from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

KNOWN_EMOTIONS = {
    "happy",
    "comfort",
    "sad",
    "angry",
    "tired",
    "proud",
    "confused",
    "speechless",
    "surprised",
    "awkward",
    "teasing",
    "shy",
    "affection",
    "miss",
    "care",
    "thanks",
    "sorry",
    "encourage",
    "thinking",
    "celebrate",
    "food",
    "goodnight",
    "pout",
    "neutral",
    "unsorted",
}

EMOTION_PRIORITY = {
    "sad": 102,
    "comfort": 100,
    "angry": 99,
    "goodnight": 95,
    "tired": 90,
    "pout": 82,
    "shy": 78,
    "affection": 76,
    "miss": 74,
    "care": 72,
    "confused": 70,
    "speechless": 69,
    "surprised": 68,
    "teasing": 67,
    "awkward": 66,
    "food": 64,
    "thinking": 62,
    "encourage": 60,
    "proud": 58,
    "thanks": 56,
    "sorry": 54,
    "celebrate": 52,
    "happy": 50,
    "neutral": 0,
    "unsorted": -1,
}

DEFAULT_EMOTION_KEYWORDS = {
    "happy": ("开心", "好耶", "哈哈", "嘿嘿", "笑死", "喜欢", "成功", "太好了", "棒", "厉害"),
    "comfort": ("难受", "难过", "烦", "焦虑", "压力", "崩溃", "委屈", "哭", "emo", "不开心", "心累", "破防"),
    "sad": ("想哭", "低落", "失落", "心碎", "emo了", "没人懂", "孤独", "空落落"),
    "angry": ("生气", "气死", "火大", "恼火", "红温", "无语死", "受不了", "欺负我"),
    "tired": ("累", "困", "疲惫", "不想动", "睡觉", "熬夜", "撑不住"),
    "proud": ("高性能", "夸我", "厉害吧", "做到啦", "启动成功", "亚托莉", "主人真厉害"),
    "confused": ("怎么", "为什么", "不懂", "错了", "答非所问", "？", "?", "抽象", "逆天", "离谱", "6"),
    "speechless": ("无语", "嫌弃", "不想理", "沉默", "呆住", "呆滞", "冷漠", "麻了", "没眼看"),
    "surprised": ("真的假的", "震惊", "惊了", "啊这", "不会吧", "这么突然"),
    "awkward": ("尴尬", "社死", "汗流浃背", "绷不住了", "难绷", "救命"),
    "teasing": ("调侃", "逗你", "阴阳怪气", "我超怕的", "怕了吧", "就这", "略略", "才不是"),
    "shy": ("喜欢你", "想你", "爱你", "抱抱", "亲亲", "涩涩", "不准涩涩", "给我忘掉"),
    "affection": ("贴贴", "抱一下", "抱住", "亲密", "撒娇", "陪陪我"),
    "miss": ("想我了吗", "有没有想我", "想你了", "突然想你", "等你", "冷落我"),
    "care": ("喝水", "吃药", "注意身体", "别硬撑", "休息一下", "照顾好自己"),
    "thanks": ("谢谢", "感谢", "辛苦你了", "帮大忙", "有你真好"),
    "sorry": ("对不起", "抱歉", "我错了", "不是故意", "原谅我"),
    "encourage": ("加油", "冲", "努力", "开始做", "坚持", "打起精神", "可以做到"),
    "thinking": ("纠结", "考虑", "想想", "该不该", "要不要", "选哪个", "怎么选"),
    "celebrate": ("庆祝", "赢了", "完成了", "搞定", "通过了", "顺利", "开香槟"),
    "food": ("吃什么", "饿", "吃饭", "早餐", "午饭", "晚饭", "夜宵"),
    "goodnight": ("晚安", "睡了", "睡觉", "困了"),
    "pout": ("冷落", "忘了我", "终于想起我", "萝卜子", "哼哒"),
}

DEFAULT_EMOJIS = {
    "happy": ("嘿嘿", "♪", "(*´▽｀*)", "今天也要亮起来"),
    "comfort": ("摸摸头", "我在", "先靠过来一点"),
    "sad": ("先别一个人扛", "别急，我陪你", "靠过来一点"),
    "angry": ("哼，我站你这边", "不准欺负主人", "先别红温"),
    "tired": ("早点休息", "困困信号收到", "不准硬撑"),
    "proud": ("哼哼，高性能模式", "(｀・ω・´)", "任务完成"),
    "confused": ("欸？", "让我重新对齐一下"),
    "speechless": ("……高性能沉默", "有点无语", "我先看你一眼"),
    "surprised": ("欸？！", "这也太突然了", "高性能震惊中"),
    "awkward": ("有点难绷", "咳，先稳住", "救命但还行"),
    "teasing": ("哼哼，逗你的", "我才没有故意气你", "略微调侃一下"),
    "shy": ("有点犯规", "……我会记住的"),
    "affection": ("抱一下", "贴贴可以，但不准得意太久", "我在你这边"),
    "miss": ("我才没有一直等你", "突然想你了", "你终于想起我啦"),
    "care": ("先喝口水", "不准硬撑", "照顾好自己"),
    "thanks": ("哼，还算你会夸", "我收下啦", "高性能当然可靠"),
    "sorry": ("原谅你一点点", "下次不准这样", "给你台阶啦"),
    "encourage": ("先迈一步", "高性能陪跑中", "你可以做到"),
    "thinking": ("让我想想", "先拆成两步", "我更偏务实一点"),
    "celebrate": ("好耶，完成！", "任务完成 ♪", "今天值得小小庆祝"),
    "food": ("先吃饭", "能量补给优先"),
    "goodnight": ("晚安", "做个轻一点的梦"),
    "pout": ("哼哒", "你终于想起我啦"),
    "neutral": ("嗯嗯", "收到"),
}

DEFAULT_QQ_FACE_IDS = {
    "happy": ("14", "21", "76", "144"),
    "comfort": ("49", "63", "66"),
    "tired": ("36", "37", "96"),
    "proud": ("13", "76", "124"),
    "confused": ("8", "32", "97"),
    "speechless": ("8", "97", "32"),
    "shy": ("9", "66", "178"),
    "food": ("28", "124"),
    "goodnight": ("75", "96"),
    "pout": ("1", "13", "46"),
    "sad": ("49", "63", "66"),
    "angry": ("5", "11", "46"),
    "surprised": ("0", "8", "97"),
    "awkward": ("10", "8", "97"),
    "teasing": ("21", "13", "76"),
    "affection": ("66", "9", "178"),
    "miss": ("9", "66", "49"),
    "care": ("63", "49", "66"),
    "thanks": ("76", "21", "14"),
    "sorry": ("9", "49", "63"),
    "encourage": ("76", "124", "21"),
    "thinking": ("32", "8", "97"),
    "celebrate": ("144", "76", "21"),
}


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

        image_path = forced_image or self._pick_image(emotion)
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
        if not self.sticker_dir.exists():
            return []

        manual_candidates = _image_files_in_dir(self.sticker_dir / emotion)
        manual_candidates.extend(
            path
            for path in self.sticker_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            and path.stem.lower().startswith(emotion.lower())
        )
        if manual_candidates:
            return sorted(set(manual_candidates))

        for emotion_dir in (
            self.sticker_dir / "_curated" / emotion,
            self.sticker_dir / "_chat_history" / emotion,
            self.sticker_dir / "_online_default" / emotion,
        ):
            candidates = _image_files_in_dir(emotion_dir)
            if candidates:
                return sorted(set(candidates))

        return []

    def _resolve_file(self, value: Any) -> Path | None:
        if not value:
            return None
        path = Path(str(value))
        if not path.is_absolute():
            path = self.sticker_dir / path
        if path.exists() and path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _image_files_in_dir(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
    ]


def _normalize_emotion(emotion: str) -> str:
    emotion = str(emotion or "neutral").strip().lower()
    aliases = {
        "sad": "sad",
        "cry": "sad",
        "angry": "angry",
        "sleepy": "tired",
        "night": "goodnight",
        "question": "confused",
        "unamused": "speechless",
        "speechless": "speechless",
        "tease": "teasing",
        "teasing": "teasing",
        "love": "shy",
        "loving": "affection",
        "missing": "miss",
        "encouragement": "encourage",
        "think": "thinking",
        "celebration": "celebrate",
        "web": "web",
    }
    normalized = aliases.get(emotion, emotion)
    if normalized == "web":
        return normalized
    return normalized if normalized in KNOWN_EMOTIONS else "neutral"


def _score_emotion(
    text: str,
    emotion_keywords: dict[str, tuple[str, ...]],
    weight: int,
) -> dict[str, int]:
    if not text:
        return {}

    scores: dict[str, int] = {}
    for emotion, keywords in emotion_keywords.items():
        normalized = _normalize_emotion(emotion)
        if normalized in {"neutral", "unsorted", "web"}:
            continue
        for keyword in keywords:
            keyword = str(keyword).strip()
            if keyword and keyword in text:
                scores[normalized] = scores.get(normalized, 0) + weight
    return scores


def _looks_like_image(value: str) -> bool:
    return Path(value).suffix.lower() in IMAGE_EXTENSIONS


def _looks_like_url(value: Any) -> bool:
    if not value:
        return False
    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _in_cooldown(profile: dict[str, Any] | None, cooldown_seconds: int) -> bool:
    if cooldown_seconds <= 0 or not profile:
        return False
    last_sticker_at = profile.get("last_sticker_at")
    try:
        if last_sticker_at is None:
            return False
        return time.time() - float(last_sticker_at) < cooldown_seconds
    except (TypeError, ValueError):
        return False


def _first_url(data: dict[str, Any]) -> str | None:
    for key in ("url", "file_url", "preview", "origin_url"):
        value = data.get(key)
        if _looks_like_url(value):
            return str(value)
    return None


def _suffix_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    return ".jpg"


def _write_capture_metadata(path: Path, url: str, emotion: str, content_type: str) -> None:
    metadata = {
        "source": "chat_history",
        "url": url,
        "emotion": emotion,
        "content_type": content_type,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
