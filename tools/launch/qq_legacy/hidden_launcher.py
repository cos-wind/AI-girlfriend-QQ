from __future__ import annotations

import csv
import ctypes
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
NAPCAT_DIR = Path(r"C:\Path\To\NapCat")  # TODO: set your NapCat path
QQ_EXE = Path(r"C:\Program Files\Tencent\QQNT\QQ.exe")
QQ_UIN = "YOUR_BOT_QQ"
BOT_PORT = 8765
OLLAMA_PORT = 11434
VOICE_PORT = 8790
GPT_SOVITS_PORT = 9880
DEFAULT_OLLAMA_MODELS = Path(r"C:\Path\To\Local\Models")  # TODO: set your models path
DEFAULT_ATRI_MODELS = DEFAULT_OLLAMA_MODELS / "AI_ATRI"
VOICE_ASCII_MODELS = Path(r"C:\Path\To\AtriModels")  # TODO: set your AtriModels path
VOICE_RUNTIME_CANDIDATES = (
    PROJECT_DIR / "data" / "runtime" / "voice-runtime",
    DEFAULT_OLLAMA_MODELS / "manifests" / "atri-runtime",
    DEFAULT_OLLAMA_MODELS.parent / "Speech" / "atri-runtime",
)
WEBUI_STATUS_URL = "http://127.0.0.1:8787/api/status"
VOICE_HEALTH_URL = f"http://127.0.0.1:{VOICE_PORT}/health"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "hidden-launcher.log"
_LAUNCHER_MUTEX_HANDLE: int | None = None
PROJECT_ROOT_TEXT = str(PROJECT_DIR).lower()
PROJECT_PYTHONW = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
PROJECT_PYTHON = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"


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


def project_env_value(name: str) -> str:
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{name}="
    try:
        lines = env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped.split("=", 1)[1].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1].strip()
        return value
    return ""


def ollama_models_path() -> Path:
    configured = project_env_value("OLLAMA_MODELS") or os.environ.get("OLLAMA_MODELS", "")
    configured = configured.strip()
    return Path(configured) if configured else DEFAULT_OLLAMA_MODELS


def ollama_process_env() -> dict[str, str]:
    env = os.environ.copy()
    models_path = ollama_models_path()
    try:
        models_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"Could not create Ollama models directory {models_path}: {exc}")
    env["OLLAMA_MODELS"] = str(models_path)
    return env


def voice_enabled() -> bool:
    enabled_values = {"1", "true", "yes", "on"}
    return any(
        project_env_value(name).strip().lower() in enabled_values
        for name in ("VOICE_ASR_ENABLED", "VOICE_TTS_ENABLED")
    )


def voice_tts_enabled() -> bool:
    return project_env_value("VOICE_TTS_ENABLED").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def start_gpt_sovits_if_needed() -> None:
    if not voice_tts_enabled() or port_open(GPT_SOVITS_PORT):
        return
    start_script = PROJECT_DIR / "tools" / "voice" / "start-gpt-sovits.ps1"
    marker = PROJECT_DIR / "data" / "runtime" / "gpt-sovits" / ".dependencies-ready"
    if not start_script.exists() or not marker.exists():
        log("Voice synthesis is enabled but GPT-SoVITS is not fully installed.")
        return
    log("Starting GPT-SoVITS in background.")
    popen_hidden(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(start_script),
        ],
        cwd=PROJECT_DIR,
    )


def start_voice_if_needed() -> None:
    if not voice_enabled():
        return
    already_listening = port_open(VOICE_PORT)
    if already_listening and voice_ready():
        log(f"Voice service already ready on {VOICE_PORT}.")
        return
    runtime_root = next(
        (
            candidate
            for candidate in VOICE_RUNTIME_CANDIDATES
            if (candidate / ".venv" / "Scripts" / "python.exe").exists()
        ),
        VOICE_RUNTIME_CANDIDATES[0],
    )
    pythonw = runtime_root / ".venv" / "Scripts" / "pythonw.exe"
    python = runtime_root / ".venv" / "Scripts" / "python.exe"
    executable = pythonw if pythonw.exists() else python
    if not executable.exists():
        log("Voice feature is enabled but its isolated runtime is not installed.")
        return
    env = os.environ.copy()
    model_root = VOICE_ASCII_MODELS if VOICE_ASCII_MODELS.exists() else DEFAULT_ATRI_MODELS
    env["MODELSCOPE_CACHE"] = str(model_root / "voice" / "modelscope")
    env["HF_HOME"] = str(model_root / "voice" / "huggingface")
    env.setdefault("ATRI_ASR_PROVIDER", "sensevoice")
    local_sensevoice = (
        Path(env["MODELSCOPE_CACHE"])
        / "models"
        / "iic--SenseVoiceSmall"
        / "snapshots"
        / "master"
    )
    env.setdefault(
        "ATRI_ASR_MODEL",
        str(local_sensevoice) if (local_sensevoice / "model.pt").exists() else "iic/SenseVoiceSmall",
    )
    env.setdefault("ATRI_ASR_DEVICE", "cpu")
    if not already_listening:
        log("Starting isolated voice service in background.")
        popen_hidden(
            [str(executable), "-m", "atri_voice_service"],
            cwd=PROJECT_DIR,
            env=env,
        )
    else:
        log("Voice service is listening; waiting for model warmup.")
    for _ in range(60):
        time.sleep(0.5)
        if voice_ready():
            log("Voice service is ready.")
            return
    log("Voice service did not report ready within timeout.")


def voice_ready() -> bool:
    try:
        with urllib.request.urlopen(VOICE_HEALTH_URL, timeout=1.2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("ok")) and bool(payload.get("ready"))
    except (OSError, ValueError):
        return False


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
    return bool(status.get("napcat")) or onebot_connection_established()


def onebot_connection_established() -> bool:
    result = run_hidden(["netstat.exe", "-ano", "-p", "TCP"])
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != "TCP" or parts[3].upper() != "ESTABLISHED":
            continue
        local_port = endpoint_port(parts[1])
        remote_port = endpoint_port(parts[2])
        if local_port == BOT_PORT or remote_port == BOT_PORT:
            return True
    return False


def listening_pids(port: int) -> list[int]:
    result = run_hidden(["netstat.exe", "-ano", "-p", "TCP"])
    if result.returncode != 0:
        return []
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if endpoint_port(parts[1]) != port:
            continue
        try:
            pids.add(int(parts[4]))
        except ValueError:
            pass
    return sorted(pids)


def endpoint_port(endpoint: str) -> int | None:
    try:
        return int(endpoint.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


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


def process_name_by_pid(pid: int) -> str | None:
    for row in process_rows():
        try:
            row_pid = int(row["pid"])
        except ValueError:
            continue
        if row_pid == pid:
            return row["name"]
    return None


def taskkill_pid(pid: int) -> None:
    run_hidden(["taskkill.exe", "/PID", str(pid), "/F"])


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
    env = ollama_process_env()
    log(f"Starting Ollama in background. models={env['OLLAMA_MODELS']}")
    popen_hidden([str(found), "serve"], env=env)
    for _ in range(30):
        time.sleep(0.5)
        if port_open(OLLAMA_PORT):
            log("Ollama is ready.")
            return
    log("Ollama did not report ready within timeout.")


def start_atri_if_needed() -> None:
    if port_open(BOT_PORT) and bot_connected():
        log(f"Atri service already listening on {BOT_PORT} and NapCat is connected.")
        return

    if port_open(BOT_PORT):
        log(f"Port {BOT_PORT} is listening but NapCat is not connected; clearing stale listener before restart.")
        for pid in listening_pids(BOT_PORT):
            name = process_name_by_pid(pid) or ""
            if name.lower().startswith("python"):
                log(f"Stopping stale Atri listener PID {pid}.")
                taskkill_pid(pid)
            else:
                log(f"Port {BOT_PORT} is owned by non-python PID {pid}; restart skipped.")
                return
        for _ in range(20):
            time.sleep(0.25)
            if not port_open(BOT_PORT):
                break
        if port_open(BOT_PORT):
            log(f"Port {BOT_PORT} is still busy; Atri service restart skipped.")
            return

    python_exe = PROJECT_PYTHONW if PROJECT_PYTHONW.exists() else PROJECT_PYTHON
    if not python_exe.exists():
        log(r"Python venv not found. Run tools\launch\atri\start-atri.bat once to repair dependencies.")
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
    if wait_for_connection(75):
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
    if wait_for_connection(60):
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
        if wait_for_connection(45):
            return
        log("NapCat boot looks stale; restarting QQ/NapCat once.")

    log("Closing stale QQ/NapCat processes before direct NapCat launch.")
    taskkill("QQ.exe")
    taskkill("NapCatWinBootMain.exe")
    time.sleep(1.2)
    launch_napcat()


def main() -> int:
    if not acquire_single_instance_mutex("AtriQQHiddenLauncher"):
        log("Hidden QQ launcher is already running; ignoring duplicate request.")
        return 0
    log("Hidden QQ launcher invoked.")
    start_ollama_if_needed()
    start_gpt_sovits_if_needed()
    start_voice_if_needed()
    start_atri_if_needed()
    start_napcat_if_needed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
