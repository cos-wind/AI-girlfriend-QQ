from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CallInviteRequest:
    topic: str = ""


@dataclass
class VoiceCallSession:
    token: str
    conversation_id: str
    user_id: int
    topic: str
    created_at: float
    expires_at: float
    active_until: float
    turns: int = 0
    closed: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "topic": self.topic,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "active_until": self.active_until,
            "turns": self.turns,
            "closed": self.closed,
        }


class VoiceCallStore:
    def __init__(self) -> None:
        self._sessions: dict[str, VoiceCallSession] = {}
        self._lock = threading.RLock()

    def create(
        self,
        conversation_id: str,
        topic: str,
        expiry_minutes: int,
        max_minutes: int,
        now: float | None = None,
    ) -> VoiceCallSession:
        created_at = now or time.time()
        user_id = _private_user_id(conversation_id)
        token = secrets.token_urlsafe(24)
        session = VoiceCallSession(
            token=token,
            conversation_id=conversation_id,
            user_id=user_id,
            topic=str(topic or "").strip()[:120],
            created_at=created_at,
            expires_at=created_at + max(1, int(expiry_minutes)) * 60,
            active_until=created_at + max(1, int(max_minutes)) * 60,
        )
        with self._lock:
            self._prune(created_at)
            self._sessions[token] = session
        return session

    def get(self, token: str, now: float | None = None) -> VoiceCallSession | None:
        current = now or time.time()
        with self._lock:
            self._prune(current)
            session = self._sessions.get(str(token or ""))
            if session is None or session.closed:
                return None
            if session.turns == 0 and current > session.expires_at:
                session.closed = True
                return None
            if current > session.active_until:
                session.closed = True
                return None
            return session

    def mark_turn(self, token: str) -> None:
        with self._lock:
            session = self._sessions.get(token)
            if session is not None and not session.closed:
                session.turns += 1

    def close(self, token: str) -> None:
        with self._lock:
            session = self._sessions.get(token)
            if session is not None:
                session.closed = True

    def _prune(self, now: float) -> None:
        expired = [
            token
            for token, session in self._sessions.items()
            if session.closed or now > max(session.expires_at, session.active_until)
        ]
        for token in expired:
            self._sessions.pop(token, None)


def _private_user_id(conversation_id: str) -> int:
    prefix = "private:"
    if not conversation_id.startswith(prefix):
        raise ValueError("通话邀请只支持私聊")
    try:
        return int(conversation_id[len(prefix) :])
    except ValueError as exc:
        raise ValueError("无法识别通话用户") from exc
