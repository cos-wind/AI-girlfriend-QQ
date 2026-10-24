"""QQ空间 Bridge 的手动启停控制。

Bridge 是 ``tools/onebot-qzone`` 下的独立 Node 进程（默认监听 5700）。它过去由
隐藏启动器在 ``optional`` 模式随 NapCat 一起拉起；因为 Bridge 一旦运行就会持续
轮询说说/评论/点赞并定期静默续期登录态，等于聊天账号在后台一直做空间网页自动化，
所以现在改成**默认不自动启动**，只允许在 WebUI 里由用户显式点击启动/停止。

本模块只负责进程与端口层面的事，不接触 Cookie 内容；登录态由 Bridge 自己维护。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = PROJECT_ROOT / "tools" / "onebot-qzone"
BRIDGE_SCRIPT = BRIDGE_DIR / "start_bridge.ps1"
BRIDGE_PORT = 5700
BRIDGE_HOST = "127.0.0.1"

_PORT_PROBE_TIMEOUT_SECONDS = 0.4
_START_WAIT_SECONDS = 25.0
_STOP_WAIT_SECONDS = 10.0
_STATUS_TIMEOUT_SECONDS = 3.0


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def port_open(port: int = BRIDGE_PORT, host: str = BRIDGE_HOST) -> bool:
    """只做一次 TCP 连接探测，不发起任何 HTTP 请求。"""

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(_PORT_PROBE_TIMEOUT_SECONDS)
    try:
        return client.connect_ex((host, int(port))) == 0
    finally:
        client.close()


def _pids_listening_on(port: int) -> list[int]:
    """用 netstat 找占用端口的进程；不依赖 psutil。"""

    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: set[int] = set()
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        local_address = parts[1]
        if not local_address.endswith(f":{port}"):
            continue
        try:
            pids.add(int(parts[4]))
        except ValueError:
            continue
    return sorted(pids)


def _kill_process_tree(pid: int) -> bool:
    if os.name != "nt":
        return False
    try:
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _bridge_status_payload() -> dict[str, Any] | None:
    """读取 Bridge 自己的 /status；失败返回 None（不抛异常给 WebUI）。"""

    headers = {"Accept": "application/json"}
    token = str(os.getenv("QZONE_BRIDGE_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/status", headers=headers)
    try:
        with urlopen(request, timeout=_STATUS_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def bridge_status() -> dict[str, Any]:
    """给 WebUI 用的状态快照：是否监听、是否登录、以及两个开关的当前值。"""

    listening = port_open()
    payload = _bridge_status_payload() if listening else None
    detail = "未运行"
    if listening and payload is None:
        detail = "端口已监听，但 /status 无响应（可能仍在启动或登录）"
    elif listening:
        if payload.get("good") or payload.get("online"):
            detail = "运行中且已登录"
        else:
            detail = "运行中但未登录，需要在 Bridge 侧扫码"
    return {
        "ok": True,
        "running": listening,
        "port": BRIDGE_PORT,
        "detail": detail,
        "enabled_in_env": _env_flag("QZONE_BRIDGE_ENABLED"),
        "autostart_in_env": _env_flag("QZONE_BRIDGE_AUTOSTART"),
        "script_exists": BRIDGE_SCRIPT.exists(),
        "bridge_dir": str(BRIDGE_DIR),
        "status": payload,
    }


def start_bridge(*, wait_seconds: float = _START_WAIT_SECONDS) -> dict[str, Any]:
    """手动启动 Bridge 并等待端口就绪（不会随桌宠启动）。"""

    if port_open():
        status = bridge_status()
        status["started"] = False
        status["message"] = "Bridge 已经在运行，未重复启动"
        return status
    if not BRIDGE_SCRIPT.exists():
        raise FileNotFoundError(f"未找到 Bridge 启动脚本：{BRIDGE_SCRIPT}")

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BRIDGE_SCRIPT),
        ],
        cwd=str(BRIDGE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )

    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    while time.monotonic() < deadline:
        if port_open():
            time.sleep(1.0)
            status = bridge_status()
            status["started"] = True
            status["message"] = "Bridge 已启动"
            return status
        time.sleep(0.5)

    status = bridge_status()
    status["started"] = True
    status["message"] = (
        f"已发出启动命令，但 {int(wait_seconds)} 秒内端口未就绪；"
        f"请查看 {BRIDGE_DIR / 'logs' / 'startup.log'}"
    )
    return status


def stop_bridge(*, wait_seconds: float = _STOP_WAIT_SECONDS) -> dict[str, Any]:
    """停止占用 Bridge 端口的进程树。"""

    if not port_open():
        status = bridge_status()
        status["stopped"] = False
        status["message"] = "Bridge 当前未运行"
        return status

    pids = _pids_listening_on(BRIDGE_PORT)
    killed: list[int] = []
    for pid in pids:
        if _kill_process_tree(pid):
            killed.append(pid)

    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    while time.monotonic() < deadline:
        if not port_open():
            break
        time.sleep(0.5)

    status = bridge_status()
    status["stopped"] = not status["running"]
    status["killed_pids"] = killed
    if status["running"]:
        status["message"] = (
            "未能停止 Bridge；可能由其它用户或服务启动，请手动结束占用 "
            f"{BRIDGE_PORT} 端口的进程"
        )
    else:
        status["message"] = "Bridge 已停止"
    return status
