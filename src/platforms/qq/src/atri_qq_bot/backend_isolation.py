"""Coordinate reply-chain transitions across desktop and launcher processes.

QQ clients/profiles remain owned by their respective launchers. This guard never
injects, stops a process, changes an account, or selects a route automatically.
"""
from contextlib import contextmanager
import os
from pathlib import Path

from atrium_runtime import user_root


@contextmanager
def transition(directory: Path | None = None, *, name: str = 'qq-backend.lock'):
    directory = directory if directory is not None else user_root() / 'data/runtime'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('另一条 QQ 接入正在启停，请稍后重试；当前登录保留。') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


@contextmanager
def napcat_transition(directory: Path | None = None):
    # Separate from reply-chain transitions: core delegates NapCat to a worker,
    # while the service card calls it directly. Both must share this lock.
    with transition(directory, name='napcat-start.lock'):
        yield


def ensure_legacy_available(directory: Path | None = None):
    from .snowluma_trial import active
    try:
        running = active(directory)
    except (OSError, ValueError, KeyError):
        raise ValueError('无法确认 SnowLuma 接入状态，未启动第二条回复链路。') from None
    if running:
        raise ValueError('SnowLuma 文字接入仍在运行，请先停止试用；QQ 登录保留。')


@contextmanager
def legacy_transition():
    # Keep the lock until the launcher has established its core listener, not
    # merely until Popen returns. A simultaneous SnowLuma start cannot slip in.
    with transition():
        ensure_legacy_available()
        yield
