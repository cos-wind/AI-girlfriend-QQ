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

from .sticker_parts import core as _sticker_core


IMAGE_EXTENSIONS = _sticker_core.IMAGE_EXTENSIONS
CONTENT_TYPE_EXTENSIONS = _sticker_core.CONTENT_TYPE_EXTENSIONS
KNOWN_EMOTIONS = _sticker_core.KNOWN_EMOTIONS
EMOTION_PRIORITY = _sticker_core.EMOTION_PRIORITY
DEFAULT_EMOTION_KEYWORDS = _sticker_core.DEFAULT_EMOTION_KEYWORDS
DEFAULT_EMOJIS = _sticker_core.DEFAULT_EMOJIS
DEFAULT_QQ_FACE_IDS = _sticker_core.DEFAULT_QQ_FACE_IDS



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

