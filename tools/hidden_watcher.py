from __future__ import annotations

import os
import time
from pathlib import Path

import hidden_launcher


PROJECT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "qq-watcher.log"
PID_FILE = LOG_DIR / "qq-watcher.pid"
LOCK_FILE = LOG_DIR / "qq-watcher.lock"
_WATCHER_MUTEX_HANDLE: int | None = None


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.open("a", encoding="utf-8").write(
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    )


def process_exists(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    result = hidden_launcher.run_hidden(["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    return str(pid) in result.stdout


def existing_watcher_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="ascii", errors="ignore").strip())
    except ValueError:
        return False
    return process_exists(pid)


def acquire_lock() -> object | None:
    if os.name == "nt":
        import ctypes

        global _WATCHER_MUTEX_HANDLE
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "AtriQQHiddenWatcher")
        if not handle:
            return object()
        if kernel32.GetLastError() == 183:
            kernel32.CloseHandle(handle)
            return None
        _WATCHER_MUTEX_HANDLE = handle
        return handle
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOCK_FILE.open("a+", encoding="utf-8")


def start_launcher() -> None:
    pythonw = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    python = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    python_exe = pythonw if pythonw.exists() else python
    if not python_exe.exists():
        log("Python executable not found; cannot start launcher.")
        return
    hidden_launcher.popen_hidden(
        [str(python_exe), str(Path(__file__).with_name("hidden_launcher.py"))],
        cwd=PROJECT_DIR,
    )


def main() -> int:
    lock_handle = acquire_lock()
    if lock_handle is None:
        return 0
    if existing_watcher_running():
        return 0
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    log("QQ watcher started.")

    armed = True
    while True:
        time.sleep(1)
        qq_running = hidden_launcher.process_running("QQ.exe")
        if not qq_running:
            armed = True
            continue
        if armed and not hidden_launcher.bot_connected():
            log("QQ detected. Starting Atri stack.")
            start_launcher()
            armed = False
            time.sleep(25)
            continue
        if hidden_launcher.bot_connected():
            armed = False


if __name__ == "__main__":
    raise SystemExit(main())
