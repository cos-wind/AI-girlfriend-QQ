from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from atri_runtime import user_root, resource_root, instance_suffix


PROJECT_DIR = user_root()
# 只是"最常见位置"的快速路径，不是唯一答案：系统盘可能不是 C，QQ 也可能被
# 装到任何目录。真正的定位见 qq_executable() 的多源探测。
DEFAULT_QQ_EXE = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tencent" / "QQNT" / "QQ.exe"
)
DEFAULT_NAPCAT_SEARCH_ROOTS = (
    PROJECT_DIR.parent / "NapCat",
    Path(os.environ.get("LOCALAPPDATA", "")) / "NapCat",
)
pass
NAPCAT_REQUIRED_FILES = (
    "NapCatWinBootMain.exe",
    "NapCatWinBootHook.dll",
    "napcat.mjs",
    "qqnt.json",
)
BOT_PORT = 8765
QZONE_BRIDGE_PORT = 5700
MAIBOT_PORT = 8001
OLLAMA_PORT = 11434
VOICE_PORT = 8790
MUSIC_BRIDGE_PORT = 8793
GPT_SOVITS_PORT = 9880
NAPCAT_CONNECTION_POLL_SECONDS = 0.75
OPTIONAL_SERVICES_WAIT_SECONDS = 30
OPTIONAL_SERVICES_STAGGER_SECONDS = 2.0
DEFAULT_OLLAMA_MODELS = Path.home() / ".ollama" / "models"
DEFAULT_VOICE_ASCII_MODELS = PROJECT_DIR / "models"
WEBUI_STATUS_URL = "http://127.0.0.1:8787/api/status"
VOICE_HEALTH_URL = f"http://127.0.0.1:{VOICE_PORT}/health"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "hidden-launcher.log"
# 主体进程（python -m atri_qq_bot）自己的 stdout/stderr 落盘处。
# 以前这里走 DEVNULL，主体崩在 import 阶段时一句报错都看不到。
ATRI_SERVICE_LOG = LOG_DIR / "atri-service.log"
ATRI_SERVICE_LOG_MAX_BYTES = 2 * 1024 * 1024
NAPCAT_STATE_FILE = PROJECT_DIR / "data" / "runtime" / "napcat-state.json"
# 快速登录账号覆盖：WebUI 切换账号时写这里，避免每次启动都用 BOT_QQ 自动登录旧号。
#   * 文件不存在          → 沿用 BOT_QQ（历史行为）
#   * off / manual / -    → 明确要求手动登录（不传 -q、不设 NAPCAT_QUICK_ACCOUNT）
#   * 纯数字              → 用这个号快速登录
NAPCAT_QUICK_ACCOUNT_FILE = PROJECT_DIR / "data" / "runtime" / "napcat-quick-account.txt"
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
) -> None:
    payload = {
        "state": state,
        "detail": detail,
        "updated_at": time.time(),
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


def acquire_single_instance_mutex(name: str) -> bool:
    if os.name != "nt":
        return True
    global _LAUNCHER_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.CreateMutexW(None, False, name + instance_suffix())
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


def popen_logged(
    args: list[str] | tuple[str, ...],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    log_path: Path,
) -> subprocess.Popen:
    """同 ``popen_hidden``，但把子进程输出追加到 ``log_path``。

    ⚠️ 为什么必须有这一个（2026-10-01 排障学到的）：主体崩在 import 阶段时
    （典型是 venv 缺 ``dotenv`` / ``httpx`` 这类包），``DEVNULL`` 会让失败
    **完全无声** —— launcher 只会报「did not report ready within timeout」，
    界面上还显示「启动命令已发出」，看着就像点了没反应。
    留一份子进程输出，下次直接 tail 就能看到真正的 ImportError。
    """
    try:
        handle = open(str(log_path), "ab")
    except OSError:
        return popen_hidden(args, cwd=cwd, env=env)
    return subprocess.Popen(
        [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=handle,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        startupinfo=startupinfo(),
    )


def start_launcher_mode_in_background(mode: str) -> bool:
    """Run a launcher slice in its own hidden process.

    Long-running recovery work (notably NapCat login detection) must not hold
    up the core launcher or delay the local ATRI service.
    """
    python_exe = PROJECT_PYTHONW if PROJECT_PYTHONW.exists() else PROJECT_PYTHON
    if not False and not python_exe.exists():
        log(f"Cannot start launcher mode {mode}: project Python was not found.")
        return False
    try:
        popen_hidden(
            ([str(python_exe), str(Path(__file__).resolve()), mode]),
            cwd=PROJECT_DIR,
        )
    except OSError as exc:
        log(f"Could not start launcher mode {mode}: {exc}")
        return False
    log(f"Launcher mode {mode} requested in background.")
    return True


def run_hidden(
    args: list[str] | tuple[str, ...],
    *,
    timeout_seconds: float = 10.0,
) -> subprocess.CompletedProcess:
    try:
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
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        log(f"Hidden command timed out after {timeout_seconds:.1f}s: {args[0] if args else 'unknown'}")
        return subprocess.CompletedProcess(args=args, returncode=124, stdout=output, stderr="")


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


QQ_EXE_FILE_NAME = "QQ.exe"
# QQ 的安装器允许自定义目录和盘符，所以下面只把官方默认布局当快速路径，
# 真正定位依靠注册表、运行中进程和常见盘符扫描，绝不把单一路径当唯一答案。
QQ_INSTALL_LAYOUTS = (
    Path("Tencent") / "QQNT" / "QQ.exe",
    Path("Tencent") / "QQ" / "Bin" / "QQ.exe",
)
QQ_UNINSTALL_DISPLAY_NAMES = ("qq", "qqnt")


def _as_qq_executable(raw: object) -> Path | None:
    """把配置或注册表里的各种写法收敛成一个确实存在的 QQ.exe。"""
    text = str(raw or "").strip().strip('"')
    if not text:
        return None
    # DisplayIcon 形如 "C:\...\QQ.exe,0"，InstallLocation 则是目录。
    if "," in text:
        text = text.split(",", 1)[0].strip().strip('"')
    try:
        path = Path(text).expanduser()
    except (OSError, ValueError):
        return None
    candidates = [path]
    if path.suffix.casefold() != ".exe":
        candidates.insert(0, path / QQ_EXE_FILE_NAME)
    for candidate in candidates:
        if candidate.name.casefold() != QQ_EXE_FILE_NAME.casefold():
            continue
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _qq_from_app_paths() -> Path | None:
    if os.name != "nt":
        return None
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_name in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe",
        ):
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    hit = _as_qq_executable(winreg.QueryValue(key, None))
            except OSError:
                continue
            if hit:
                return hit
    return None


def _qq_from_uninstall_entries() -> Path | None:
    """卸载登记项里的 DisplayIcon 是当前 QQ 安装器唯一稳定留下的路径线索。"""
    if os.name != "nt":
        return None
    import winreg

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, root in roots:
        try:
            with winreg.OpenKey(hive, root) as parent:
                subkey_count = winreg.QueryInfoKey(parent)[0]
                for index in range(subkey_count):
                    try:
                        with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as entry:
                            display = str(
                                winreg.QueryValueEx(entry, "DisplayName")[0] or ""
                            ).strip().casefold()
                            # 精确匹配，避免 QQ音乐 / QQ浏览器 / QQ输入法 误命中。
                            if display not in QQ_UNINSTALL_DISPLAY_NAMES:
                                continue
                            for value_name in ("DisplayIcon", "InstallLocation"):
                                try:
                                    raw = winreg.QueryValueEx(entry, value_name)[0]
                                except OSError:
                                    continue
                                hit = _as_qq_executable(raw)
                                if hit:
                                    return hit
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def _qq_from_running_process() -> Path | None:
    """QQ 正在运行时直接读进程映像路径，对无注册表登记的安装最可靠。"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if str(entry.szExeFile).casefold() == QQ_EXE_FILE_NAME.casefold():
                # PROCESS_QUERY_LIMITED_INFORMATION 才能读高权限进程的映像路径。
                handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        size = wintypes.DWORD(1024)
                        buffer = ctypes.create_unicode_buffer(1024)
                        if kernel32.QueryFullProcessImageNameW(
                            handle, 0, buffer, ctypes.byref(size)
                        ):
                            image = buffer.value
                            # NapCat 自己的目录下也放了一份 QQ.exe 副本，别把副本
                            # 当成用户安装的 QQ，否则会指向一个随时会被清理的目录。
                            if "napcat" not in image.casefold():
                                hit = _as_qq_executable(image)
                                if hit:
                                    return hit
                    finally:
                        kernel32.CloseHandle(handle)
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def _qq_from_common_install_dirs() -> Path | None:
    for letter in "CDEFG":
        drive = Path(f"{letter}:/")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        for base in ("Program Files", "Program Files (x86)"):
            for layout in QQ_INSTALL_LAYOUTS:
                hit = _as_qq_executable(drive / base / layout)
                if hit:
                    return hit
    return None


def qq_executable() -> Path:
    """按可靠性从高到低定位 QQ.exe，任何一环失败都继续往下找。"""
    # 1) 用户显式配置优先，但必须是真实存在的 QQ.exe，写错就继续探测。
    for raw in (project_env_value("QQ_EXE"), os.environ.get("QQ_EXE", "")):
        hit = _as_qq_executable(raw)
        if hit:
            return hit
    # 2) 官方默认位置，命中即返回，省掉后面的探测开销。
    hit = _as_qq_executable(DEFAULT_QQ_EXE)
    if hit:
        return hit
    # 3) 自定义目录 / 自定义盘符 / 运行中实例。
    for probe in (
        _qq_from_app_paths,
        _qq_from_uninstall_entries,
        _qq_from_running_process,
        _qq_from_common_install_dirs,
    ):
        hit = probe()
        if hit:
            return hit
    return DEFAULT_QQ_EXE


def qq_profile_dir() -> Path:
    r"""返回项目 QQ 专用的 Chromium/Electron 配置目录。

    QQ 的聊天数据库仍由 QQ 按账号写入 ``Documents\Tencent Files\<QQ号>``；
    这里隔离的是两个不同版本 QQ 最容易互相污染的界面缓存、WebStorage、
    Cookie 和 Electron 配置。桌面 QQ 不应登录 BOT_QQ 对应账号。
    """
    configured = (
        project_env_value("QQ_PROFILE_DIR")
        or os.environ.get("QQ_PROFILE_DIR", "")
    ).strip()
    return Path(configured).expanduser() if configured else DEFAULT_QQ_PROFILE_DIR


def napcat_quick_account() -> str | None:
    r"""本次启动使用的快速登录账号；``None`` 表示"按 BOT_QQ"。

    返回 ``""`` 表示**明确要求手动登录**（WebUI 的"切换账号"会写这个），此时既不
    传 ``-q`` 也不设 ``NAPCAT_QUICK_ACCOUNT``，否则 QQ 会用保存的会话把用户拉回
    刚退出的旧账号——这正是"退出了又登回原号"的成因。
    """

    try:
        raw = NAPCAT_QUICK_ACCOUNT_FILE.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not raw:
        return None
    if raw.casefold() in {"off", "manual", "none", "-"}:
        return ""
    return raw if raw.isdigit() else None


def set_napcat_quick_account(value: str | None) -> None:
    """写快速登录账号覆盖文件；``None`` 删除（回到按 BOT_QQ 的历史行为）。"""

    try:
        if value is None:
            NAPCAT_QUICK_ACCOUNT_FILE.unlink(missing_ok=True)
            return
        NAPCAT_QUICK_ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        NAPCAT_QUICK_ACCOUNT_FILE.write_text(f"{value}\n", encoding="utf-8")
    except OSError as exc:
        log(f"Unable to update NapCat quick-login override: {exc}")


def project_napcat_root() -> Path | None:
    """项目专用 NapCat 的 shell 根目录（``.../NapCat.<build>.Shell``）。"""

    napcat_dir = find_napcat_dir()
    if napcat_dir is None:
        return None
    for parent in napcat_dir.parents:
        if parent.name.casefold().endswith(".shell"):
            return parent
    return napcat_dir


def project_napcat_boot_pids() -> list[int]:
    """项目专用 NapCat 引导进程（只认自己的目录，不碰桌面 QQ 的进程）。"""

    root = project_napcat_root()
    if root is None:
        return []
    prefix = str(root).casefold()
    matches: list[int] = []
    for pid in pids_by_name("NapCatWinBootMain.exe"):
        path = process_executable_path(pid)
        if path is None:
            continue
        if str(path).casefold().startswith(prefix):
            matches.append(pid)
    return matches


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
    """构造已验证可用的专用 QQ 启动参数。

    ``qq_uin`` 为空时**不传 ``-q``**：那表示"这次要手动登录"（WebUI 切换账号时
    不能让 QQ 拿旧会话自动登回原账号）。传了 ``-q`` QQ 会尝试免扫码快速登录。
    """
    arguments = [str(qq_exe), "--enable-logging"]
    uin = str(qq_uin or "").strip()
    if uin:
        arguments.extend(["-q", uin])
    arguments.append(f"--user-data-dir={profile_dir}")
    return arguments


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


def launch_napcat_boot_process(
    *,
    launcher: Path,
    hook: Path,
    qq_exe: Path,
    qq_uin: str,
    profile_dir: Path,
    cwd: Path,
    env: dict[str, str],
) -> int:
    """通过 NapCat 自带引导器启动专用 QQ。

    之前这里复刻引导器的远程注入流程。该流程在 Windows 重启后的某些
    会话/安全策略下可能卡在 CreateProcessW 或 CreateRemoteThread，导致
    隐藏启动器永久占用互斥锁。官方引导器已经负责同样的注入和参数转发，
    因此只提交一次受控子进程，不在本进程里执行不可中断的注入调用。
    """
    qq_exe, profile_dir = validate_qq_isolation(qq_exe, profile_dir)
    if not hook.is_file():
        raise FileNotFoundError(f"NapCat hook not found: {hook}")
    if not launcher.is_file():
        raise FileNotFoundError(f"NapCat launcher not found: {launcher}")
    profile_dir.mkdir(parents=True, exist_ok=True)

    # launcher-user.bat 的实际调用约定：NapCatWinBootMain.exe
    # <QQ.exe> <NapCatWinBootHook.dll> [QQ arguments...]
    qq_args = isolated_qq_arguments(qq_exe, qq_uin, profile_dir)[1:]
    command = [str(launcher), str(qq_exe), str(hook), *qq_args]
    child = popen_hidden(command, cwd=cwd, env=env)

    # 只观察引导器很短时间，避免启动器因等待第三方进程而永久阻塞。
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        return_code = child.poll()
        if return_code is not None:
            if return_code != 0:
                raise OSError(
                    f"NapCat official launcher exited with code {return_code}."
                )
            break
        time.sleep(0.1)
    return int(child.pid)


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
    # 16GB 系统内存下只保留一个本地模型并串行推理；聊天、embedding 与视觉
    # 依次切换，避免同时加载两个 4B 模型耗尽 Windows 提交内存。
    defaults = {
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_QUEUE": "32",
        "OLLAMA_KEEP_ALIVE": "0",
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
    }
    for name, default in defaults.items():
        env[name] = project_env_value(name) or env.get(name) or default
    return env


def voice_enabled() -> bool:
    enabled_values = {"1", "true", "yes", "on"}
    return any(
        project_env_value(name).strip().lower() in enabled_values
        for name in ("VOICE_ASR_ENABLED", "VOICE_TTS_ENABLED")
    )


def voice_force_start_requested() -> bool:
    """WebUI 的"启动语音服务"开关用它绕过语音开关。

    歌曲合成链路依赖 8790 托管 Seed-VC 推理，与 QQ 语音开关是两件事；用户显式
    点击启动时不应被 VOICE_ASR_ENABLED/VOICE_TTS_ENABLED 静默拦住。
    """

    return os.getenv("ATRI_VOICE_FORCE_START", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    if not voice_enabled() and not voice_force_start_requested():
        return
    global VOICE_PORT, VOICE_HEALTH_URL
    src_dir = str(PROJECT_DIR / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from atri_shared.voice_endpoint import local_voice_port

    VOICE_PORT = local_voice_port()
    VOICE_HEALTH_URL = f"http://127.0.0.1:{VOICE_PORT}/health"
    already_listening = port_open(VOICE_PORT)
    if already_listening and not wait_for_ready:
        log(f"Voice service already listening on {VOICE_PORT}.")
        return
    if already_listening and voice_ready():
        log(f"Voice service already ready on {VOICE_PORT}.")
        return
    pass
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
    executable = (pythonw if pythonw.exists() else python)
    if not executable.exists():
        log("Voice feature is enabled but its isolated runtime is not installed.")
        return
    env = os.environ.copy()
    env["ATRI_VOICE_HOST"] = "127.0.0.1"
    env["ATRI_VOICE_PORT"] = str(VOICE_PORT)
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
    # GPT-SoVITS 冷启动可能需要加载数 GB 权重；启动等待与单次推理预算
    # 分开配置，且成功后保持常驻，避免每轮聊天重新冷启动。
    env.setdefault("ATRI_TTS_TOTAL_TIMEOUT_SECONDS", "75")
    env.setdefault("ATRI_TTS_STARTUP_TIMEOUT_SECONDS", "45")
    env.setdefault("ATRI_TTS_PREWARM_ENABLED", "true")
    env.setdefault("ATRI_TTS_IDLE_SHUTDOWN_SECONDS", "0")
    if not already_listening:
        log("Starting isolated voice service in background.")
        popen_logged(
            [str(executable), "-m", "atri_voice_service"],
            cwd=PROJECT_DIR,
            env=env,
            log_path=LOG_DIR / "voice-service.log",
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
    # AI_music 自带的 config/singing-pipeline.json 只是 external-api 占位（separator /
    # converter / mixer 全为 null），用它启动会让 WebUI 的三阶段工程报
    # "歌曲管线未配置人声分离命令"。本机真正可用的三阶段命令在 ATRI 的
    # data/voice/singing-pipeline.json，按 AI_music README 的要求显式指定。
    local_manifest = PROJECT_DIR / "data" / "voice" / "singing-pipeline.json"
    if local_manifest.is_file():
        env.setdefault("ATRI_MUSIC_PIPELINE_MANIFEST", str(local_manifest))
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


def start_qzone_bridge_if_needed(*, wait_for_ready: bool = True) -> None:
    """Start the local QQ-space Bridge on explicit opt-in only.

    The Bridge keeps polling QZone posts/comments/likes and silently refreshes the
    web login, so auto-starting it next to NapCat means the chat account keeps
    doing QZone web automation in the background.  It is therefore disabled by
    default and must be started manually from the WebUI (高级配置 → QQ 空间
    Bridge); only ``QZONE_BRIDGE_AUTOSTART=true`` restores the old behaviour.
    """
    if project_env_value("QZONE_BRIDGE_AUTOSTART").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        log(
            "QZone Bridge autostart is disabled (QZONE_BRIDGE_AUTOSTART!=true); "
            "start it manually from the WebUI when needed."
        )
        return
    enabled = project_env_value("QZONE_BRIDGE_ENABLED").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        log("QZone Bridge is disabled in .env; skipping startup.")
        return
    if port_open(QZONE_BRIDGE_PORT):
        log(f"QZone Bridge already listening on {QZONE_BRIDGE_PORT}.")
        return
    bridge_dir = PROJECT_DIR / "tools" / "onebot-qzone"
    bridge_script = bridge_dir / "start_bridge.ps1"
    if not bridge_script.exists():
        log(f"QZone Bridge startup script not found: {bridge_script}")
        return
    log("Starting QZone Bridge in background.")
    popen_hidden(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(bridge_script),
        ],
        cwd=bridge_dir,
    )
    if not wait_for_ready:
        return
    for _ in range(30):
        time.sleep(0.5)
        if port_open(QZONE_BRIDGE_PORT):
            log(f"QZone Bridge is ready on {QZONE_BRIDGE_PORT}.")
            return
    log("QZone Bridge did not report ready within timeout; ATRI will retry when it is available.")


def maibot_root() -> Path | None:
    configured = project_env_value("MAIBOT_ROOT") or os.environ.get("MAIBOT_ROOT", "")
    candidates = [Path(configured)] if configured else []
    candidates.extend((Path.home() / "MaiBot-install", PROJECT_DIR.parent / "MaiBot-install"))
    for candidate in candidates:
        if (candidate / "bot.py").exists():
            return candidate
    return None


def start_maibot_if_needed(*, wait_for_ready: bool = False) -> None:
    """Start the local MaiBot WebUI service without opening a console window."""
    if port_open(MAIBOT_PORT):
        log(f"MaiBot already listening on {MAIBOT_PORT}.")
        return
    root = maibot_root()
    if root is None:
        log("MaiBot installation was not found; skipping MaiBot startup.")
        return
    script = root / "start_maibot.ps1"
    if not script.exists():
        log(f"MaiBot startup script not found: {script}")
        return
    log(f"Starting MaiBot WebUI in background: {root}")
    popen_hidden(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=root,
    )
    if not wait_for_ready:
        return
    for _ in range(60):
        time.sleep(0.5)
        if port_open(MAIBOT_PORT):
            log(f"MaiBot is ready on {MAIBOT_PORT}.")
            return
    log("MaiBot did not report ready within timeout; check MaiBot logs/startup.log.")


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _windows_process_rows() -> list[dict[str, str]]:
    """使用 Toolhelp 快照枚举进程，避免冷启动时 tasklist/WMI 卡死。"""
    if os.name != "nt":
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        rows: list[dict[str, str]] = []
        while True:
            rows.append({"name": str(entry.szExeFile), "pid": str(int(entry.th32ProcessID))})
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        return rows
    finally:
        kernel32.CloseHandle(snapshot)


def process_rows() -> list[dict[str, str]]:
    return _windows_process_rows()


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


def start_ollama_if_needed(*, wait_for_ready: bool = True) -> None:
    configured_models = ollama_models_path()
    if port_open(OLLAMA_PORT):
        # 端口在监听不等于当前进程加载了项目模型目录。旧版 Ollama
        # 桌面进程可能先占用 11434，却使用 ~/.ollama/models，
        # 这会让项目看到空模型列表并持续返回 404。
        if ollama_api_has_models() and ollama_has_project_models(configured_models):
            log(f"Ollama already listening on {OLLAMA_PORT} with project models.")
            return
        log(
            f"Ollama is listening on {OLLAMA_PORT} but project models are unavailable; "
            "restarting it with the configured model directory."
        )
        stop_ollama_processes()

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
        # Ollama opens its TCP port before the model registry API is ready.
        # Treating the socket as readiness lets the first chat request race
        # startup and surface as a timeout/502.
        if port_open(OLLAMA_PORT) and ollama_api_has_models():
            log("Ollama is ready.")
            return
    log("Ollama did not report ready within timeout.")


def ollama_has_project_models(models_path: Path) -> bool:
    """检查项目模型目录是否有 Ollama manifest，避免把空服务当成可用。"""
    manifest_root = models_path / "manifests"
    try:
        return any(manifest_root.rglob("*") if manifest_root.is_dir() else ())
    except OSError:
        return False


def ollama_api_has_models() -> bool:
    """读取当前 11434 服务的模型列表，识别“空 Ollama 服务”状态。"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{OLLAMA_PORT}/api/tags",
            timeout=2.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return bool(payload.get("models")) if isinstance(payload, dict) else False
    except (OSError, ValueError, TypeError):
        return False


def stop_ollama_processes() -> None:
    """仅停止 Ollama 进程，不影响 QQ、NapCat 或项目 Python 服务。"""
    for process in run_hidden(["taskkill", "/F", "/T", "/IM", "ollama.exe"]).stdout.splitlines():
        if process.strip():
            log(f"Stopped stale Ollama process: {process.strip()}")


def start_atri_if_needed(*, wait_for_ready: bool = True) -> bool:
    if port_open(BOT_PORT):
        if bot_connected():
            log(f"Atri service already listening on {BOT_PORT} and NapCat is connected.")
        else:
            log(
                f"Atri service already listening on {BOT_PORT}; "
                "keeping it alive while NapCat connects."
            )
        return True

    python_exe = PROJECT_PYTHONW if PROJECT_PYTHONW.exists() else PROJECT_PYTHON
    if not False and not python_exe.exists():
        log(r"Python venv not found. Run tools\launch\atri\start-atri.bat once to repair dependencies.")
        return False

    log("Starting Atri service in background.")
    try:
        service_log = roll_service_log(ATRI_SERVICE_LOG)
        popen_logged(
            ([str(python_exe), "-m", "atri_qq_bot"]),
            cwd=PROJECT_DIR,
            log_path=service_log,
        )
    except OSError as exc:
        log(f"Atri process could not be started: {exc}")
        return False
    if not wait_for_ready:
        log("Atri startup requested; NapCat may start in parallel.")
        return True
    for _ in range(75):
        time.sleep(0.2)
        if port_open(BOT_PORT):
            log("Atri service is ready.")
            return True
    log(
        "Atri service did not report ready within timeout. "
        f"See {ATRI_SERVICE_LOG} for the process output."
    )
    return False


def roll_service_log(log_path: Path) -> Path:
    """给本次启动准备一份服务日志：过大就轮转，并写下分隔标记。"""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > ATRI_SERVICE_LOG_MAX_BYTES:
            rotated = log_path.with_suffix(".old.log")
            try:
                if rotated.exists():
                    rotated.unlink()
                log_path.replace(rotated)
            except OSError:
                log_path.unlink(missing_ok=True)
        with open(str(log_path), "ab") as handle:
            handle.write(
                f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"atri_qq_bot start =====\n".encode("utf-8", errors="replace")
            )
    except OSError as exc:
        log(f"Could not prepare service log: {exc}")
    return log_path


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
        if bot_connected():
            if keep_qq_hidden:
                hide_qq_windows()
            log("NapCat connected to Atri.")
            return True
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(NAPCAT_CONNECTION_POLL_SECONDS, remaining))
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


def close_project_qq_windows(pids: list[int] | tuple[int, ...]) -> bool:
    """Ask only the project QQ windows to close so login tokens can be flushed."""
    if os.name != "nt":
        return False
    qq_pids = {int(pid) for pid in pids}
    if not qq_pids:
        return False

    user32 = ctypes.windll.user32
    close_requested = False
    enum_proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    def close_window(hwnd: int, _lparam: int) -> bool:
        nonlocal close_requested
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in qq_pids:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            close_requested = True
        return True

    user32.EnumWindows(enum_proc_type(close_window), 0)
    return close_requested


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


def stop_atri_service(timeout_seconds: float = 5.0) -> bool:
    """停止占用项目 OneBot 端口的 ATRI 进程。"""
    try:
        from atri_qq_bot.runtime.control import tcp_rows
    except ImportError as exc:
        log(f"Could not inspect Atri listener: {exc}")
        return False

    listener_pids = sorted(
        {
            int(row["pid"])
            for row in tcp_rows()
            if row.get("state") == "LISTENING"
            and row.get("local_port") == BOT_PORT
            and isinstance(row.get("pid"), int)
        }
    )
    if not listener_pids:
        return True

    log(f"Stopping Atri listener processes: pids={listener_pids}")
    for pid in listener_pids:
        if pid != os.getpid():
            taskkill_process_tree(pid)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not port_open(BOT_PORT):
            return True
        time.sleep(0.1)
    log(f"Atri listener did not stop within {timeout_seconds:.1f}s.")
    return False


def stop_project_napcat(timeout_seconds: float = 8.0) -> bool:
    """仅停止项目专用 QQ/NapCat，不影响用户独立安装的桌面 QQ。"""
    project_pids = sorted(set(project_qq_pids()))
    if not project_pids:
        return True

    log(f"Closing project NapCat QQ gracefully: pids={project_pids}")
    close_project_qq_windows(project_pids)
    if wait_for_project_qq_exit(timeout_seconds):
        return True

    remaining_pids = sorted(set(project_qq_pids()))
    log(
        f"Project NapCat QQ did not close within {timeout_seconds:.1f}s; "
        f"forcing remaining pids={remaining_pids}."
    )
    for pid in remaining_pids:
        taskkill_process_tree(pid)
    return wait_for_project_qq_exit(2.0)


def recover_background_services() -> bool:
    """重建 ATRI 与项目专用 NapCat 会话，清除假在线和失效 QQ 内核。"""
    required = required_napcat_files()
    if required is None:
        publish_napcat_state("failed", detail="NapCat 运行文件不完整，无法执行恢复")
        return False

    publish_napcat_state("recovering", detail="正在重启 ATRI 与项目专用 NapCat/QQ")
    if not stop_atri_service():
        publish_napcat_state("failed", detail="ATRI 旧进程未能停止")
        return False
    if not stop_project_napcat():
        publish_napcat_state("failed", detail="项目专用 NapCat/QQ 旧进程未能停止")
        return False
    if not start_atri_if_needed(wait_for_ready=True):
        publish_napcat_state("failed", detail="ATRI 重启失败")
        return False
    return launch_napcat(required)


def launch_napcat(
    required: tuple[Path, Path, Path, Path, Path] | None = None,
) -> bool:
    required = required or required_napcat_files()
    if required is None:
        return False
    launcher, hook, napcat_main, load_path, patch_package = required
    quick_override = napcat_quick_account()
    if quick_override == "":
        qq_uin = ""
        log("NapCat quick login disabled by data/runtime/napcat-quick-account.txt; manual login required.")
    else:
        qq_uin = quick_override or bot_qq_uin()
        if not qq_uin:
            log("BOT_QQ is missing or invalid in .env.")
            return False
    qq_exe = qq_executable()
    profile_dir = qq_profile_dir()
    napcat_dir = launcher.parent
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
        }
    )
    if qq_uin:
        env["NAPCAT_QUICK_ACCOUNT"] = qq_uin
    else:
        env.pop("NAPCAT_QUICK_ACCOUNT", None)
    log(
        f"Starting isolated NapCat QQ for {qq_uin or 'manual login'}. "
        f"qq={qq_exe}; profile={profile_dir}"
    )
    publish_napcat_state("starting", detail="正在启动专用 NapCat/QQ")
    try:
        pid = launch_napcat_boot_process(
            launcher=launcher,
            hook=hook,
            qq_exe=qq_exe,
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
    log("NapCat login is not confirmed; waiting for manual login through NapCat WebUI.")
    if wait_for_connection(55):
        return True
    if port_open(NAPCAT_WEBUI_PORT) or process_running("NapCatWinBootMain.exe"):
        detail = "NapCat 已启动但 QQ 未登录，请打开 NapCat WebUI 手动扫码登录"
        log(detail)
        publish_napcat_state("login_required", detail=detail)
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
        detail = "NapCat 已启动但 QQ 未登录，请打开 NapCat WebUI 手动扫码登录"
        log("QQ and NapCat are running without an Atri connection; login is required.")
        publish_napcat_state("login_required", detail=detail)
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
        if wait_for_connection(45):
            return
        detail = "NapCat 已启动但未连接，请打开 NapCat WebUI 手动扫码登录"
        log(detail)
        publish_napcat_state("login_required", detail=detail)
        return
    else:
        log("No stale QQ/NapCat process found; starting directly.")
    launch_napcat(required)


def restart_napcat_for_login() -> bool:
    """停掉项目专用 QQ/NapCat 再重新拉起，用于 WebUI 的"切换账号"。

    只停自己安装目录下的进程（桌面 QQ 不受影响），启动时是否快速登录由
    :func:`napcat_quick_account` 决定——切换流程会写到"手动登录"，所以重启后
    会停在二维码页面，让用户扫码或输密码登另一个号。
    """

    publish_napcat_state("recovering", detail="正在重启 NapCat 以便切换账号")
    if not stop_project_napcat():
        log("NapCat/QQ could not be stopped; aborting account switch restart.")
        publish_napcat_state("failed", detail="NapCat/QQ 未能停止，账号切换已中止")
        return False
    for pid in project_napcat_boot_pids():
        taskkill_process_tree(pid)
    time.sleep(1.0)
    required = required_napcat_files()
    if required is None:
        publish_napcat_state("failed", detail="NapCat 运行文件不完整，无法重启")
        return False
    # launch_napcat 返回 False 表示"已启动但未登录"——这正是切换账号时的预期状态。
    launch_napcat(required)
    return True


def main(mode: str = "core") -> int:
    """Start one bounded runtime slice instead of every model at once.

    ``core`` is the source launcher default. It brings up ATRI first, then delegates
    NapCat recovery and optional integrations to isolated modes. Heavy inference
    services are launched by their first real request, so normal QQ text chat
    cannot exhaust Windows virtual memory or destabilise system audio.
    """
    normalized_mode = str(mode or "core").strip().lower()
    supported_modes = {
        "core",
        "recover",
        "napcat",
        "napcat-restart",
        "optional",
        "voice-asr",
        "voice-tts",
        "ollama",
        "music",
    }
    if normalized_mode not in supported_modes:
        log(f"Unknown launcher mode: {normalized_mode}.")
        return 2
    if not acquire_single_instance_mutex(f"AtriQQHiddenLauncher-{normalized_mode}"):
        log(f"Hidden launcher mode {normalized_mode} is already running; ignoring duplicate request.")
        return 0
    log(f"Hidden QQ launcher invoked. mode={normalized_mode}")

    if normalized_mode == "core":
        # QQ text chat is the critical path.  Confirm ATRI is listening first,
        # then let NapCat recovery continue independently because manual login
        # can legitimately take much longer than service startup.
        if not start_atri_if_needed(wait_for_ready=True):
            log("Core startup stopped because Atri did not become ready.")
            return 1
        start_launcher_mode_in_background("napcat")
        start_launcher_mode_in_background("optional")
        return 0
    if normalized_mode == "recover":
        return 0 if recover_background_services() else 1
    if normalized_mode == "napcat":
        start_napcat_if_needed()
        return 0
    if normalized_mode == "optional":
        # Give the QQ chat path first access to disk and CPU after a cold boot.
        # Optional integrations still start if login requires manual action.
        if not wait_for_connection(OPTIONAL_SERVICES_WAIT_SECONDS):
            log("NapCat is not ready yet; starting optional services without blocking chat recovery.")
        try:
            start_qzone_bridge_if_needed(wait_for_ready=False)
        except Exception as exc:
            log(f"Optional QZone Bridge startup failed: {exc}")
        time.sleep(OPTIONAL_SERVICES_STAGGER_SECONDS)
        try:
            start_maibot_if_needed(wait_for_ready=False)
        except Exception as exc:
            log(f"Optional MaiBot startup failed: {exc}")
        return 0
    if normalized_mode == "voice-asr":
        start_voice_if_needed(wait_for_ready=True)
        return 0
    if normalized_mode == "voice-tts":
        # 只恢复轻量服务；GPT-SoVITS 必须由请求在全局推理锁内启动。
        start_voice_if_needed(wait_for_ready=True)
        return 0
    if normalized_mode == "ollama":
        start_ollama_if_needed(wait_for_ready=True)
        return 0
    if normalized_mode == "music":
        start_music_bridge_if_needed()
        return 0
    if normalized_mode == "napcat-restart":
        return 0 if restart_napcat_for_login() else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "core"))
