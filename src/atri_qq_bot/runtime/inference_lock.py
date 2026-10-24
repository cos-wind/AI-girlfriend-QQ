"""跨进程推理资源锁。

本机模型、embedding、视觉和语音服务可能共享同一块内存/GPU。文件锁比进程内
asyncio.Lock 覆盖范围更大，可以协调不同 Python 进程，同时保留超时降级能力。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from enum import IntEnum
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Iterator
from uuid import uuid4

from .paths import DATA_DIR


INFERENCE_LOCK_PATH = DATA_DIR / "runtime" / "gpu-inference.lock"
INFERENCE_QUEUE_PATH = DATA_DIR / "runtime" / "gpu-inference-queue"
INFERENCE_OWNER_PATH = DATA_DIR / "runtime" / "gpu-inference.lock.owner.json"

# 没给截止时间时的兜底上限（秒）。
#
# Windows 的文件锁在**同一进程的不同句柄之间**同样互斥（不像 flock 那样按进程计），
# 所以只要有一个租约异常退出而没走到 `release()`，本进程后续的 `acquire()` 就会
# 永远拿不到锁 —— 而 `timeout_seconds=None` 的调用方（TTS 会话等）原本会无限空转，
# 表现为「端口在监听、/health 秒回、合成永不返回、GPU 0%」的假死。
# 这里给一个保守上限，把「永久死锁」降级成可重试的 InferenceResourceBusyError。
DEFAULT_ACQUIRE_TIMEOUT_SECONDS = 600.0


class InferencePriority(IntEnum):
    """单 GPU 上各类工作的调度优先级，数值越小越先执行。

    这里只决定“下一位是谁”，不会中断已经进入 GPU 的推理。长任务因此仍需
    在调用层设置截止时间；聊天会在当前片段结束后先于视觉和后台任务取得资源。
    """

    CHAT = 0
    USER_MEDIA = 20
    VISION = 30
    BACKGROUND = 80


class InferenceResourceBusyError(TimeoutError):
    pass


class _InferenceAcquireCancelled(Exception):
    """Internal signal used to stop a worker-thread lock acquisition."""


class _InterprocessFileLock:
    def __init__(
        self,
        path: Path | None = None,
        *,
        queue_path: Path | None = None,
        priority: int | InferencePriority = InferencePriority.BACKGROUND,
        owner_path: Path | None = None,
        owner: str = "",
    ) -> None:
        self.path = Path(path or INFERENCE_LOCK_PATH)
        self.queue_path = Path(queue_path or INFERENCE_QUEUE_PATH)
        self.priority = max(0, min(999, int(priority)))
        self.owner_path = Path(owner_path or INFERENCE_OWNER_PATH)
        self.owner = str(owner or "unknown")
        self.owner_token = uuid4().hex
        self._stream: BinaryIO | None = None
        self._ticket: Path | None = None

    @property
    def held(self) -> bool:
        return self._stream is not None

    def acquire(
        self,
        timeout_seconds: float | None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_path.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()

        effective_timeout = (
            DEFAULT_ACQUIRE_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = (
            None
            if effective_timeout is None
            else time.monotonic() + max(0.0, float(effective_timeout))
        )
        ticket = self.queue_path / (
            f"{self.priority:03d}-{time.time_ns():020d}-{os.getpid()}-"
            f"{uuid4().hex}.ticket"
        )
        ticket.touch(exist_ok=False)
        self._ticket = ticket
        last_error: OSError | None = None
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise _InferenceAcquireCancelled()
                if self._ticket_is_next(ticket):
                    try:
                        stream.seek(0)
                        _try_lock(stream)
                        if cancel_event is not None and cancel_event.is_set():
                            _unlock(stream)
                            raise _InferenceAcquireCancelled()
                        self._stream = stream
                        ticket.unlink(missing_ok=True)
                        self._ticket = None
                        self._publish_owner()
                        return
                    except OSError as exc:
                        last_error = exc
                if deadline is not None and time.monotonic() >= deadline:
                    raise InferenceResourceBusyError(
                        "GPU 推理资源正被其他任务占用"
                    ) from last_error
                time.sleep(0.05)
        except BaseException:
            ticket.unlink(missing_ok=True)
            self._ticket = None
            stream.close()
            raise

    def _publish_owner(self) -> None:
        payload = {
            "pid": os.getpid(),
            "owner": self.owner,
            "priority": self.priority,
            "acquired_at": time.time(),
            "token": self.owner_token,
        }
        try:
            self.owner_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.owner_path.with_name(
                f"{self.owner_path.name}.{self.owner_token}.tmp"
            )
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.owner_path)
        except OSError:
            # Diagnostics must never turn a valid GPU lease into a failed request.
            pass

    def _clear_owner(self) -> None:
        try:
            if not self.owner_path.is_file():
                return
            payload = json.loads(self.owner_path.read_text(encoding="utf-8"))
            if payload.get("token") == self.owner_token:
                self.owner_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass

    def _ticket_is_next(self, ticket: Path) -> bool:
        """清理崩溃进程留下的票据，并判断当前请求是否排在队首。"""

        stale_before = time.time() - 180.0
        pending: list[Path] = []
        for candidate in self.queue_path.glob("*.ticket"):
            try:
                if candidate.stat().st_mtime < stale_before:
                    candidate.unlink(missing_ok=True)
                    continue
            except OSError:
                continue
            pending.append(candidate)
        if not pending:
            return True
        return min(pending, key=lambda item: item.name).name == ticket.name

    def release(self) -> None:
        ticket = self._ticket
        self._ticket = None
        if ticket is not None:
            ticket.unlink(missing_ok=True)
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.seek(0)
            _unlock(stream)
        finally:
            stream.close()
            self._clear_owner()


def _try_lock(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@asynccontextmanager
async def inference_resource_lease(
    engine: str,
    *,
    timeout_seconds: float | None = None,
    priority: int | InferencePriority = InferencePriority.BACKGROUND,
) -> AsyncIterator[None]:
    # acquire 是阻塞的文件操作，放进线程避免阻塞 OneBot 的事件循环。
    cancel_event = threading.Event()
    lock = _InterprocessFileLock(
        priority=priority,
        owner=engine,
    )
    acquire_task = asyncio.create_task(
        asyncio.to_thread(lock.acquire, timeout_seconds, cancel_event)
    )
    try:
        # shield prevents task cancellation from abandoning the worker future.
        await asyncio.shield(acquire_task)
    except asyncio.CancelledError:
        # A cancelled coroutine must not leave its worker thread free to acquire
        # the lock after the caller has already exited the context manager.
        cancel_event.set()
        try:
            await acquire_task
        except (_InferenceAcquireCancelled, InferenceResourceBusyError):
            pass
        finally:
            if lock.held:
                await asyncio.to_thread(lock.release)
        raise
    try:
        yield
    finally:
        await asyncio.to_thread(lock.release)


@contextmanager
def inference_resource_lease_sync(
    engine: str,
    *,
    timeout_seconds: float | None = None,
    priority: int | InferencePriority = InferencePriority.BACKGROUND,
) -> Iterator[None]:
    """同步后台任务使用的同一资源租约。

    记忆摄取与向量检索运行在线程中，不能使用异步上下文管理器；它们必须
    与视觉/语音共享同一把跨进程锁，否则 Ollama 上线时会并发加载多个模型。
    """
    lock = _InterprocessFileLock(priority=priority, owner=engine)
    lock.acquire(timeout_seconds)
    try:
        yield
    finally:
        lock.release()
