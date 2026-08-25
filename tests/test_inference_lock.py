from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import atri_qq_bot.runtime.inference_lock as inference_lock
from atri_qq_bot.runtime.inference_lock import (
    InferencePriority,
    _InterprocessFileLock,
)


def test_cancelled_async_lease_cannot_reacquire_after_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _test_cancelled_async_lease_cannot_reacquire_after_cancellation(
            tmp_path,
            monkeypatch,
        )
    )


async def _test_cancelled_async_lease_cannot_reacquire_after_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "gpu.lock"
    queue_path = tmp_path / "queue"
    owner_path = tmp_path / "owner.json"
    monkeypatch.setattr(inference_lock, "INFERENCE_LOCK_PATH", lock_path)
    monkeypatch.setattr(inference_lock, "INFERENCE_QUEUE_PATH", queue_path)
    monkeypatch.setattr(inference_lock, "INFERENCE_OWNER_PATH", owner_path)

    ready_path = tmp_path / "holder.ready"
    holder_script = "\n".join(
        (
            "import sys, time",
            f"sys.path.insert(0, {str(Path.cwd() / 'src')!r})",
            "from pathlib import Path",
            "from atri_qq_bot.runtime.inference_lock import _InterprocessFileLock",
            f"lock = _InterprocessFileLock({str(lock_path)!r}, queue_path={str(queue_path)!r}, owner_path={str(owner_path)!r})",
            "lock.acquire(10.0)",
            f"Path({str(ready_path)!r}).touch()",
            "time.sleep(30)",
        )
    )
    holder_process = subprocess.Popen(
        [sys.executable, "-c", holder_script],
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not ready_path.exists():
            await asyncio.sleep(0.01)
        assert ready_path.exists()

        async def wait_for_lease() -> None:
            async with inference_lock.inference_resource_lease(
                "chat:test",
                timeout_seconds=5.0,
            ):
                raise AssertionError("cancelled waiter unexpectedly entered lease")

        task = asyncio.create_task(wait_for_lease())
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not list(queue_path.glob("*.ticket")):
            await asyncio.sleep(0.01)
        assert list(queue_path.glob("*.ticket"))

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        holder_process.terminate()
        holder_process.wait(timeout=5.0)
        await asyncio.sleep(0.1)

        probe = _InterprocessFileLock(
            lock_path,
            queue_path=queue_path,
            owner_path=owner_path,
        )
        probe.acquire(0.5)
        probe.release()
    finally:
        if holder_process.poll() is None:
            holder_process.terminate()
            holder_process.wait(timeout=5.0)


def test_cross_process_lock_selects_high_priority_waiter_first(tmp_path: Path) -> None:
    lock_path = tmp_path / "gpu.lock"
    queue_path = tmp_path / "queue"
    holder = _InterprocessFileLock(lock_path, queue_path=queue_path)
    holder.acquire(1.0)
    order: list[str] = []

    def wait(name: str, priority: InferencePriority) -> None:
        lock = _InterprocessFileLock(
            lock_path,
            queue_path=queue_path,
            priority=priority,
        )
        lock.acquire(2.0)
        try:
            order.append(name)
            time.sleep(0.02)
        finally:
            lock.release()

    low = threading.Thread(
        target=wait,
        args=("background", InferencePriority.BACKGROUND),
    )
    high = threading.Thread(
        target=wait,
        args=("chat", InferencePriority.CHAT),
    )
    low.start()
    high.start()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(list(queue_path.glob("*.ticket"))) < 2:
        time.sleep(0.01)
    holder.release()
    low.join(timeout=3.0)
    high.join(timeout=3.0)

    assert not low.is_alive()
    assert not high.is_alive()
    assert order == ["chat", "background"]
