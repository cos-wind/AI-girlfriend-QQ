"""One owning thread per adapter, with bounded waits and no implicit replay."""
from __future__ import annotations

from concurrent.futures import CancelledError, Future, TimeoutError
from dataclasses import dataclass, field
import logging
import math
from queue import Queue
from threading import Lock, Thread
import time
from typing import Callable
import uuid


@dataclass
class _Task:
    action: str
    payload: dict
    future: Future = field(default_factory=Future)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float | None = None
    detached: bool = False


class OwnedWorker:
    """Preserve UIA/Playwright affinity without waiting forever in callers.

    Expired queued work is cancelled. Expired running work keeps ownership of
    the adapter and blocks new work until completion; it is never replayed.
    A fatal adapter exit poisons this worker instead of replacing its thread.
    """

    def __init__(self, factory: Callable, *, wait_timeout: float = 300):
        self._wait_timeout = self._timeout(wait_timeout)
        self._factory = factory
        self._queue: Queue = Queue()
        self._lock = Lock()
        self._thread = None
        self._closed = False
        self._stopped = False
        self._failed = False
        self._pending: dict[str, _Task] = {}
        self._active: _Task | None = None
        self._last_task: dict = {}

    @staticmethod
    def _timeout(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("工作台等待时间必须为有限正数")
        return value

    def snapshot(self):
        """Passive, payload-free status; never queue a call to the adapter."""
        with self._lock:
            active = self._active
            state = ("failed" if self._failed else
                     "closed" if self._stopped else
                     "closing" if self._closed else
                     "stalled" if active and active.detached else
                     "running" if active else
                     "idle" if self._thread else "not_started")
            return {"state": state, "task_id": active.id if active else "",
                    "action": active.action if active else "",
                    "elapsed_seconds": round(time.monotonic() - active.started, 1) if active else 0,
                    "pending": sum(task.started is None for task in self._pending.values()),
                    "last_task": dict(self._last_task)}

    def call(self, action: str, payload: dict, *, timeout: float | None = None):
        wait = self._wait_timeout if timeout is None else self._timeout(timeout)
        task = _Task(action, payload)
        with self._lock:
            if self._closed:
                raise ValueError("工作台正在关闭")
            if self._failed:
                raise ValueError("平台工作线程已退出，请重新打开软件后核对平台状态")
            if self._active and self._active.detached:
                raise ValueError("此前平台操作仍在执行，请等待完成；涉及发送时请先在平台核对，勿重复发送")
            if len(self._pending) >= 32:
                raise ValueError("平台待处理操作过多，请等待已有操作完成")
            if self._thread is None:
                self._thread = Thread(target=self._run, daemon=True, name="atri-social")
                self._thread.start()
            self._pending[task.id] = task
            self._queue.put(task)
        try:
            return task.future.result(timeout=wait)
        except TimeoutError:
            with self._lock:
                # Adapter-raised TimeoutError and completion at the deadline
                # are real results, not evidence that work is still running.
                if task.future.done():
                    if task.future.cancelled():
                        raise ValueError("工作台正在关闭，排队操作已取消，尚未执行") from None
                    return task.future.result()
                if task.future.cancel():
                    self._pending.pop(task.id, None)
                    raise ValueError("平台操作排队超时，尚未执行，已取消") from None
                task.detached = True
            raise ValueError("平台操作等待超时，但仍在执行；请等待完成，涉及发送时先在平台核对，勿重复发送") from None
        except CancelledError:
            raise ValueError("工作台正在关闭，排队操作已取消，尚未执行") from None

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for key, task in list(self._pending.items()):
                if task.started is None:
                    task.future.cancel()
                    del self._pending[key]
            if self._thread is not None:
                self._queue.put(None)
            else:
                self._stopped = True

    def _run(self):
        adapter = None
        try:
            while True:
                task = self._queue.get()
                if task is None:
                    return
                with self._lock:
                    if task.future.cancelled():
                        continue
                    task.future.set_running_or_notify_cancel()
                    task.started = time.monotonic()
                    self._active = task
                try:
                    if adapter is None:
                        adapter = self._factory()
                    result = adapter.execute(task.action, task.payload)
                except Exception as exc:
                    self._finish(task, error=exc)
                else:
                    self._finish(task, result=result)
        except BaseException as exc:
            # A SystemExit in an SDK must not strand waiting callers or cause
            # a replacement adapter to overlap an uncertain operation.
            logging.getLogger(__name__).error("Platform worker exited (%s)", type(exc).__name__)
            with self._lock:
                self._failed = True
                for task in self._pending.values():
                    if not task.future.done():
                        task.future.set_exception(ValueError("平台工作线程异常退出，操作结果未确认，请先在平台核对"))
                self._pending.clear()
                self._active = None
        finally:
            if adapter is not None and callable(getattr(adapter, "close", None)):
                try:
                    adapter.close()
                except BaseException as exc:
                    logging.getLogger(__name__).warning("Platform adapter close failed (%s)", type(exc).__name__)
            with self._lock:
                self._stopped = True

    def _finish(self, task, *, result=None, error=None):
        with self._lock:
            self._last_task = {"id": task.id, "action": task.action,
                               "outcome": "failed" if error is not None else "completed",
                               "detached": task.detached}
            self._pending.pop(task.id, None)
            self._active = None
            if error is not None:
                task.future.set_exception(error)
            else:
                task.future.set_result(result)
