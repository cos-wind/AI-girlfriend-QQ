from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from .paths import DATA_DIR


INFERENCE_LOCK_PATH = DATA_DIR / "runtime" / "gpu-inference.lock"


class InferenceResourceBusyError(TimeoutError):
    pass


class _InterprocessFileLock:
    def __init__(self, path: Path = INFERENCE_LOCK_PATH) -> None:
        self.path = Path(path)
        self._stream: BinaryIO | None = None

    def acquire(self, timeout_seconds: float | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()

        deadline = (
            None
            if timeout_seconds is None
            else time.monotonic() + max(0.0, float(timeout_seconds))
        )
        while True:
            try:
                stream.seek(0)
                _try_lock(stream)
                self._stream = stream
                return
            except OSError as exc:
                if deadline is not None and time.monotonic() >= deadline:
                    stream.close()
                    raise InferenceResourceBusyError(
                        "GPU 推理资源正被其他任务占用"
                    ) from exc
                time.sleep(0.1)

    def release(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.seek(0)
            _unlock(stream)
        finally:
            stream.close()


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
) -> AsyncIterator[None]:
    del engine
    lock = _InterprocessFileLock()
    await asyncio.to_thread(lock.acquire, timeout_seconds)
    try:
        yield
    finally:
        await asyncio.to_thread(lock.release)
