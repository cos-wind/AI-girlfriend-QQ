from __future__ import annotations

import json
import re
from typing import Any


def is_poke_event(event: dict[str, Any]) -> bool:
    """判断 OneBot 通知是否为戳一戳事件。

    戳一戳在 OneBot v11 中不是普通 message，而是 notice 事件。先在
    OneBot 适配层识别，后续再归一化为 ATRI 可以复用的普通对话事件。
    """

    return (
        str(event.get("post_type") or "").lower() == "notice"
        and (
            str(event.get("notice_type") or "").lower() == "poke"
            or str(event.get("sub_type") or "").lower() == "poke"
        )
    )


def normalize_poke_event(event: dict[str, Any], bot_qq: int) -> dict[str, Any] | None:
    """把“戳到亚托莉”的通知转换成普通消息事件。

    这里只做事件归一化，不调用 OneBot 动作，也不直接发送回戳。这样
    戳一戳会自然进入现有的回复策略、人格、记忆、语音和表情包流程。
    戳到其他人的通知返回 ``None``，避免机器人误回复。
    """

    if not is_poke_event(event):
        return None
    target_id = _as_int(event.get("target_id"))
    actor_id = _as_int(event.get("user_id"))
    if target_id != int(bot_qq) or actor_id is None or actor_id == int(bot_qq):
        return None

    normalized = dict(event)
    normalized.update(
        {
            "post_type": "message",
            "message_type": "group" if event.get("group_id") is not None else "private",
            "sub_type": "poke",
            "message": [
                {
                    "type": "text",
                    "data": {"text": "[用户戳了戳亚托莉]"},
                }
            ],
            "raw_message": "[用户戳了戳亚托莉]",
            "_atri_poke_event": True,
        }
    )
    return normalized


def extract_reply_message_id(message: Any) -> str | None:
    """从消息段或 NapCat 的 reply 对象中提取被引用消息 ID。"""

    if isinstance(message, list):
        for segment in message:
            result = extract_reply_message_id(segment)
            if result:
                return result
        return None
    if not isinstance(message, dict):
        return None

    if str(message.get("type") or "").lower() == "reply":
        data = message.get("data") or {}
        value = data.get("id") or data.get("message_id")
        return str(value) if value not in (None, "") else None

    for key in ("message_id", "id"):
        value = message.get(key)
        if value not in (None, "") and ("message" in message or "sender" in message):
            return str(value)
    nested = message.get("message")
    return extract_reply_message_id(nested) if nested is not None else None


def extract_reply_inline_message(event: dict[str, Any]) -> Any | None:
    """读取事件中可能直接携带的引用原文，避免不必要的 get_msg 请求。"""

    reply = event.get("reply")
    if isinstance(reply, dict):
        if reply.get("message") is not None:
            return reply.get("message")
        for key in ("raw_message", "text"):
            if reply.get(key):
                return reply[key]
    return None


def extract_plain_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()

    if not isinstance(message, list):
        return str(message).strip()

    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue

        segment_type = segment.get("type")
        data = segment.get("data") or {}

        if segment_type == "text":
            parts.append(str(data.get("text", "")))
        elif segment_type == "at":
            qq = str(data.get("qq", ""))
            parts.append("@全体成员" if qq == "all" else "@群友")
        elif segment_type == "face":
            face_id = data.get("id") or data.get("face_id")
            parts.append(f"[QQ表情:{face_id}]" if face_id else "[QQ表情]")
        elif segment_type in {"mface", "marketface"}:
            summary = data.get("summary") or data.get("text") or data.get("name") or data.get("emoji_id")
            parts.append(f"[动画表情:{summary}]" if summary else "[动画表情]")
        elif segment_type == "image":
            summary = data.get("summary") or data.get("sub_type") or data.get("file") or data.get("url")
            if summary:
                parts.append(f"[表情包/图片:{summary}]")
            else:
                parts.append("[表情包/图片]")
        elif segment_type == "record":
            parts.append("[语音]")
        elif segment_type == "video":
            summary = data.get("summary") or data.get("title") or data.get("name") or data.get("file") or data.get("url")
            parts.append(f"[视频:{summary}]" if summary else "[视频]")
        elif segment_type == "file":
            summary = (
                data.get("name")
                or data.get("file_name")
                or data.get("filename")
                or data.get("file")
                or data.get("url")
                or data.get("file_id")
            )
            parts.append(f"[文件:{summary}]" if summary else "[文件]")
        elif segment_type in {"json", "xml", "share"}:
            summary = _share_segment_summary(data)
            parts.append(f"[分享:{summary}]" if summary else "[分享]")

    return "".join(parts).strip()


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _share_segment_summary(data: dict[str, Any]) -> str:
    raw = data.get("data") if "data" in data else data
    values: list[Any] = [data, raw]
    parsed = _parse_json_text(raw)
    if parsed is not None:
        values.append(parsed)

    title = _first_nested_text(values, {"title", "prompt", "desc", "summary"})
    url = _first_nested_url(values)
    if title and url:
        return f"{title} {url}"
    return title or url


def _parse_json_text(value: Any) -> Any | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _first_nested_text(values: list[Any], keys: set[str]) -> str:
    for value in values:
        result = _find_nested_text(value, keys)
        if result:
            return _compact_summary(result)
    return ""


def _find_nested_text(value: Any, keys: set[str]) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in keys and isinstance(item, (str, int, float)):
                text = str(item).strip()
                if text and not text.startswith(("http://", "https://")):
                    return text
            result = _find_nested_text(item, keys)
            if result:
                return result
    elif isinstance(value, list):
        for item in value:
            result = _find_nested_text(item, keys)
            if result:
                return result
    elif isinstance(value, str):
        match = re.search(r"<(?:title|summary|desc)[^>]*>(.*?)</(?:title|summary|desc)>", value, re.I | re.S)
        if match:
            return match.group(1)
    return ""


def _first_nested_url(values: list[Any]) -> str:
    for value in values:
        result = _find_nested_url(value)
        if result:
            return result
    return ""


def _find_nested_url(value: Any) -> str:
    if isinstance(value, dict):
        for item in value.values():
            result = _find_nested_url(item)
            if result:
                return result
    elif isinstance(value, list):
        for item in value:
            result = _find_nested_url(item)
            if result:
                return result
    elif isinstance(value, str):
        match = re.search(r"https?://[^\s<>\]）)\"']+", value)
        if match:
            return match.group(0).rstrip("，。！？!?")
    return ""


def _compact_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:120]
