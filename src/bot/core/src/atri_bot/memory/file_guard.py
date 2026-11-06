"""Serialize JSON replacement across the chat process and the memory editor."""
from contextlib import contextmanager
from pathlib import Path
import os
import threading
import time

_registry_lock = threading.Lock()
_locks = {}
_local = threading.local()


@contextmanager
def memory_write_guard(path):
    key = os.path.normcase(str(Path(path).resolve()))
    with _registry_lock:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        active = getattr(_local, 'active', set())
        if key in active:
            yield
            return
        target = Path(key + '.lock')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a+b') as stream:
            if not target.stat().st_size:
                stream.write(b'0')
                stream.flush()
            deadline = time.monotonic() + 5
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('记忆文件正在由另一进程保存')
                    time.sleep(.01)
            _local.active = active | {key}
            try:
                yield
            finally:
                _local.active = active
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
