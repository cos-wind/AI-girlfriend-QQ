from __future__ import annotations

from typing import Any

from ..stickers import StickerManager
from .schema import OutgoingMessage
from .splitting import split_reply_text


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
