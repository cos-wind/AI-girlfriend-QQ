from __future__ import annotations

import csv
import ctypes
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
NAPCAT_DIR = Path(
    r"D:\Tools\NapCat\OneKey\NapCat.44498.Shell\versions\9.9.26-44498\resources\app\napcat"
)
QQ_EXE = Path(r"C:\Program Files\Tencent\QQNT\QQ.exe")
QQ_UIN = "3380609082"
BOT_PORT = 8765
OLLAMA_PORT = 11434
WEBUI_STATUS_URL = "http://127.0.0.1:8787/api/status"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "hidden-launcher.log"
_LAUNCHER_MUTEX_HANDLE: int | None = None


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    LOG_FILE.open("a", encoding="utf-8").write(line)


def acquire_single_instance_mutex(name: str) -> bool:
    if os.name != "nt":
        return True
    global _LAUNCHER_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    already_exists = kernel32.GetLastError() == 183
    if already_exists:
        kernel32.CloseHandle(handle)
        return False
    _LAUNCHER_MUTEX_HANDLE = handle
    return True


def startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return info


def popen_hidden(
    args: list[str] | tuple[str, ...],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    return subprocess.Popen(
        [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        startupinfo=startupinfo(),
    )


def run_hidden(args: list[str] | tuple[str, ...]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(arg) for arg in args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        startupinfo=startupinfo(),
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def status_payload() -> dict[str, object]:
    try:
        with urllib.request.urlopen(WEBUI_STATUS_URL, timeout=1.2) as response:
            import json

            return json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def bot_connected() -> bool:
    status = status_payload()
    return bool(status.get("napcat"))


def process_rows() -> list[dict[str, str]]:
    result = run_hidden(["tasklist.exe", "/FO", "CSV", "/NH"])
    if result.returncode != 0:
        return []
    rows: list[dict[str, str]] = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 2:
            continue
        rows.append({"name": row[0], "pid": row[1]})
    return rows


def pids_by_name(name: str) -> list[int]:
    wanted = name.lower()
    pids: list[int] = []
    for row in process_rows():
        if row["name"].lower() == wanted:
            try:
                pids.append(int(row["pid"]))
            except ValueError:
                pass
    return pids


def process_running(name: str) -> bool:
    return bool(pids_by_name(name))


def taskkill(image_name: str) -> None:
    run_hidden(["taskkill.exe", "/IM", image_name, "/F"])


def show_qq_window(timeout_seconds: int = 35) -> bool:
    user32 = ctypes.windll.user32
    handles: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect_window(hwnd: int, _lparam: int) -> bool:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in qq_pids:
            return True
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        visible = bool(user32.IsWindowVisible(hwnd))
        if visible or class_name.value.startswith("Chrome_WidgetWin"):
            handles.append(hwnd)
        return True

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        qq_pids = set(pids_by_name("QQ.exe"))
        if not qq_pids:
            time.sleep(0.35)
            continue
        handles.clear()
        user32.EnumWindows(enum_proc_type(collect_window), 0)
        if handles:
            hwnd = handles[0]
            user32.ShowWindowAsync(hwnd, 5)
            time.sleep(0.15)
            user32.ShowWindowAsync(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            log(f"QQ window restored: handle={hwnd}.")
            return True
        time.sleep(0.35)
    log(f"QQ window was not found within {timeout_seconds} seconds.")
    return False


def start_ollama_if_needed() -> None:
    if port_open(OLLAMA_PORT):
        log(f"Ollama already listening on {OLLAMA_PORT}.")
        return

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
    ]
    found = next((path for path in candidates if path.exists()), None)
    if found is None:
        which = shutil.which("ollama.exe")
        found = Path(which) if which else None
    if not found or not found.exists():
        log("Ollama executable not found; skipping local model server.")
        return
    log("Starting Ollama in background.")
    popen_hidden([str(found), "serve"])
    time.sleep(1.5)


def start_atri_if_needed() -> None:
    if port_open(BOT_PORT):
        log(f"Atri service already listening on {BOT_PORT}.")
        return

    pythonw = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    python = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    python_exe = pythonw if pythonw.exists() else python
    if not python_exe.exists():
        log("Python venv not found. Run start-atri.bat once to repair dependencies.")
        return

    log("Starting Atri service in background.")
    popen_hidden([str(python_exe), "-m", "atri_qq_bot"], cwd=PROJECT_DIR)
    for _ in range(30):
        time.sleep(0.5)
        if port_open(BOT_PORT):
            log("Atri service is ready.")
            return
    log("Atri service did not report ready within timeout.")


def required_napcat_files() -> tuple[Path, Path, Path, Path, Path] | None:
    launcher = NAPCAT_DIR / "NapCatWinBootMain.exe"
    hook = NAPCAT_DIR / "NapCatWinBootHook.dll"
    napcat_main = NAPCAT_DIR / "napcat.mjs"
    load_path = NAPCAT_DIR / "loadNapCat.js"
    patch_package = NAPCAT_DIR / "qqnt.json"
    for path in (launcher, hook, napcat_main, patch_package, QQ_EXE):
        if not path.exists():
            log(f"Required launcher file not found: {path}")
            return None
    return launcher, hook, napcat_main, load_path, patch_package


def wait_for_connection(seconds: int) -> bool:
    for _ in range(seconds):
        time.sleep(1)
        if bot_connected():
            log("NapCat connected to Atri.")
            return True
    return False


def launch_napcat() -> bool:
    required = required_napcat_files()
    if required is None:
        return False
    launcher, hook, napcat_main, load_path, patch_package = required

    napcat_uri = "file:///" + str(napcat_main).replace("\\", "/").replace(" ", "%20")
    load_path.write_text(f'(async () => {{await import("{napcat_uri}")}})()\n', encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "NAPCAT_PATCH_PACKAGE": str(patch_package),
            "NAPCAT_LOAD_PATH": str(load_path),
            "NAPCAT_INJECT_PATH": str(hook),
            "NAPCAT_LAUNCHER_PATH": str(launcher),
            "NAPCAT_MAIN_PATH": str(napcat_main),
            "NAPCAT_QUICK_ACCOUNT": QQ_UIN,
        }
    )
    log(f"Starting NapCat QQ directly for {QQ_UIN}.")
    popen_hidden([str(launcher), str(QQ_EXE), str(hook), "-q", QQ_UIN], cwd=NAPCAT_DIR, env=env)
    show_qq_window(timeout_seconds=45)
    if wait_for_connection(30):
        return True
    if process_running("NapCatWinBootMain.exe"):
        log("NapCat started, waiting for OneBot connection.")
    else:
        log("NapCat failed to stay running.")
    return False


def launch_napcat_for_existing_qq() -> bool:
    required = required_napcat_files()
    if required is None:
        return False
    launcher, hook, napcat_main, load_path, patch_package = required

    napcat_uri = "file:///" + str(napcat_main).replace("\\", "/").replace(" ", "%20")
    load_path.write_text(f'(async () => {{await import("{napcat_uri}")}})()\n', encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "NAPCAT_PATCH_PACKAGE": str(patch_package),
            "NAPCAT_LOAD_PATH": str(load_path),
            "NAPCAT_INJECT_PATH": str(hook),
            "NAPCAT_LAUNCHER_PATH": str(launcher),
            "NAPCAT_MAIN_PATH": str(napcat_main),
            "NAPCAT_QUICK_ACCOUNT": QQ_UIN,
        }
    )
    log(f"Starting NapCat against existing QQ for {QQ_UIN}.")
    popen_hidden([str(launcher), str(QQ_EXE), str(hook), "-q", QQ_UIN], cwd=NAPCAT_DIR, env=env)
    show_qq_window(timeout_seconds=25)
    if wait_for_connection(25):
        return True
    if process_running("NapCatWinBootMain.exe"):
        log("NapCat started, waiting for OneBot connection.")
    else:
        log("NapCat failed to stay running.")
    return False


def start_napcat_if_needed() -> None:
    if bot_connected():
        log("NapCat is already connected to Atri.")
        show_qq_window(timeout_seconds=8)
        return

    if process_running("QQ.exe"):
        log("QQ is already running without OneBot connection; switching to NapCat QQ.")
        taskkill("QQ.exe")
        taskkill("NapCatWinBootMain.exe")
        time.sleep(1.2)
        launch_napcat()
        return

    if process_running("NapCatWinBootMain.exe"):
        log("NapCat boot process is already running.")
        show_qq_window(timeout_seconds=12)
        if wait_for_connection(12):
            return
        log("NapCat boot looks stale; restarting QQ/NapCat once.")

    log("Closing stale QQ/NapCat processes before direct NapCat launch.")
    taskkill("QQ.exe")
    taskkill("NapCatWinBootMain.exe")
    time.sleep(1.2)
    launch_napcat()


def main() -> int:
    if not acquire_single_instance_mutex("AtriQQHiddenLauncher"):
        return 0
    log("Hidden QQ launcher invoked.")
    start_ollama_if_needed()
    start_atri_if_needed()
    start_napcat_if_needed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
