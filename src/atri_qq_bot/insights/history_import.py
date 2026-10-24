"""按需读取 QQ 客户端历史消息。

本模块不监听实时 OneBot 事件。用户在 WebUI 点击“生成并保存/发送”时，
由调用方从当前登录的 QQ/NapCat 内核读取目标群的历史消息。手动生成日报
直接使用该次规范化快照，因此报告不依赖亚托莉在聊天发生时是否运行，也不会
混入旧的实时归档缓存。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .store import InsightsStore


def normalize_group_history(
    group_id: str,
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int | str]]:
    """将一次 QQ 历史读取转换为独立、可分析的消息快照。"""

    normalized_group_id = str(group_id or "").strip()
    if not normalized_group_id:
        raise ValueError("群号不能为空")
    messages: list[dict[str, Any]] = []
    ignored = 0
    seen: set[str] = set()
    for event in events:
        item = _normalize_event(event, normalized_group_id)
        if item is None:
            ignored += 1
            continue
        message_key = str(item["message_key"])
        if message_key in seen:
            continue
        seen.add(message_key)
        # 本次读取不写回实时归档；消息键仅保留在内存中用于去重和兼容已有
        # 的 ``import_group_history`` 辅助函数，不参与报告内容。
        messages.append(item)
    messages.sort(key=lambda item: str(item["created_at"]))
    return messages, {
        "source": "qq_client_history",
        "fetched": len(events),
        "accepted": len(messages),
        "ignored": ignored,
    }


def import_group_history(
    store: InsightsStore,
    group_id: str,
    events: list[dict[str, Any]],
) -> dict[str, int | str]:
    """只读导入一次 QQ 历史快照，并以 QQ 消息 ID 保证幂等。"""

    imported = 0
    duplicate = 0
    ignored = 0
    messages, snapshot = normalize_group_history(group_id, events)
    ignored = int(snapshot["ignored"])
    for item in messages:
        if store.add_group_message(**item):
            imported += 1
        else:
            duplicate += 1
    return {
        "source": "qq_client_history",
        "fetched": len(events),
        "imported": imported,
        "duplicate": duplicate,
        "ignored": ignored,
    }


def _normalize_event(event: dict[str, Any], expected_group_id: str) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    group_id = str(event.get("group_id") or expected_group_id).strip()
    if group_id != expected_group_id:
        return None
    user_id = str(event.get("user_id") or "").strip()
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    nickname = str(sender.get("card") or sender.get("nickname") or user_id or "未知成员").strip()[:200]
    message = event.get("message")
    content = _plain_text(message)
    media = _media(message)
    # 纯图片/表情也应计入群聊活跃度，避免与 QQ 客户端消息数量不一致。
    if not content:
        content = _media_placeholder(media)
    if not content:
        return None

    created_at = _event_time(event)
    message_id = str(event.get("message_id") or event.get("message_seq") or event.get("id") or "").strip()
    if not message_id:
        message_id = hashlib.sha1(
            f"{group_id}|{user_id}|{created_at}|{content}".encode("utf-8", errors="replace")
        ).hexdigest()
    return {
        # 与实时 OneBot 归档使用同一键，避免同一条消息先被实时收到、后又被
        # 手动历史补录时在日报里重复计数。
        "message_key": f"{group_id}:{message_id}",
        "group_id": group_id,
        "user_id": user_id or "unknown",
        "nickname": nickname,
        "content": content,
        "message_type": "qq_history",
        "created_at": created_at,
        "media": media,
    }


def _event_time(event: dict[str, Any]) -> str:
    value = event.get("time")
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        pass
    for key in ("time", "time_stamp", "created_at"):
        text = str(event.get(key) or "").strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, list):
        return ""
    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        kind = str(segment.get("type") or "").lower()
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "at":
            target = str(data.get("qq") or "")
            parts.append("@全体成员" if target == "all" else "@群友")
        elif kind == "face":
            parts.append("[QQ表情]")
        elif kind in {"mface", "marketface"}:
            parts.append("[动画表情]")
        elif kind == "image":
            parts.append("[图片]")
        elif kind == "record":
            parts.append("[语音]")
        elif kind == "video":
            parts.append("[视频]")
        elif kind == "file":
            parts.append("[文件]")
    return "".join(parts).strip()[:8000]


def _media(message: Any) -> list[dict[str, str]]:
    if not isinstance(message, list):
        return []
    result: list[dict[str, str]] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        kind = str(segment.get("type") or "").lower()
        if kind not in {"image", "mface", "face", "record", "video", "file"}:
            continue
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        url = str(data.get("url") or data.get("proxy_url") or "").strip()
        file_id = str(data.get("file") or data.get("file_id") or data.get("name") or "").strip()
        result.append({"type": kind, "url": url[:2000], "file": file_id[:300]})
    return result[:16]


def _media_placeholder(media: list[dict[str, str]]) -> str:
    if not media:
        return ""
    kind = str(media[0].get("type") or "")
    return {
        "image": "[图片]",
        "mface": "[动画表情]",
        "face": "[QQ表情]",
        "record": "[语音]",
        "video": "[视频]",
        "file": "[文件]",
    }.get(kind, "[非文本消息]")
