from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from .stickers import StickerManager


@dataclass(frozen=True)
class OutgoingMessage:
    kind: Literal["text", "image", "face"]
    content: str


def build_outgoing_messages(
    reply_text: str,
    user_text: str,
    sticker_manager: StickerManager,
    config: Any,
    profile: dict[str, Any] | None = None,
) -> list[OutgoingMessage]:
    target_parts = int((profile or {}).get("preferred_parts") or config.message_split_max_parts)
    max_parts = max(1, min(config.message_split_max_parts, target_parts + 1))
    text_parts = split_reply_text(reply_text, config.message_split_max_chars, max_parts)

    sticker = sticker_manager.choose(
        user_text,
        reply_text,
        config.sticker_chance,
        profile,
        config.sticker_cooldown_seconds,
    )
    if sticker and sticker.emoji_text and text_parts:
        text_parts[-1] = _append_light_emoji(text_parts[-1], sticker.emoji_text)

    messages = [OutgoingMessage("text", part) for part in text_parts if part]
    if sticker and sticker.file_url:
        messages.append(OutgoingMessage("image", sticker.file_url))
    elif sticker and sticker.face_id:
        messages.append(OutgoingMessage("face", sticker.face_id))

    return messages or [OutgoingMessage("text", reply_text.strip() or "嗯，我在。")]


def split_reply_text(text: str, max_chars: int = 44, max_parts: int = 4) -> list[str]:
    text = _compact_reply_text(text)
    if not text:
        return []

    raw_sentences = _sentence_chunks(text)
    pieces: list[str] = []
    for sentence in raw_sentences:
        pieces.extend(_hard_wrap(sentence, max_chars))

    merged: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if merged and len(merged[-1]) + len(piece) <= max_chars and not _ends_with_strong_punctuation(merged[-1]):
            merged[-1] = f"{merged[-1]}{piece}"
        else:
            merged.append(piece)

    if len(merged) <= max_parts:
        return merged

    kept = merged[: max_parts - 1]
    tail = "".join(merged[max_parts - 1 :])
    kept.append(_truncate_tail(tail, max_chars * 2))
    return kept


def outgoing_to_onebot_message(message: OutgoingMessage) -> str | list[dict[str, Any]]:
    if message.kind == "text":
        return message.content
    if message.kind == "face":
        face_id: int | str = int(message.content) if message.content.isdigit() else message.content
        return [{"type": "face", "data": {"id": face_id}}]
    return [{"type": "image", "data": {"file": message.content, "cache": 0}}]


def _compact_reply_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text.strip())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _sentence_chunks(text: str) -> list[str]:
    chunks = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    cleaned = [chunk.strip() for chunk in chunks if chunk.strip()]
    return cleaned or [text]


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    remaining = text
    soft_marks = "，,、 "
    while len(remaining) > max_chars:
        split_at = max(remaining.rfind(mark, 0, max_chars + 1) for mark in soft_marks)
        if split_at < max_chars // 2:
            split_at = max_chars
        part = remaining[: split_at + 1].strip()
        remaining = remaining[split_at + 1 :].strip()
        if part:
            parts.append(part)
    if remaining:
        parts.append(remaining)
    return parts


def _ends_with_strong_punctuation(text: str) -> bool:
    return text.endswith(("。", "！", "？", "!", "?", "；", ";"))


def _truncate_tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _append_light_emoji(text: str, emoji_text: str) -> str:
    if not emoji_text:
        return text
    if emoji_text in text:
        return text
    if len(text) + len(emoji_text) + 1 > 64:
        return text
    if text.endswith(("。", "！", "？", "!", "?")):
        return f"{text[:-1]}，{emoji_text}{text[-1]}"
    return f"{text} {emoji_text}"
