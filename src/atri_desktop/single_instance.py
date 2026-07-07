from __future__ import annotations

import atexit
import ctypes
import msvcrt
import os

from atri_qq_bot.runtime.paths import DATA_DIR


PID_FILE = DATA_DIR / "runtime" / "desktop_pet.pid"
LOCK_FILE = DATA_DIR / "runtime" / "desktop_pet.lock"
MUTEX_NAME = "Local\\AtriQQDesktopPet"
ERROR_ALREADY_EXISTS = 183
_lock_handle = None
_mutex_handle = None


def acquire_single_instance() -> bool:
    if os.name == "nt":
        if not _acquire_windows_mutex():
            return False
    elif not _acquire_file_lock():
        return False

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(release_single_instance)
    return True


def release_single_instance() -> None:
    global _lock_handle, _mutex_handle
    try:
        if _read_pid() == os.getpid():
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    if _lock_handle is not None:
        try:
            _lock_handle.seek(0)
            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            _lock_handle.close()
        except Exception:
            pass
        _lock_handle = None

    if _mutex_handle is not None:
        try:
            ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        except Exception:
            pass
        try:
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _acquire_windows_mutex() -> bool:
    global _mutex_handle

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if not handle:
        return False
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def _acquire_file_lock() -> bool:
    global _lock_handle

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_FILE.open("a+b")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return False
    _lock_handle = handle
    return True
