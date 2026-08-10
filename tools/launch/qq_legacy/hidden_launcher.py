from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_QQ_EXE = Path(r"C:\Program Files\Tencent\QQNT\QQ.exe")
DEFAULT_NAPCAT_SEARCH_ROOTS = (
    Path(r"D:\Tools\NapCat\OneKey"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "NapCat",
)
NAPCAT_REQUIRED_FILES = (
    "NapCatWinBootMain.exe",
    "NapCatWinBootHook.dll",
    "napcat.mjs",
    "qqnt.json",
)
BOT_PORT = 8765
OLLAMA_PORT = 11434
VOICE_PORT = 8790
MUSIC_BRIDGE_PORT = 8793
GPT_SOVITS_PORT = 9880
DEFAULT_OLLAMA_MODELS = Path.home() / ".ollama" / "models"
DEFAULT_VOICE_ASCII_MODELS = Path(r"D:\AtriModels")
WEBUI_STATUS_URL = "http://127.0.0.1:8787/api/status"
VOICE_HEALTH_URL = f"http://127.0.0.1:{VOICE_PORT}/health"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "hidden-launcher.log"
NAPCAT_STATE_FILE = PROJECT_DIR / "data" / "runtime" / "napcat-state.json"
NAPCAT_QR_MAX_AGE_SECONDS = 300
NAPCAT_WEBUI_PORT = 6099
DEFAULT_QQ_PROFILE_DIR = PROJECT_DIR / "data" / "runtime" / "qq-profile"
_LAUNCHER_MUTEX_HANDLE: int | None = None
PROJECT_ROOT_TEXT = str(PROJECT_DIR).lower()
PROJECT_PYTHONW = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
PROJECT_PYTHON = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
NAPCAT_LAUNCHER_CACHE = (
    PROJECT_DIR
    / "data"
    / "runtime"
    / "napcat-launcher"
    / "NapCatWinBootMain.exe"
)
PE_WINDOWS_GUI_SUBSYSTEM = 2
PE_WINDOWS_CONSOLE_SUBSYSTEM = 3
NAPCAT_CONSOLE_LOGGING_SWITCH = "--enable-logging".encode("utf-16-le")


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    LOG_FILE.open("a", encoding="utf-8").write(line)


def publish_napcat_state(
    state: str,
    *,
    detail: str = "",
    qrcode: Path | None = None,
) -> None:
    payload = {
        "state": state,
        "detail": detail,
        "updated_at": time.time(),
        "qrcode": str(qrcode) if qrcode else "",
    }
    try:
        NAPCAT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = NAPCAT_STATE_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, NAPCAT_STATE_FILE)
    except OSError as exc:
        log(f"Could not publish NapCat runtime state: {exc}")


def fresh_napcat_qrcode(
    napcat_dir: Path,
    *,
    since: float | None = None,
) -> Path | None:
    qrcode = napcat_dir / "cache" / "qrcode.png"
    try:
        minimum_mtime = (
            since
            if since is not None
            else time.time() - NAPCAT_QR_MAX_AGE_SECONDS
        )
        return qrcode if qrcode.stat().st_mtime >= minimum_mtime else None
    except OSError:
        return None


def show_login_qrcode(qrcode: Path) -> None:
    try:
        os.startfile(qrcode)  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        log(f"Could not open NapCat login QR code {qrcode}: {exc}")


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


def bot_qq_uin() -> str:
    value = (
        project_env_value("BOT_QQ")
        or os.environ.get("BOT_QQ", "")
    ).strip()
    return value if value.isdigit() else ""


def qq_executable() -> Path:
    configured = (
        project_env_value("QQ_EXE")
        or os.environ.get("QQ_EXE", "")
    ).strip()
    return Path(configured).expanduser() if configured else DEFAULT_QQ_EXE


def qq_profile_dir() -> Path:
    """返回项目 QQ 专用的 Chromium/Electron 配置目录。

    QQ 的聊天数据库仍由 QQ 按账号写入 ``Documents\Tencent Files\<QQ号>``；
    这里隔离的是两个不同版本 QQ 最容易互相污染的界面缓存、WebStorage、
    Cookie 和 Electron 配置。桌面 QQ 不应登录 BOT_QQ 对应账号。
    """
    configured = (
        project_env_value("QQ_PROFILE_DIR")
        or os.environ.get("QQ_PROFILE_DIR", "")
    ).strip()
    return Path(configured).expanduser() if configured else DEFAULT_QQ_PROFILE_DIR


def validate_qq_isolation(qq_exe: Path, profile_dir: Path) -> tuple[Path, Path]:
    """校验专用 QQ 与配置目录，失败时禁止回退到桌面 QQ。"""
    resolved_exe = qq_exe.resolve(strict=False)
    resolved_profile = profile_dir.resolve(strict=False)
    desktop_profile = (
        Path(os.environ.get("APPDATA", "")) / "QQ"
    ).resolve(strict=False)
    if not resolved_exe.is_file():
        raise FileNotFoundError(f"Project QQ executable not found: {resolved_exe}")
    if not resolved_profile.is_absolute():
        raise ValueError("QQ_PROFILE_DIR must be an absolute path.")
    if os.path.normcase(str(resolved_profile)) == os.path.normcase(
        str(desktop_profile)
    ):
        raise ValueError("QQ_PROFILE_DIR must not use the desktop QQ profile.")
    return resolved_exe, resolved_profile


def isolated_qq_arguments(
    qq_exe: Path,
    qq_uin: str,
    profile_dir: Path,
) -> list[str]:
    """构造已验证可用的专用 QQ 启动参数。"""
    return [
        str(qq_exe),
        "--enable-logging",
        "-q",
        qq_uin,
        f"--user-data-dir={profile_dir}",
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _windows_environment_block(env: dict[str, str]) -> ctypes.Array:
    """生成 CreateProcessW 需要的双 NUL 结尾 Unicode 环境块。"""
    entries = [f"{key}={value}" for key, value in sorted(env.items())]
    return ctypes.create_unicode_buffer("\0".join(entries) + "\0\0")


def launch_isolated_napcat_qq(
    *,
    qq_exe: Path,
    hook: Path,
    qq_uin: str,
    profile_dir: Path,
    cwd: Path,
    env: dict[str, str],
) -> int:
    """挂起启动专用 QQ，注入 NapCat 后再恢复主线程。

    官方引导器不会透传 ``--user-data-dir``。因此这里复用其核心流程：
    CreateProcessW(CREATE_SUSPENDED) -> 远程 LoadLibraryW(hook) -> ResumeThread。
    任一步失败都会终止新进程，绝不退回桌面 QQ 或共享配置启动。
    """
    if os.name != "nt":
        raise OSError("NapCat QQ isolation is only supported on Windows.")
    qq_exe, profile_dir = validate_qq_isolation(qq_exe, profile_dir)
    if not hook.is_file():
        raise FileNotFoundError(f"NapCat hook not found: {hook}")
    profile_dir.mkdir(parents=True, exist_ok=True)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.VirtualAllocEx.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.VirtualAllocEx.restype = wintypes.LPVOID
    kernel32.WriteProcessMemory.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.LPCVOID,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.WriteProcessMemory.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
    kernel32.GetProcAddress.restype = wintypes.LPVOID
    kernel32.CreateRemoteThread.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CreateRemoteThread.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeThread.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeThread.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.VirtualFreeEx.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    kernel32.VirtualFreeEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    arguments = isolated_qq_arguments(qq_exe, qq_uin, profile_dir)
    command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
    environment_block = _windows_environment_block(env)
    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    process = _PROCESS_INFORMATION()
    create_suspended = 0x00000004
    create_unicode_environment = 0x00000400
    created = kernel32.CreateProcessW(
        str(qq_exe),
        command_line,
        None,
        None,
        False,
        create_suspended | create_unicode_environment,
        environment_block,
        str(cwd),
        ctypes.byref(startup),
        ctypes.byref(process),
    )
    if not created:
        raise ctypes.WinError(ctypes.get_last_error())

    remote_memory = None
    remote_thread = None
    resumed = False
    try:
        hook_payload = (str(hook.resolve()) + "\0").encode("utf-16-le")
        hook_buffer = ctypes.create_string_buffer(hook_payload)
        remote_memory = kernel32.VirtualAllocEx(
            process.hProcess,
            None,
            len(hook_payload),
            0x3000,  # MEM_COMMIT | MEM_RESERVE
            0x04,  # PAGE_READWRITE
        )
        if not remote_memory:
            raise ctypes.WinError(ctypes.get_last_error())

        written = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(
            process.hProcess,
            remote_memory,
            ctypes.cast(hook_buffer, wintypes.LPCVOID),
            len(hook_payload),
            ctypes.byref(written),
        ) or written.value != len(hook_payload):
            raise ctypes.WinError(ctypes.get_last_error())

        kernel_module = kernel32.GetModuleHandleW("kernel32.dll")
        load_library = kernel32.GetProcAddress(kernel_module, b"LoadLibraryW")
        if not load_library:
            raise ctypes.WinError(ctypes.get_last_error())
        remote_thread = kernel32.CreateRemoteThread(
            process.hProcess,
            None,
            0,
            load_library,
            remote_memory,
            0,
            None,
        )
        if not remote_thread:
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel32.WaitForSingleObject(remote_thread, 15000) != 0:
            raise TimeoutError("Timed out while injecting the NapCat hook.")
        module_handle = wintypes.DWORD()
        if not kernel32.GetExitCodeThread(remote_thread, ctypes.byref(module_handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        if module_handle.value == 0:
            raise OSError("NapCat hook injection returned a null module handle.")
        if kernel32.ResumeThread(process.hThread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = True
        return int(process.dwProcessId)
    finally:
        if not resumed:
            kernel32.TerminateProcess(process.hProcess, 1)
        if remote_thread:
            kernel32.CloseHandle(remote_thread)
        if remote_memory:
            kernel32.VirtualFreeEx(process.hProcess, remote_memory, 0, 0x8000)
        kernel32.CloseHandle(process.hThread)
        kernel32.CloseHandle(process.hProcess)


def find_napcat_dir(
    search_roots: tuple[Path, ...] | None = None,
) -> Path | None:
    configured = (
        project_env_value("NAPCAT_DIR")
        or os.environ.get("NAPCAT_DIR", "")
    ).strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if _is_napcat_runtime(configured_path):
            return configured_path.resolve()

    candidates: list[Path] = []
    for root in search_roots or DEFAULT_NAPCAT_SEARCH_ROOTS:
        root = Path(root).expanduser()
        if _is_napcat_runtime(root):
            candidates.append(root)
        if not root.is_dir():
            continue
        candidates.extend(
            path
            for path in root.glob(
                "NapCat*.Shell/versions/*/resources/app/napcat"
            )
            if _is_napcat_runtime(path)
        )
        candidates.extend(
            path
            for path in root.glob("versions/*/resources/app/napcat")
            if _is_napcat_runtime(path)
        )
    if not candidates:
        return None
    return max(
        {path.resolve() for path in candidates},
        key=lambda path: (path.stat().st_mtime_ns, str(path).casefold()),
    )


def _is_napcat_runtime(path: Path) -> bool:
    return path.is_dir() and all(
        (path / name).is_file() for name in NAPCAT_REQUIRED_FILES
    )


def prepare_napcat_no_console_launcher(source: Path) -> Path:
    source_bytes = bytearray(source.read_bytes())
    if len(source_bytes) < 0x40 or source_bytes[:2] != b"MZ":
        raise ValueError("NapCat launcher is not a valid Windows executable.")

    pe_offset = int.from_bytes(source_bytes[0x3C:0x40], "little")
    optional_header = pe_offset + 24
    if (
        pe_offset <= 0
        or optional_header + 70 > len(source_bytes)
        or source_bytes[pe_offset : pe_offset + 4] != b"PE\0\0"
    ):
        raise ValueError("NapCat launcher has an invalid PE header.")

    magic = int.from_bytes(
        source_bytes[optional_header : optional_header + 2],
        "little",
    )
    if magic not in {0x10B, 0x20B}:
        raise ValueError("NapCat launcher uses an unsupported PE format.")

    subsystem_offset = optional_header + 68
    subsystem = int.from_bytes(
        source_bytes[subsystem_offset : subsystem_offset + 2],
        "little",
    )
    if subsystem == PE_WINDOWS_CONSOLE_SUBSYSTEM:
        source_bytes[subsystem_offset : subsystem_offset + 2] = (
            PE_WINDOWS_GUI_SUBSYSTEM.to_bytes(2, "little")
        )
    elif subsystem != PE_WINDOWS_GUI_SUBSYSTEM:
        raise ValueError(f"Unsupported NapCat PE subsystem: {subsystem}.")

    logging_switch_offset = source_bytes.find(NAPCAT_CONSOLE_LOGGING_SWITCH)
    if logging_switch_offset >= 0:
        source_bytes[logging_switch_offset : logging_switch_offset + 2] = b"\0\0"

    patched_bytes = bytes(source_bytes)
    try:
        if (
            NAPCAT_LAUNCHER_CACHE.is_file()
            and NAPCAT_LAUNCHER_CACHE.read_bytes() == patched_bytes
        ):
            return NAPCAT_LAUNCHER_CACHE
    except OSError:
        pass

    NAPCAT_LAUNCHER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = NAPCAT_LAUNCHER_CACHE.with_suffix(".tmp")
    temporary.write_bytes(patched_bytes)
    os.replace(temporary, NAPCAT_LAUNCHER_CACHE)
    return NAPCAT_LAUNCHER_CACHE


def ollama_models_path() -> Path:
    configured = project_env_value("OLLAMA_MODELS") or os.environ.get("OLLAMA_MODELS", "")
    configured = configured.strip()
    return Path(configured) if configured else DEFAULT_OLLAMA_MODELS


def voice_models_root() -> Path:
    configured = (
        project_env_value("ATRI_MODELS_ROOT")
        or os.environ.get("ATRI_MODELS_ROOT", "")
    ).strip()
    if configured:
        return Path(configured).expanduser()
    if DEFAULT_VOICE_ASCII_MODELS.is_dir():
        return DEFAULT_VOICE_ASCII_MODELS
    return ollama_models_path() / "AI_ATRI"


def voice_runtime_candidates() -> tuple[Path, ...]:
    models_path = ollama_models_path()
    return (
        PROJECT_DIR / "data" / "runtime" / "voice-runtime",
        models_path / "manifests" / "atri-runtime",
        models_path.parent / "Speech" / "atri-runtime",
    )


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
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(start_script),
        ],
        cwd=PROJECT_DIR,
    )


def start_voice_if_needed(*, wait_for_ready: bool = True) -> None:
    if not voice_enabled():
        return
    already_listening = port_open(VOICE_PORT)
    if already_listening and not wait_for_ready:
        log(f"Voice service already listening on {VOICE_PORT}.")
        return
    if already_listening and voice_ready():
        log(f"Voice service already ready on {VOICE_PORT}.")
        return
    runtime_candidates = voice_runtime_candidates()
    runtime_root = next(
        (
            candidate
            for candidate in runtime_candidates
            if (candidate / ".venv" / "Scripts" / "python.exe").exists()
        ),
        runtime_candidates[0],
    )
    pythonw = runtime_root / ".venv" / "Scripts" / "pythonw.exe"
    python = runtime_root / ".venv" / "Scripts" / "python.exe"
    executable = pythonw if pythonw.exists() else python
    if not executable.exists():
        log("Voice feature is enabled but its isolated runtime is not installed.")
        return
    env = os.environ.copy()
    compat_path = str(PROJECT_DIR / "tools" / "voice" / "compat")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (compat_path, existing_pythonpath) if part
    )
    model_root = voice_models_root()
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
    if not wait_for_ready:
        log("Voice service startup requested; model warmup continues in background.")
        return
    for _ in range(60):
        time.sleep(0.5)
        if voice_ready():
            log("Voice service is ready.")
            return
    log("Voice service did not report ready within timeout.")


def start_music_bridge_if_needed() -> None:
    if port_open(MUSIC_BRIDGE_PORT):
        log(f"AI_music bridge already listening on {MUSIC_BRIDGE_PORT}.")
        return
    configured_root = os.getenv("ATRI_MUSIC_PROJECT_DIR", "").strip()
    music_root = (
        Path(configured_root).expanduser().resolve()
        if configured_root
        else PROJECT_DIR.parent / "多模态AI" / "AI_music"
    )
    bridge = music_root / "bridge" / "server.py"
    executable = PROJECT_PYTHONW if PROJECT_PYTHONW.exists() else PROJECT_PYTHON
    if not bridge.exists() or not executable.exists():
        log(f"AI_music bridge unavailable under {music_root}.")
        return
    env = os.environ.copy()
    env.setdefault("ATRI_BRIDGE_HOST", "127.0.0.1")
    env.setdefault("ATRI_BRIDGE_PORT", str(MUSIC_BRIDGE_PORT))
    env.setdefault("ATRI_VOICE_SERVICE_URL", f"http://127.0.0.1:{VOICE_PORT}")
    log("Starting AI_music bridge in background.")
    popen_hidden([str(executable), str(bridge)], cwd=music_root, env=env)


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
    if status:
        return bool(status.get("napcat")) and status.get("napcat_state") not in {
            "event_stale",
            "probe_stale",
            "qq_offline",
            "recovering",
            "login_required",
        }
    # WebUI 尚未就绪时才使用本地 TCP 作为启动阶段的兼容判断。
    return onebot_connection_established()


def onebot_connection_established() -> bool:
    try:
        from atri_qq_bot.runtime.control import has_established_port
    except ImportError:
        return False
    return has_established_port(BOT_PORT)


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


def process_executable_path(pid: int) -> Path | None:
    """使用 Windows 原生 API 获取进程路径，不创建终端窗口。"""
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            ctypes.byref(size),
        ):
            return None
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def project_qq_pids() -> list[int]:
    target = os.path.normcase(os.path.abspath(str(qq_executable())))
    matches: list[int] = []
    for pid in pids_by_name("QQ.exe"):
        path = process_executable_path(pid)
        if path is None:
            continue
        if os.path.normcase(os.path.abspath(str(path))) == target:
            matches.append(pid)
    return matches


def taskkill_pid(pid: int) -> None:
    run_hidden(["taskkill.exe", "/PID", str(pid), "/F"])


def taskkill_process_tree(pid: int) -> None:
    """仅终止指定 NapCat 引导进程及其 QQ 子进程，不触碰用户独立 QQ。"""
    run_hidden(["taskkill.exe", "/PID", str(pid), "/T", "/F"])


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
        qq_pids = set(project_qq_pids())
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


def start_ollama_if_needed(*, wait_for_ready: bool = True) -> None:
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
    if not wait_for_ready:
        log("Ollama startup requested; readiness check continues in the service.")
        return
    for _ in range(30):
        time.sleep(0.5)
        if port_open(OLLAMA_PORT):
            log("Ollama is ready.")
            return
    log("Ollama did not report ready within timeout.")


def start_atri_if_needed(*, wait_for_ready: bool = True) -> None:
    if port_open(BOT_PORT):
        if bot_connected():
            log(f"Atri service already listening on {BOT_PORT} and NapCat is connected.")
        else:
            log(
                f"Atri service already listening on {BOT_PORT}; "
                "keeping it alive while NapCat connects."
            )
        return

    python_exe = PROJECT_PYTHONW if PROJECT_PYTHONW.exists() else PROJECT_PYTHON
    if not python_exe.exists():
        log(r"Python venv not found. Run tools\launch\atri\start-atri.bat once to repair dependencies.")
        return

    log("Starting Atri service in background.")
    popen_hidden([str(python_exe), "-m", "atri_qq_bot"], cwd=PROJECT_DIR)
    if not wait_for_ready:
        log("Atri startup requested; NapCat may start in parallel.")
        return
    for _ in range(75):
        time.sleep(0.2)
        if port_open(BOT_PORT):
            log("Atri service is ready.")
            return
    log("Atri service did not report ready within timeout.")


def required_napcat_files() -> tuple[Path, Path, Path, Path, Path] | None:
    napcat_dir = find_napcat_dir()
    if napcat_dir is None:
        log(
            "NapCat runtime was not found. Set NAPCAT_DIR in .env "
            "or install NapCat under a supported location."
        )
        return None
    launcher = napcat_dir / "NapCatWinBootMain.exe"
    hook = napcat_dir / "NapCatWinBootHook.dll"
    napcat_main = napcat_dir / "napcat.mjs"
    load_path = napcat_dir / "loadNapCat.js"
    patch_package = napcat_dir / "qqnt.json"
    qq_exe = qq_executable()
    for path in (launcher, hook, napcat_main, patch_package, qq_exe):
        if not path.exists():
            log(f"Required launcher file not found: {path}")
            return None
    return launcher, hook, napcat_main, load_path, patch_package


def wait_for_connection(
    seconds: int,
    *,
    keep_qq_hidden: bool = False,
) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if keep_qq_hidden:
            hide_qq_windows()
        time.sleep(0.1 if keep_qq_hidden else 0.25)
        if bot_connected():
            if keep_qq_hidden:
                hide_qq_windows()
            log("NapCat connected to Atri.")
            return True
    return False


def hide_qq_windows() -> bool:
    if os.name != "nt":
        return False
    qq_pids = set(project_qq_pids())
    if not qq_pids:
        return False

    user32 = ctypes.windll.user32
    hidden = False
    enum_proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    def hide_window(hwnd: int, _lparam: int) -> bool:
        nonlocal hidden
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in qq_pids and user32.IsWindowVisible(hwnd):
            user32.ShowWindowAsync(hwnd, 0)
            hidden = True
        return True

    user32.EnumWindows(enum_proc_type(hide_window), 0)
    return hidden


def wait_for_process_exit(
    image_names: tuple[str, ...],
    timeout_seconds: float = 3.0,
) -> bool:
    wanted = {name.casefold() for name in image_names}
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        running = {
            row["name"].casefold()
            for row in process_rows()
            if row["name"].casefold() in wanted
        }
        if not running:
            return True
        time.sleep(0.1)
    return False


def wait_for_project_qq_exit(timeout_seconds: float = 5.0) -> bool:
    """等待专用兼容版 QQ 退出，不检查也不影响桌面 QQ。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not project_qq_pids():
            return True
        time.sleep(0.1)
    return False


def launch_napcat(
    required: tuple[Path, Path, Path, Path, Path] | None = None,
) -> bool:
    required = required or required_napcat_files()
    if required is None:
        return False
    launcher, hook, napcat_main, load_path, patch_package = required
    qq_uin = bot_qq_uin()
    if not qq_uin:
        log("BOT_QQ is missing or invalid in .env.")
        return False
    qq_exe = qq_executable()
    profile_dir = qq_profile_dir()
    napcat_dir = launcher.parent
    launch_started_at = time.time()

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
            "NAPCAT_QUICK_ACCOUNT": qq_uin,
        }
    )
    log(
        f"Starting isolated NapCat QQ for {qq_uin}. "
        f"qq={qq_exe}; profile={profile_dir}"
    )
    publish_napcat_state("starting", detail="正在启动专用 NapCat/QQ")
    try:
        pid = launch_isolated_napcat_qq(
            qq_exe=qq_exe,
            hook=hook,
            qq_uin=qq_uin,
            profile_dir=profile_dir,
            cwd=napcat_dir,
            env=env,
        )
    except (OSError, ValueError, TimeoutError) as exc:
        detail = f"专用 QQ 启动失败：{exc}"
        log(detail)
        publish_napcat_state("failed", detail=detail)
        return False
    log(f"Isolated NapCat QQ process started: pid={pid}")
    if wait_for_connection(20, keep_qq_hidden=True):
        return True
    qrcode = fresh_napcat_qrcode(napcat_dir, since=launch_started_at)
    if qrcode is not None:
        detail = "QQ 登录已失效，需要扫码登录"
        log(f"{detail}. QR code: {qrcode}")
        publish_napcat_state("login_required", detail=detail, qrcode=qrcode)
        show_qq_window(timeout_seconds=20)
        show_login_qrcode(qrcode)
        return False
    log("NapCat quick login is delayed; showing QQ for possible manual login.")
    show_qq_window(timeout_seconds=20)
    if wait_for_connection(55):
        return True
    if port_open(NAPCAT_WEBUI_PORT) or process_running("NapCatWinBootMain.exe"):
        log("NapCat started, waiting for OneBot connection.")
        publish_napcat_state("connecting", detail="NapCat 已启动，正在等待 OneBot 连接")
    else:
        log("NapCat failed to stay running.")
        publish_napcat_state("failed", detail="NapCat 启动后意外退出")
    return False


def launch_napcat_for_existing_qq() -> bool:
    """兼容旧调用名，但始终走隔离启动，禁止注入已打开的桌面 QQ。"""
    log("Legacy existing-QQ launch requested; forcing isolated project QQ startup.")
    return launch_napcat()


def start_napcat_if_needed() -> None:
    if port_open(BOT_PORT) and bot_connected():
        log("NapCat is already connected to Atri.")
        return

    required = required_napcat_files()
    if required is None:
        log("NapCat startup aborted before changing any running QQ process.")
        return
    if not bot_qq_uin():
        log("BOT_QQ is missing or invalid; existing QQ processes were left unchanged.")
        return

    running_names = {row["name"].casefold() for row in process_rows()}
    # 桌面 QQ 与项目 QQ 可以同时运行；这里只判断配置中指定的兼容版 QQ。
    qq_running = bool(project_qq_pids())
    napcat_boot_running = "napcatwinbootmain.exe" in running_names
    # 隔离启动模式直接向专用 QQ 注入 Hook，不会留下引导器常驻进程。
    napcat_runtime_running = napcat_boot_running or port_open(NAPCAT_WEBUI_PORT)

    if qq_running and napcat_runtime_running:
        if status_payload().get("napcat_state") in {
            "event_stale",
            "probe_stale",
            "qq_offline",
        }:
            log("NapCat event stream is stale; restarting only the isolated QQ instance.")
            publish_napcat_state(
                "recovering",
                detail="检测到 NapCat 事件流假在线，正在重启专用 NapCat/QQ 进程",
            )
            for pid in project_qq_pids():
                taskkill_pid(pid)
            wait_for_project_qq_exit()
            if napcat_boot_running:
                taskkill("NapCatWinBootMain.exe")
                wait_for_process_exit(("NapCatWinBootMain.exe",))
            launch_napcat(required)
            return
        qrcode = fresh_napcat_qrcode(required[0].parent)
        if qrcode is not None:
            detail = "QQ 登录已失效，需要扫码登录"
            log("QQ and NapCat are already waiting for login; preserving the current session.")
            publish_napcat_state("login_required", detail=detail, qrcode=qrcode)
        else:
            detail = "QQ 与 NapCat 已启动，正在等待 OneBot 连接"
            log("QQ and NapCat are already starting; preserving the current session.")
            publish_napcat_state("connecting", detail=detail)
        show_qq_window(timeout_seconds=5)
        return

    if qq_running:
        log("Project QQ is running without NapCat; stopping only that compatible QQ instance.")
        for pid in project_qq_pids():
            taskkill_pid(pid)
        wait_for_project_qq_exit()
        launch_napcat(required)
        return

    if napcat_runtime_running:
        log("NapCat boot process is already running.")
        show_qq_window(timeout_seconds=12)
        if wait_for_connection(45):
            return
        log("NapCat boot looks stale; restarting QQ/NapCat once.")

        if napcat_boot_running:
            taskkill("NapCatWinBootMain.exe")
            wait_for_process_exit(("NapCatWinBootMain.exe",))
    else:
        log("No stale QQ/NapCat process found; starting directly.")
    launch_napcat(required)


def main() -> int:
    if not acquire_single_instance_mutex("AtriQQHiddenLauncher"):
        log("Hidden QQ launcher is already running; ignoring duplicate request.")
        return 0
    log("Hidden QQ launcher invoked.")

    # Bring text chat online first. Model and voice services are optional and
    # must not delay or destabilize the OneBot connection.
    start_atri_if_needed(wait_for_ready=False)
    start_napcat_if_needed()

    start_gpt_sovits_if_needed()
    start_ollama_if_needed(wait_for_ready=False)
    start_voice_if_needed(wait_for_ready=False)
    start_music_bridge_if_needed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
