from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_GROUP_REPLY_FOCUS_TTL_SECONDS = 120.0
DEFAULT_ACTIVE_GROUP_SESSION_TTL_SECONDS = 5 * 60.0


@dataclass(frozen=True)
class GroupReplyFocus:
    actor_id: str
    nickname: str
    trigger_text: str
    focus_text: str
    source: str
    analysis_event: dict[str, Any]

    def prompt_context(self) -> str:
        display_name = self.nickname.strip() or "当前群友"
        if not self.focus_text:
            return (
                "本轮强制回复焦点：\n"
                f"回复对象：{display_name}\n"
                "焦点内容：对方本轮只艾特了你，没有附带可回答的具体内容。\n"
                "请自然回应这位群友或询问想聊什么；其他群友消息只能作为背景，"
                "不得抢答其他人的问题。"
            )
        return (
            "本轮强制回复焦点：\n"
            f"回复对象：{display_name}\n"
            f"焦点内容：{self.focus_text}\n"
            "第一句必须先回应上面的焦点内容。其他群友消息只能作为背景，"
            "除非当前回复对象明确要求讨论别人，否则不得优先回答其他人的消息。"
        )


@dataclass(frozen=True)
class _PendingGroupMessage:
    stored_at: float
    event: dict[str, Any]
    text: str
    nickname: str


@dataclass
class _ActiveGroupSession:
    expires_at: float
    nickname: str


class GroupReplyFocusStore:
    def __init__(
        self,
        ttl_seconds: float = DEFAULT_GROUP_REPLY_FOCUS_TTL_SECONDS,
        active_session_ttl_seconds: float = DEFAULT_ACTIVE_GROUP_SESSION_TTL_SECONDS,
        bot_qq: int = 100000001,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.active_session_ttl_seconds = max(30.0, float(active_session_ttl_seconds))
        self.bot_qq = int(bot_qq)
        self._pending: dict[str, _PendingGroupMessage] = {}
        self._active: dict[str, _ActiveGroupSession] = {}

    def open_session(
        self,
        event: dict[str, Any],
        *,
        nickname: str = "",
        now: float | None = None,
    ) -> None:
        key = _group_member_key(event)
        if not key:
            return
        current_time = time.time() if now is None else float(now)
        self._active[key] = _ActiveGroupSession(
            expires_at=current_time + self.active_session_ttl_seconds,
            nickname=str(nickname or "").strip(),
        )
        self._trim()

    def is_active_continuation(
        self,
        event: dict[str, Any],
        text: str,
        *,
        now: float | None = None,
    ) -> bool:
        key = _group_member_key(event)
        if not key:
            return False
        current_time = time.time() if now is None else float(now)
        session = self._active.get(key)
        if session is None:
            return False
        if current_time > session.expires_at:
            self._active.pop(key, None)
            return False
        if not _looks_like_direct_continuation(event, text, self.bot_qq):
            return False
        session.expires_at = current_time + self.active_session_ttl_seconds
        return True

    def remember(
        self,
        event: dict[str, Any],
        text: str,
        *,
        addressed_to_bot: bool,
        nickname: str = "",
        now: float | None = None,
    ) -> None:
        key = _group_member_key(event)
        if not key or addressed_to_bot:
            return
        normalized = str(text or "").strip()
        if not normalized or _is_only_generic_mentions(normalized):
            return
        self._pending[key] = _PendingGroupMessage(
            stored_at=time.time() if now is None else float(now),
            event=copy.deepcopy(event),
            text=normalized,
            nickname=str(nickname or "").strip(),
        )
        self._trim()

    def resolve(
        self,
        event: dict[str, Any],
        text: str,
        *,
        nickname: str = "",
        addressed_to_bot: bool,
        now: float | None = None,
    ) -> GroupReplyFocus | None:
        key = _group_member_key(event)
        if not key or not addressed_to_bot:
            return None

        actor_id = str(event.get("user_id") or "")
        display_name = str(nickname or "").strip() or "当前群友"
        current_focus = _current_text_without_bot_mention(event, text, self.bot_qq)
        pending = self._pending.pop(key, None)

        if current_focus:
            return GroupReplyFocus(
                actor_id=actor_id,
                nickname=display_name,
                trigger_text=str(text or "").strip(),
                focus_text=current_focus,
                source="current_message",
                analysis_event=event,
            )

        current_time = time.time() if now is None else float(now)
        if pending is not None and current_time - pending.stored_at <= self.ttl_seconds:
            return GroupReplyFocus(
                actor_id=actor_id,
                nickname=display_name or pending.nickname,
                trigger_text=str(text or "").strip(),
                focus_text=pending.text,
                source="previous_same_sender",
                analysis_event=_merge_previous_event(pending.event, event),
            )

        return GroupReplyFocus(
            actor_id=actor_id,
            nickname=display_name,
            trigger_text=str(text or "").strip(),
            focus_text="",
            source="bare_mention",
            analysis_event=event,
        )

    def _trim(self) -> None:
        if len(self._pending) > 256:
            oldest = min(self._pending, key=lambda key: self._pending[key].stored_at)
            self._pending.pop(oldest, None)
        if len(self._active) > 256:
            earliest = min(self._active, key=lambda key: self._active[key].expires_at)
            self._active.pop(earliest, None)


def _group_member_key(event: dict[str, Any]) -> str:
    if event.get("message_type") != "group":
        return ""
    group_id = event.get("group_id")
    user_id = event.get("user_id")
    if group_id is None or user_id is None:
        return ""
    return f"group:{group_id}:user:{user_id}"


def _current_text_without_bot_mention(
    event: dict[str, Any],
    fallback_text: str,
    bot_qq: int,
) -> str:
    message = event.get("message")
    if not isinstance(message, list):
        return str(fallback_text or "").replace("@群友", "", 1).strip()
    remaining = []
    removed_bot_mention = False
    for segment in message:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type") or "").lower()
        data = segment.get("data") or {}
        if (
            segment_type == "at"
            and str(data.get("qq") or "") == str(bot_qq)
            and not removed_bot_mention
        ):
            removed_bot_mention = True
            continue
        remaining.append(segment)
    return _segments_to_text(remaining).strip()


def _merge_previous_event(
    previous_event: dict[str, Any],
    current_event: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(current_event)
    previous_segments = [
        dict(segment)
        for segment in _message_to_segments(previous_event.get("message"))
        if str(segment.get("type") or "").lower() != "at"
    ]
    merged["message"] = previous_segments + _message_to_segments(current_event.get("message"))
    return merged


def _message_to_segments(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, list):
        return [dict(segment) for segment in message if isinstance(segment, dict)]
    if message is None:
        return []
    return [{"type": "text", "data": {"text": str(message)}}]


def _segments_to_text(segments: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for segment in segments:
        segment_type = str(segment.get("type") or "").lower()
        data = segment.get("data") or {}
        if segment_type == "text":
            parts.append(str(data.get("text") or ""))
        elif segment_type == "at":
            parts.append("@群友")
        elif segment_type == "face":
            face_id = data.get("id") or data.get("face_id")
            parts.append(f"[QQ表情:{face_id}]" if face_id else "[QQ表情]")
        elif segment_type in {"mface", "marketface"}:
            summary = data.get("summary") or data.get("text") or data.get("name")
            parts.append(f"[动画表情:{summary}]" if summary else "[动画表情]")
        elif segment_type == "image":
            summary = data.get("summary") or data.get("file") or data.get("url")
            parts.append(f"[表情包/图片:{summary}]" if summary else "[表情包/图片]")
        elif segment_type == "video":
            summary = data.get("summary") or data.get("title") or data.get("file")
            parts.append(f"[视频:{summary}]" if summary else "[视频]")
        elif segment_type == "file":
            summary = data.get("name") or data.get("file_name") or data.get("file")
            parts.append(f"[文件:{summary}]" if summary else "[文件]")
        elif segment_type in {"json", "xml", "share"}:
            summary = data.get("title") or data.get("prompt") or data.get("desc")
            url = data.get("url")
            combined = " ".join(str(item).strip() for item in (summary, url) if item)
            parts.append(f"[分享:{combined}]" if combined else "[分享]")
        elif segment_type == "record":
            parts.append("[语音]")
    return "".join(parts)


def _is_only_generic_mentions(text: str) -> bool:
    compact = "".join(str(text or "").split())
    while compact.startswith("@群友"):
        compact = compact[len("@群友") :]
    return not compact


def _looks_like_direct_continuation(
    event: dict[str, Any],
    text: str,
    bot_qq: int,
) -> bool:
    """Conservatively decide whether a message continues the user's bot dialogue."""
    message = event.get("message")
    segments = message if isinstance(message, list) else []
    has_reply = any(
        isinstance(segment, dict)
        and str(segment.get("type") or "").lower() == "reply"
        for segment in segments
    )
    mentions_other = any(
        isinstance(segment, dict)
        and str(segment.get("type") or "").lower() == "at"
        and str((segment.get("data") or {}).get("qq") or "")
        not in {"", str(bot_qq)}
        for segment in segments
    )
    if mentions_other and not has_reply:
        return False

    normalized = str(text or "").replace("@群友", "").strip()
    compact = "".join(normalized.split()).lower()
    if has_reply:
        return True
    if not compact:
        return any(
            isinstance(segment, dict)
            and str(segment.get("type") or "").lower()
            in {"image", "mface", "marketface", "record", "video", "file"}
            for segment in segments
        )

    direct_cues = (
        "你", "亚托莉", "atri", "那", "所以", "然后", "还有", "对了",
        "但是", "为什么", "怎么", "什么", "真的吗", "你呢", "可以吗",
        "行吗", "谢谢", "好吧", "嗯", "对", "不是",
    )
    return (
        any(cue in compact for cue in direct_cues)
        or compact.endswith(("?", "？", "!", "！"))
        or len(compact) >= 12
    )
