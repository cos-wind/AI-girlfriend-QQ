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
        # 调用方超时放弃、但 acquire 随后才成功的次数。持续为 0 才说明没在漏锁。
        self._late_releases = 0

    async def _acquire_guarded(self, timeout_seconds: float) -> None:
        """带超时地获取进程内锁，且**绝不取消 `acquire()` 本身**。

        ⚠️ 不要退回 `asyncio.wait_for(self._lock.acquire(), ...)`。
        `wait_for` 超时会取消正在等待的 `acquire()`；而 `asyncio.Lock`（3.11 的纯
        Python 实现）在「已被 `release()` 唤醒、但协程还没恢复去置 `_locked=True`」
        这个窗口里被取消时，可能把它从等待队列摘掉却没唤醒下一位 —— 锁就进入
        **`_locked=False` 但队列里永远躺着一个等待者**的毒化状态。表现为：

            /health 里 inference_resources.busy=false、queued=1 卡住不动，
            端口在监听、/health 秒回，**所有合成请求永远不返回**（GPU 0%）。

        这里改成 `shield`：超时只放弃*等待*，不打断 acquire；万一 acquire 事后
        成功，由 `_release_late` 立刻归还，锁状态始终自洽。
        """
        acquirer = asyncio.ensure_future(self._lock.acquire())
        try:
            await asyncio.wait_for(
                asyncio.shield(acquirer),
                timeout=max(0.1, float(timeout_seconds)),
            )
        except asyncio.TimeoutError as exc:
            asyncio.ensure_future(self._release_late(acquirer))
            raise InferenceResourceBusyError("语音推理队列繁忙") from exc

    async def _release_late(self, acquirer: asyncio.Future) -> None:
        """收尾一次「调用方已放弃、但之后才拿到」的 acquire，避免永久占锁。"""
        try:
            await asyncio.shield(acquirer)
        except BaseException:
            return
        self._late_releases += 1
        try:
            self._lock.release()
        except RuntimeError:  # pragma: no cover - 只为不让后台任务炸掉
            pass

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
                await self._acquire_guarded(float(timeout_seconds))
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
            "late_releases": self._late_releases,
        }
