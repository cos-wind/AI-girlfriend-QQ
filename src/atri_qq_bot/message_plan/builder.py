from __future__ import annotations

from typing import Any

from ..stickers import StickerManager
from ..sticker_media import prepare_local_sticker
from .schema import OutgoingMessage
from .splitting import split_reply_text


def build_outgoing_messages(
    reply_text: str,
    user_text: str,
    sticker_manager: StickerManager,
    config: Any,
    profile: dict[str, Any] | None = None,
) -> list[OutgoingMessage]:
    # 业务层只返回文本意图；这里负责把它编译成 OneBot 可发送的消息计划。
    # 人格引擎因此不需要依赖 QQ segment 的具体格式。
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
        if sticker.local:
            sticker_path = prepare_local_sticker(sticker.file_url)
            messages.append(
                OutgoingMessage(
                    "sticker",
                    sticker_path,
                    sub_type=1,
                    summary="[动画表情]",
                )
            )
        else:
            messages.append(OutgoingMessage("image", sticker.file_url))
    elif sticker and sticker.face_id:
        messages.append(OutgoingMessage("face", sticker.face_id))

    # 空文本代表上游模型失败或被安全策略拦截，必须保持静默。
    # 这里不能再补发“嗯，我在”之类的模板，否则会把失败伪装成正常回复。
    return messages


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
