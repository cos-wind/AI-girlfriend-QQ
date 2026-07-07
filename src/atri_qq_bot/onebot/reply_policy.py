from __future__ import annotations

from typing import Any

from .message_parser import extract_plain_text


SMART_GROUP_TRIGGERS = (
    "萝卜子",
    "高性能",
    "哼哒",
    "给我忘掉",
    "不准涩涩",
    "涩涩",
    "帮我看看",
    "帮忙看看",
    "分析一下",
    "分析这个",
    "总结一下",
    "总结这个",
    "评价一下",
    "评价这个",
    "锐评",
    "解读一下",
    "识图",
    "看看这个",
    "看看这张",
    "看这个视频",
    "抽象",
)


def is_bot_mentioned(event: dict[str, Any], bot_qq: int, plain_text: str) -> bool:
    message = event.get("message")
    if isinstance(message, list):
        for segment in message:
            if not isinstance(segment, dict) or segment.get("type") != "at":
                continue
            qq = str((segment.get("data") or {}).get("qq", ""))
            if qq in {str(bot_qq), "all"}:
                return True

    lowered = plain_text.lower()
    return f"@{bot_qq}" in plain_text or "亚托莉" in plain_text or "atri" in lowered


def should_reply(
    event: dict[str, Any],
    bot_qq: int,
    reply_mode: str,
    owner_qqs: tuple[int, ...] = (),
) -> bool:
    if event.get("post_type") != "message":
        return False

    if _as_int(event.get("self_id")) not in {None, bot_qq}:
        return False

    if _as_int(event.get("user_id")) == bot_qq:
        return False

    message_type = event.get("message_type")
    if message_type == "private":
        return reply_mode in {"private", "mention", "smart", "all"}

    if message_type != "group":
        return False

    if reply_mode == "all":
        return True
    plain_text = extract_plain_text(event.get("message"))
    if reply_mode == "mention":
        return is_bot_mentioned(event, bot_qq, plain_text)
    if reply_mode == "smart":
        return _should_reply_smart_group(event, bot_qq, plain_text, owner_qqs)
    return False


def _should_reply_smart_group(
    event: dict[str, Any],
    bot_qq: int,
    plain_text: str,
    owner_qqs: tuple[int, ...] = (),
) -> bool:
    if is_bot_mentioned(event, bot_qq, plain_text):
        return True

    lowered = plain_text.lower()
    if "atri" in lowered:
        return True
    return any(trigger in plain_text for trigger in SMART_GROUP_TRIGGERS)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
