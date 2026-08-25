from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from atri_qq_bot.runtime.inference_lock import (
    InferencePriority,
    InferenceResourceBusyError,
    inference_resource_lease,
)


class InferenceResourceManager:
    """Serializes GPU-heavy work without coupling providers to one runtime."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_engine = ""
        self._waiters = 0
        self._last_engine = ""
        self._last_started_at = ""

    @asynccontextmanager
    async def lease(
        self,
        engine: str,
        *,
        timeout_seconds: float | None = None,
        priority: int | InferencePriority = InferencePriority.USER_MEDIA,
    ) -> AsyncIterator[None]:
        started_at = asyncio.get_running_loop().time()
        self._waiters += 1
        try:
            if timeout_seconds is None:
                await self._lock.acquire()
            else:
                try:
                    await asyncio.wait_for(
                        self._lock.acquire(),
                        timeout=max(0.1, float(timeout_seconds)),
                    )
                except asyncio.TimeoutError as exc:
                    raise InferenceResourceBusyError(
                        "语音推理队列繁忙"
                    ) from exc
        finally:
            self._waiters -= 1
        self._active_engine = str(engine or "unknown")
        self._last_engine = self._active_engine
        self._last_started_at = datetime.now(timezone.utc).isoformat()
        try:
            remaining_timeout = timeout_seconds
            if timeout_seconds is not None:
                remaining_timeout = max(
                    0.1,
                    float(timeout_seconds)
                    - (asyncio.get_running_loop().time() - started_at),
                )
            async with inference_resource_lease(
                self._active_engine,
                timeout_seconds=remaining_timeout,
                priority=priority,
            ):
                yield
        finally:
            self._active_engine = ""
            self._lock.release()

    def status(self) -> dict[str, object]:
        return {
            "busy": self._lock.locked(),
            "active_engine": self._active_engine,
            "queued": self._waiters,
            "last_engine": self._last_engine,
            "last_started_at": self._last_started_at,
        }
