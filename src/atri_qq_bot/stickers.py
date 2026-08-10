from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .sticker_parts import core as _sticker_core


IMAGE_EXTENSIONS = _sticker_core.IMAGE_EXTENSIONS
CONTENT_TYPE_EXTENSIONS = _sticker_core.CONTENT_TYPE_EXTENSIONS
KNOWN_EMOTIONS = _sticker_core.KNOWN_EMOTIONS
EMOTION_PRIORITY = _sticker_core.EMOTION_PRIORITY
DEFAULT_EMOTION_KEYWORDS = _sticker_core.DEFAULT_EMOTION_KEYWORDS
DEFAULT_EMOJIS = _sticker_core.DEFAULT_EMOJIS
DEFAULT_QQ_FACE_IDS = _sticker_core.DEFAULT_QQ_FACE_IDS

_FILENAME_EMOTION_HINTS = {
    "happy": ("哈哈", "开心", "满意", "热情", "可爱"),
    "comfort": ("理解",),
    "sad": ("呜呜", "疼"),
    "angry": ("生气", "攻击", "火箭拳", "警告", "拒绝"),
    "tired": ("好累", "好热", "懒"),
    "proud": ("高性能", "自信", "认可", "赞美", "满意"),
    "confused": ("疑惑", "啊", "诶"),
    "speechless": ("无语", "不屑"),
    "surprised": ("惊喜", "啊", "诶"),
    "awkward": ("心虚", "掩饰", "装傻"),
    "teasing": ("调皮", "搞怪", "抽象", "轻浮", "捡回一条小命", "装傻", "嘴硬"),
    "shy": ("害羞",),
    "affection": ("撒娇", "请求"),
    "encourage": ("加油",),
    "thinking": ("若有所思", "让我想想", "果然如此"),
    "pout": ("傲娇", "不服", "委屈", "不快", "嘴硬"),
}
_FILENAME_CONTEXT_ALIASES = {
    "生气": ("气死", "火大", "恼火", "红温", "过分"),
    "攻击": ("攻击", "打他", "揍", "火箭拳", "欺负"),
    "警告": ("警告", "不许", "不准", "注意点"),
    "拒绝": ("拒绝", "不要", "不可以", "不行"),
    "哈哈": ("好笑", "笑死", "绷不住"),
    "理解": ("理解", "明白", "懂你", "我懂"),
    "呜呜": ("想哭", "哭了", "难过", "伤心"),
    "疼": ("疼", "痛", "受伤"),
    "好累": ("累", "疲惫", "撑不住"),
    "懒": ("懒", "不想动"),
    "高性能": ("高性能", "完成", "搞定", "成功"),
    "疑惑": ("疑惑", "不懂", "为什么", "怎么回事"),
    "无语": ("无语", "麻了", "没眼看"),
    "不屑": ("不屑", "嫌弃", "就这"),
    "惊喜": ("惊喜", "惊了", "不会吧", "真的假的"),
    "心虚": ("心虚", "被发现", "露馅"),
    "装傻": ("装傻", "不知道", "别问我"),
    "调皮": ("调皮", "逗你", "开玩笑"),
    "搞怪": ("搞怪", "抽象", "整活"),
    "轻浮": ("轻浮", "阴阳怪气", "逗你"),
    "害羞": ("害羞", "喜欢你", "爱你", "亲亲"),
    "撒娇": ("撒娇", "求求", "拜托", "陪我"),
    "加油": ("加油", "努力", "坚持", "开始做"),
    "若有所思": ("考虑", "想想", "纠结", "怎么选"),
    "傲娇": ("傲娇", "嘴硬", "才不是"),
    "委屈": ("委屈", "欺负我", "不开心"),
}
_FILENAME_SPLIT_RE = re.compile(r"[\s,，、;；。.!！?？_\-—()（）【】\[\]{}]+")


@dataclass(frozen=True)
class StickerChoice:
    emotion: str
    file_url: str | None = None
    face_id: str | None = None
    emoji_text: str | None = None
    triggered: bool = False


class StickerManager:
    def __init__(self, sticker_dir: Path, trigger_file: Path | None = None) -> None:
        self.sticker_dir = sticker_dir
        self.trigger_file = trigger_file or sticker_dir / "triggers.json"
        self._custom = self._load_custom_config()

    def detect_emotion(self, user_text: str, reply_text: str = "") -> str:
        matched = self._match_custom_trigger(user_text)
        if matched:
            return _normalize_emotion(matched[0])

        emotion_keywords = dict(DEFAULT_EMOTION_KEYWORDS)
        custom_keywords = self._custom.get("emotion_keywords")
        if isinstance(custom_keywords, dict):
            for emotion, keywords in custom_keywords.items():
                emotion = _normalize_emotion(str(emotion))
                emotion_keywords[emotion] = tuple(map(str, _as_list(keywords)))

        user_emotion = _score_emotion(user_text, emotion_keywords, weight=3)
        reply_emotion = _score_emotion(reply_text, emotion_keywords, weight=1)
        scores = dict(reply_emotion)
        for emotion, score in user_emotion.items():
            scores[emotion] = scores.get(emotion, 0) + score

        if not scores:
            return "neutral"

        return max(
            scores,
            key=lambda emotion: (scores[emotion], EMOTION_PRIORITY.get(emotion, 0)),
        )

    def choose(
        self,
        user_text: str,
        reply_text: str,
        chance: float,
        profile: dict[str, Any] | None = None,
        cooldown_seconds: int = 0,
    ) -> StickerChoice | None:
        triggered = False
        emotion = "neutral"
        forced_image: Path | str | None = None

        custom_match = self._match_custom_trigger(user_text)
        if custom_match:
            emotion, forced_image = custom_match
            emotion = _normalize_emotion(emotion)
            triggered = True
        else:
            emotion = self.detect_emotion(user_text, reply_text)

        if not triggered and _in_cooldown(profile, cooldown_seconds):
            return None

        if not triggered:
            adjusted_chance = self._adjusted_chance(chance, profile)
            if random.random() > adjusted_chance:
                return None

        semantic_image = self._pick_semantic_image(user_text, reply_text, emotion)
        if isinstance(forced_image, str) or (
            isinstance(forced_image, Path) and self._is_primary_file(forced_image)
        ):
            image_path = forced_image
        else:
            image_path = semantic_image or forced_image or self._pick_image(emotion)
        if isinstance(image_path, Path):
            return StickerChoice(
                emotion=emotion,
                file_url=str(image_path.resolve()),
                triggered=triggered,
            )
        if isinstance(image_path, str):
            return StickerChoice(emotion=emotion, file_url=image_path, triggered=triggered)

        face_id = self._pick_face_id(emotion)
        if face_id:
            return StickerChoice(
                emotion=emotion,
                face_id=face_id,
                emoji_text=self._pick_emoji(emotion),
                triggered=triggered,
            )

        emoji = self._pick_emoji(emotion)
        if emoji:
            return StickerChoice(emotion=emotion, emoji_text=emoji, triggered=triggered)
        return None

    def _adjusted_chance(self, chance: float, profile: dict[str, Any] | None) -> float:
        chance = max(0.0, min(1.0, chance))
        if not profile:
            return chance
        if float(profile.get("emoji_rate") or 0.0) >= 0.35:
            return min(0.8, chance + 0.16)
        if int(profile.get("message_count") or 0) <= 2:
            return min(chance, 0.18)
        return chance

    def _match_custom_trigger(self, text: str) -> tuple[str, Path | str | None] | None:
        trigger_words = self._custom.get("trigger_words")
        if not isinstance(trigger_words, dict):
            return None

        for trigger, target in trigger_words.items():
            if str(trigger) not in text:
                continue

            if isinstance(target, dict):
                emotion = _normalize_emotion(str(target.get("emotion") or "happy"))
                file_value = target.get("file")
            else:
                raw_target = str(target)
                if _looks_like_url(raw_target):
                    return "web", raw_target
                if _looks_like_image(raw_target):
                    file_path = self._resolve_file(raw_target)
                    return _normalize_emotion(file_path.stem if file_path else "happy"), file_path
                emotion = _normalize_emotion(raw_target)
                file_value = None

            file_path = self._resolve_file(file_value) if file_value else None
            if file_path is None and _looks_like_url(file_value):
                return emotion, str(file_value)
            return emotion, file_path

        return None

    def _pick_image(self, emotion: str) -> Path | str | None:
        emotion = _normalize_emotion(emotion)
        if emotion in {"neutral", "unsorted"}:
            return None

        candidates = self._images_for_emotion(emotion)
        if candidates:
            return random.choice(candidates)
        return self._pick_web_image(emotion)

    def _images_for_emotion(self, emotion: str) -> list[Path]:
        roots = self._library_roots()
        for root in roots:
            if not root.exists():
                continue
            manual_candidates = _image_files_in_dir(root / emotion)
            manual_candidates.extend(
                path
                for path in root.iterdir()
                if path.is_file()
                and path.suffix.lower() in IMAGE_EXTENSIONS
                and path.stem.lower().startswith(emotion.lower())
            )
            if manual_candidates:
                return sorted(set(manual_candidates))

        for root in roots:
            for emotion_dir in (
                root / "_curated" / emotion,
                root / "_chat_history" / emotion,
                root / "_online_default" / emotion,
            ):
                candidates = _image_files_in_dir(emotion_dir)
                if candidates:
                    return sorted(set(candidates))

        return []

    def _pick_semantic_image(
        self,
        user_text: str,
        reply_text: str,
        emotion: str,
    ) -> Path | None:
        if not self.sticker_dir.exists():
            return None

        scored: list[tuple[int, Path]] = []
        for path in self.sticker_dir.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.lower() not in IMAGE_EXTENSIONS
                or any(part.startswith("_") for part in path.relative_to(self.sticker_dir).parts[:-1])
            ):
                continue
            score = _semantic_filename_score(path.stem, user_text, reply_text, emotion)
            if score > 0:
                scored.append((score, path))

        if not scored:
            return None
        best_score = max(score for score, _ in scored)
        return random.choice([path for score, path in scored if score == best_score])

    def _library_roots(self) -> list[Path]:
        roots = [self.sticker_dir]
        trigger_root = self.trigger_file.parent
        try:
            same_root = trigger_root.resolve() == self.sticker_dir.resolve()
        except OSError:
            same_root = trigger_root == self.sticker_dir
        if not same_root:
            roots.append(trigger_root)
        return roots

    def _is_primary_file(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.sticker_dir.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _resolve_file(self, value: Any) -> Path | None:
        if not value:
            return None
        path = Path(str(value))
        candidates = [path] if path.is_absolute() else [
            self.sticker_dir / path,
            self.trigger_file.parent / path,
        ]
        for candidate in candidates:
            if (
                candidate.exists()
                and candidate.is_file()
                and candidate.suffix.lower() in IMAGE_EXTENSIONS
            ):
                return candidate
        return None

    def _pick_web_image(self, emotion: str) -> str | None:
        web_images = self._custom.get("web_images")
        if not isinstance(web_images, dict):
            return None

        urls = _as_list(web_images.get(emotion))
        urls = [str(url) for url in urls if _looks_like_url(url)]
        if not urls:
            return None
        return random.choice(urls)

    def _pick_emoji(self, emotion: str) -> str | None:
        custom_emojis = self._custom.get("emotion_emojis")
        if isinstance(custom_emojis, dict) and emotion in custom_emojis:
            values = _as_list(custom_emojis[emotion])
            if values:
                return str(random.choice(values))

        values = DEFAULT_EMOJIS.get(emotion) or DEFAULT_EMOJIS.get("neutral", ())
        return random.choice(values) if values else None

    def _pick_face_id(self, emotion: str) -> str | None:
        custom_faces = self._custom.get("emotion_faces")
        if isinstance(custom_faces, dict) and emotion in custom_faces:
            values = [str(value) for value in _as_list(custom_faces[emotion]) if str(value).strip()]
            if values:
                return random.choice(values)

        values = DEFAULT_QQ_FACE_IDS.get(emotion)
        if not values:
            return None
        return random.choice(values)

    async def capture_from_event(
        self,
        event: dict[str, Any],
        context_text: str,
        enabled: bool = True,
        max_bytes: int = 3_000_000,
    ) -> list[Path]:
        if not enabled:
            return []

        message = event.get("message")
        if not isinstance(message, list):
            return []

        emotion = self.detect_emotion(context_text)
        if emotion == "neutral":
            emotion = "unsorted"
        saved: list[Path] = []
        for index, segment in enumerate(message):
            if not isinstance(segment, dict):
                continue
            if segment.get("type") not in {"image", "mface", "marketface"}:
                continue

            data = segment.get("data") or {}
            url = _first_url(data)
            if not url:
                continue

            path = await self._download_sticker_url(url, emotion, index, max_bytes)
            if path:
                saved.append(path)

        return saved

    async def _download_sticker_url(
        self,
        url: str,
        emotion: str,
        index: int,
        max_bytes: int,
    ) -> Path | None:
        import httpx

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:
            print(f"[stickers] capture download failed: {exc}")
            return None

        content = response.content
        if not content or len(content) > max_bytes:
            return None

        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        suffix = CONTENT_TYPE_EXTENSIONS.get(content_type)
        if not suffix:
            suffix = _suffix_from_url(url)
        if suffix not in IMAGE_EXTENSIONS:
            return None

        digest = hashlib.sha1(content).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = self.sticker_dir / "_chat_history" / emotion
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"chat_{timestamp}_{index}_{digest}{suffix}"

        if not target.exists():
            target.write_bytes(content)
            _write_capture_metadata(target, url, emotion, content_type)
            print(f"[stickers] captured chat sticker: {target}")
        return target

    def _load_custom_config(self) -> dict[str, Any]:
        if not self.trigger_file.exists():
            return {}
        try:
            data = json.loads(self.trigger_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def _semantic_filename_score(
    stem: str,
    user_text: str,
    reply_text: str,
    emotion: str,
) -> int:
    terms = [term.strip().lower() for term in _FILENAME_SPLIT_RE.split(stem) if term.strip()]
    if not terms:
        return 0

    user_normalized = _normalize_semantic_text(user_text)
    reply_normalized = _normalize_semantic_text(reply_text)
    score = 0
    for term in terms:
        normalized_term = _normalize_semantic_text(term)
        if not normalized_term:
            continue
        if normalized_term in user_normalized:
            score += 28 + min(12, len(normalized_term) * 2)
        if normalized_term in reply_normalized:
            score += 34 + min(12, len(normalized_term) * 2)
        for label, aliases in _FILENAME_CONTEXT_ALIASES.items():
            if _normalize_semantic_text(label) not in normalized_term:
                continue
            if any(_normalize_semantic_text(alias) in user_normalized for alias in aliases):
                score += 18
            if any(_normalize_semantic_text(alias) in reply_normalized for alias in aliases):
                score += 22

    normalized_emotion = _normalize_emotion(emotion)
    for hint in _FILENAME_EMOTION_HINTS.get(normalized_emotion, ()):
        if _normalize_semantic_text(hint) in _normalize_semantic_text(stem):
            score += 12
    return score


def _normalize_semantic_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


_as_list = _sticker_core._as_list
_image_files_in_dir = _sticker_core._image_files_in_dir
_normalize_emotion = _sticker_core._normalize_emotion
_score_emotion = _sticker_core._score_emotion
_looks_like_image = _sticker_core._looks_like_image
_looks_like_url = _sticker_core._looks_like_url
_in_cooldown = _sticker_core._in_cooldown
_first_url = _sticker_core._first_url
_suffix_from_url = _sticker_core._suffix_from_url
_write_capture_metadata = _sticker_core._write_capture_metadata

