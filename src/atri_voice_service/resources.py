from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from atri_qq_bot.runtime.inference_lock import inference_resource_lease


class InferenceResourceManager:
    """Serializes GPU-heavy work without coupling providers to one runtime."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_engine = ""
        self._waiters = 0
        self._last_engine = ""
        self._last_started_at = ""

    @asynccontextmanager
    async def lease(self, engine: str) -> AsyncIterator[None]:
        self._waiters += 1
        try:
            await self._lock.acquire()
        finally:
            self._waiters -= 1
        self._active_engine = str(engine or "unknown")
        self._last_engine = self._active_engine
        self._last_started_at = datetime.now(timezone.utc).isoformat()
        try:
            async with inference_resource_lease(self._active_engine):
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
