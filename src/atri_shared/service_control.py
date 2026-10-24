"""语音服务托管与歌曲工作台入口。

这里只剩两件事：

* **atri_voice_service**（本机端口由 ``VOICE_SERVICE_URL`` 配置，默认 ``8790``）
  可由桌面软件独立启动，也支持 QQ 语音链路按需拉起。停止前验证健康接口身份，
  不做优雅退出协调：正在唱歌/说话时点停止
  会直接掐断当次合成，这是用户主动选择的行为。
* **AI_music 歌曲工作台**（前端 ``3000``、桥接 ``8793``）已经迁出本项目，
  生命周期由那个项目自己的 ``scripts/start.ps1`` 负责。这里只做只读探活，并在
  用户点击时调用对方脚本；本项目不再拥有桥接进程，也不再读取它的工程目录。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from atri_qq_bot.runtime.control import run_hidden, tcp_rows
from atri_qq_bot.runtime.paths import PROJECT_ROOT, TOOLS_DIR
from .voice_endpoint import local_voice_port, validate_port


VOICE_SERVICE_PORT = 8790
MUSIC_BRIDGE_PORT = 8793
MUSIC_WORKBENCH_PORT = 3000

#: AI_music 项目位置；只在调用对方启动脚本时用到，不读取它的任何数据文件。
MUSIC_WORKBENCH_ROOT = (
    Path(os.getenv("ATRI_MUSIC_PROJECT_DIR", "")).expanduser().resolve()
    if os.getenv("ATRI_MUSIC_PROJECT_DIR", "").strip()
    else PROJECT_ROOT.parent / "多模态AI" / "AI_music"
)
MUSIC_WORKBENCH_SCRIPT = MUSIC_WORKBENCH_ROOT / "scripts" / "start.ps1"
WORKBENCH_URL = os.getenv(
    "ATRI_MUSIC_UI_URL", f"http://127.0.0.1:{MUSIC_WORKBENCH_PORT}/workbench"
)

VOICE_LOG = PROJECT_ROOT / "logs" / "voice-service.log"
LAUNCHER = TOOLS_DIR / "launch" / "qq_legacy" / "hidden_launcher.py"

_PORT_PROBE_TIMEOUT_SECONDS = 0.4
_HTTP_PROBE_TIMEOUT_SECONDS = 3.0
_WORKBENCH_WAIT_SECONDS = 60.0
_VOICE_SERVICE_WAIT_SECONDS = 60.0
_VOICE_SERVICE_STOP_WAIT_SECONDS = 10.0
#: 工作台要停两个端口（桥接 + 前端），前端 dev server 退出稍慢，给宽一点。
_MUSIC_STOP_WAIT_SECONDS = 12.0


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    """只做一次 TCP 连接探测，不发起 HTTP 请求，避免给冷启动的服务加压。"""

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(_PORT_PROBE_TIMEOUT_SECONDS)
    try:
        return client.connect_ex((host, int(port))) == 0
    finally:
        client.close()


def _probe_json(port: int, path: str) -> dict[str, Any] | None:
    """读取服务自己的 HTTP 接口；失败返回 None，不把异常抛给 WebUI。"""

    try:
        with urlopen(
            f"http://127.0.0.1:{int(port)}{path}",
            timeout=_HTTP_PROBE_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _launcher_command(mode: str) -> list[str] | None:
    """构造隐藏启动器命令；缺少启动器或 Python 运行时返回 None。"""

    if not LAUNCHER.is_file():
        return None
    candidates = (
        PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    )
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        return None
    return [str(executable), str(LAUNCHER), mode]


def _detached_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def _launch_runtime_mode(mode: str, *, extra_env: dict[str, str] | None = None) -> None:
    """后台拉起一个隐藏启动器模式；启动器自带单实例互斥锁，重复点击是安全的。"""

    pass
    command = _launcher_command(mode)
    if command is None:
        raise FileNotFoundError(f"未找到隐藏启动器或 Python 运行时：{LAUNCHER}")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=_detached_flags(),
        close_fds=True,
    )


def _wait_for_port(port: int, wait_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.5, float(wait_seconds))
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return _port_open(port)


def music_workbench_status() -> dict[str, Any]:
    """歌曲工作台的三段状态：前端、桥接、语音服务。

    前端与桥接是两个独立进程，只报一个"不可达"会把原因说反（例如界面没起但桥接
    在跑），所以这里分开探测，并给出可直接照做的提示。
    """

    web_running = _port_open(MUSIC_WORKBENCH_PORT)
    bridge_running = _port_open(MUSIC_BRIDGE_PORT)
    voice_port = local_voice_port(VOICE_SERVICE_PORT)
    voice_running = _port_open(voice_port)
    voice_health = _probe_json(voice_port, "/health") if voice_running else None
    voice_ready = bool(voice_running and (voice_health or {}).get("ready"))
    script_ready = MUSIC_WORKBENCH_SCRIPT.is_file()

    if not web_running and not bridge_running:
        detail = "工作台未运行，可以点「启动工作台」" if script_ready else "请先独立安装 AI_music，并设置 ATRI_MUSIC_PROJECT_DIR"
    elif not web_running:
        detail = f"桥接在线，但界面 {WORKBENCH_URL} 未监听：执行 scripts\\start.ps1 -Mode Web"
    elif not bridge_running:
        detail = f"界面在线，但桥接 {MUSIC_BRIDGE_PORT} 未监听：执行 scripts\\start.ps1 -Mode Bridge"
    elif not voice_running:
        detail = f"工作台已就绪；模型推理需要语音服务（{voice_port}），可点「启动语音服务」"
    else:
        detail = "工作台已就绪"

    return {
        "ok": True,
        "service": "music_workbench",
        "web": {"running": web_running, "port": MUSIC_WORKBENCH_PORT, "url": WORKBENCH_URL},
        "bridge": {"running": bridge_running, "port": MUSIC_BRIDGE_PORT},
        "voice_service": {
            "running": voice_running,
            "port": voice_port,
            "ready": voice_ready,
        },
        "launcher_ready": script_ready,
        "launcher": str(MUSIC_WORKBENCH_SCRIPT),
        "root": str(MUSIC_WORKBENCH_ROOT),
        "detail": detail,
    }




def start_music_workbench(*, wait_seconds: float = _WORKBENCH_WAIT_SECONDS) -> dict[str, Any]:
    """调用 AI_music 自己的启动脚本拉起工作台。

    本项目不直接管理桥接进程：只把对方的脚本当命令执行，端口、管线参数与日志
    目录都由那个项目决定，避免两处各有一套启动逻辑。
    """

    pass
    if _port_open(MUSIC_WORKBENCH_PORT) and _port_open(MUSIC_BRIDGE_PORT):
        status = music_workbench_status()
        status.update({"started": False, "message": "工作台已在运行，未重复启动"})
        return status

    if not MUSIC_WORKBENCH_SCRIPT.is_file():
        raise FileNotFoundError(
            f"未找到工作台启动脚本：{MUSIC_WORKBENCH_SCRIPT}；"
            "可用 ATRI_MUSIC_PROJECT_DIR 指定 AI_music 项目目录"
        )
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        raise FileNotFoundError("未找到 PowerShell，无法调用工作台启动脚本")

    subprocess.Popen(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(MUSIC_WORKBENCH_SCRIPT),
            "-NoWait",
        ],
        cwd=str(MUSIC_WORKBENCH_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_detached_flags(),
        close_fds=True,
    )

    if wait_seconds <= 0:
        return {"ok": True, "started": True, "message": "已提交音乐工作台启动命令"}

    deadline = max(1.0, float(wait_seconds))
    bridge_ready = _wait_for_port(MUSIC_BRIDGE_PORT, deadline)
    web_ready = _wait_for_port(MUSIC_WORKBENCH_PORT, 5.0) if bridge_ready else False
    status = music_workbench_status()
    status.update(
        {
            "started": True,
            "message": (
                f"工作台已启动：{WORKBENCH_URL}"
                if bridge_ready and web_ready
                else f"已发出启动命令，但 {int(deadline)} 秒内端口未全部就绪；"
                "请在 AI_music 项目的 data/runtime 目录查看日志"
            ),
        }
    )
    return status


def voice_service_status(*, enabled: bool = True) -> dict[str, Any]:
    """atri_voice_service 状态：端口、模型是否预热完成、启动器是否可用。"""

    port = local_voice_port(VOICE_SERVICE_PORT)
    listening = _port_open(port)
    health = _probe_json(port, "/health") if listening else None
    available = bool(health and health.get("service") == "atri-voice" and health.get("ok") is not False)
    ready = bool(available and (health.get("ready") or (health.get("conversation_speech") or {}).get("ready")))
    launcher_ready = _launcher_command("voice-asr") is not None
    pass
    if not listening:
        detail = "未运行；QQ 语音回复与语音合成都会失败" + (
            "" if enabled else "（语音开关当前关闭，仍可在这里手动启动）"
        )
    elif not available:
        detail = "端口被占用，但未确认是 ATRI 语音服务；请检查端口或查看启动日志"
    elif ready:
        detail = "服务已就绪；识别模型在首次使用时加载" if (health.get("asr") or {}).get("dependency_available") and not (health.get("asr") or {}).get("loaded") else "运行中且模型已就绪"
    else:
        detail = "端口已监听，模型仍在预热"
    return {
        "ok": True,
        "service": "voice_service",
        "running": listening,
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "can_stop": available,
        "ready": ready,
        "available": available,
        "asr": dict(health.get("asr") or {}) if available else {},
        "detail": detail,
        "enabled": bool(enabled),
        "launcher_ready": launcher_ready,
        "launcher": str(LAUNCHER),
        "log": str(VOICE_LOG),
    }


def start_voice_service(*, wait_seconds: float = _VOICE_SERVICE_WAIT_SECONDS) -> dict[str, Any]:
    """按需启动 atri_voice_service（隐藏启动器的 voice-asr 模式）。

    启动器的 ``voice-asr`` 模式平时受 ``VOICE_ASR_ENABLED`` / ``VOICE_TTS_ENABLED``
    约束；这里显式带上 ``ATRI_VOICE_FORCE_START=1``，因为用户点击按钮就是明确的启动
    意图，而且歌曲合成的模型推理链路也需要这个服务来托管 Seed-VC。
    """

    port = local_voice_port(VOICE_SERVICE_PORT)
    if _port_open(port):
        status = voice_service_status()
        status.update({"ok": status["available"], "started": False, "message": (
            "语音服务已在运行，未重复启动" if status["available"] else f"端口 {port} 已被占用，未启动服务"
        )})
        return status

    _launch_runtime_mode("voice-asr", extra_env={
        "ATRI_VOICE_FORCE_START": "1", "ATRI_VOICE_PORT": str(port), "ATRI_VOICE_HOST": "127.0.0.1",
    })
    if _wait_for_port(port, wait_seconds):
        status = voice_service_status()
        # The socket can listen before the HTTP handler is ready to identify
        # itself. Give the newly launched service a short readiness grace period.
        deadline = time.monotonic() + min(5.0, max(0.0, float(wait_seconds)))
        while status["running"] and not status["available"] and time.monotonic() < deadline:
            time.sleep(0.2)
            status = voice_service_status()
        status.update(
            {
                "ok": status["available"],
                "started": True,
                "message": ("语音服务已启动，可刷新状态查看模型就绪情况" if status["available"]
                            else "端口已监听但语音接口尚未响应，请刷新状态或查看日志"),
            }
        )
        return status

    status = voice_service_status()
    status.update(
        {
            "ok": False,
            "started": True,
            "message": (
                f"已发出启动命令，但 {int(wait_seconds)} 秒内 {port} 未就绪；"
                f"请查看 {status['log']}"
            ),
        }
    )
    return status


def _listening_pids(port: int) -> list[int]:
    """按端口找出处于 LISTENING 状态的进程 PID。"""

    return sorted(
        {
            int(row["pid"])
            for row in tcp_rows()
            if row["state"] == "LISTENING"
            and row["local_port"] == port
            and isinstance(row["pid"], int)
        }
    )


def stop_voice_service(*, wait_seconds: float = _VOICE_SERVICE_STOP_WAIT_SECONDS) -> dict[str, Any]:
    """停止 atri_voice_service：验证身份后结束监听配置端口的进程树。

    与桌宠「停止 Atri」同一套路（taskkill /T /F）：不做优雅退出协调，正在
    进行的合成会被掐断，这是用户点「停止」时明确选择的行为。已加载的模型
    权重随之释放，下次使用会重新冷启动。
    """

    port = local_voice_port(VOICE_SERVICE_PORT)
    pids = _listening_pids(port)
    if not pids:
        status = voice_service_status(enabled=True)
        status.update({"stopped": False, "message": "语音服务当前未运行"})
        return status

    status = voice_service_status()
    if not status["available"]:
        status.update({"ok": False, "stopped": False,
                       "message": f"未确认端口 {port} 上是 ATRI 语音服务，未结束任何进程"})
        return status

    failed: list[str] = []
    for pid in pids:
        completed = run_hidden(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"], timeout=5.0
        )
        if completed.returncode != 0:
            failed.append(f"PID {pid}")

    stopped = False
    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    while time.monotonic() < deadline:
        if not _listening_pids(port):
            stopped = True
            break
        time.sleep(0.3)

    status = voice_service_status(enabled=True)
    status["stopped"] = stopped
    status["ok"] = stopped
    if stopped:
        status["message"] = "语音服务已停止；下次语音功能可用时再在这里启动"
    else:
        detail = "停止命令已执行，但端口仍被占用"
        if failed:
            detail += f"（未能结束 {', '.join(failed)}）"
        status["message"] = f"{detail}；请到任务管理器手动处理，日志见 {status['log']}"
    return status


def voice_service_settings() -> dict[str, Any]:
    """Read-only metadata: no socket, process, runtime import or file writes."""
    port = local_voice_port(VOICE_SERVICE_PORT)
    url = f"http://127.0.0.1:{port}"
    return {"port": port, "host": "127.0.0.1", "url": url,
            "health_url": url + "/health", "synthesize_url": url + "/v1/synthesize",
            "transcribe_url": url + "/v1/transcribe", "log": str(VOICE_LOG)}


def save_voice_service_settings(port: object) -> dict[str, Any]:
    port = validate_port(port)
    current = local_voice_port(VOICE_SERVICE_PORT)
    if port != current:
        if _port_open(current) and voice_service_status()["available"]:
            raise ValueError("请先停止当前语音服务，再修改端口")
        if _port_open(port):
            raise ValueError(f"端口 {port} 已被占用，请换一个端口")
    from .config_admin import update_env

    update_env({"VOICE_SERVICE_URL": f"http://127.0.0.1:{port}"})
    return {"ok": True, "data": voice_service_settings(),
            "message": "语音端口已保存，下次启动生效；其他项目请使用新的接口地址。"}


def voice_service_log() -> str:
    parts: list[str] = []
    # Fixed sibling paths only. Include launcher failures before a runtime exists.
    for path, limit in ((VOICE_LOG, 16000),
                        (VOICE_LOG.with_name("voice-service-error.log"), 4000),
                        (VOICE_LOG.with_name("hidden-launcher.log"), 4000)):
        if path.is_file():
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - limit))
                parts.append(f"[{path.name}]\n" + stream.read().decode("utf-8", errors="replace"))
    return "\n\n".join(parts) if parts else "暂无语音服务日志。"


def stop_music_workbench(
    *, wait_seconds: float = _MUSIC_STOP_WAIT_SECONDS
) -> dict[str, Any]:
    """停止 AI_music 歌曲工作台：结束占用 8793（桥接）与 3000（界面）的进程树。

    ⚠️ 这两个端口属于**另一个项目**（AI_music），本项目只按端口探测并结束
    占用者，不去读它的工程目录、也不做优雅退出协调 —— 与 ``start_music_workbench``
    只调对方脚本是同一个边界原则。

    只结束**这两个端口**上的监听进程，不会碰到 AI_music 可能同时跑着的
    其它任务（例如它自己的批量跑批进程没有监听端口）。
    """
    targets = {
        MUSIC_BRIDGE_PORT: _listening_pids(MUSIC_BRIDGE_PORT),
        MUSIC_WORKBENCH_PORT: _listening_pids(MUSIC_WORKBENCH_PORT),
    }
    if not any(targets.values()):
        status = music_workbench_status()
        status.update({"stopped": False, "message": "歌曲工作台当前未运行"})
        return status

    failed: list[str] = []
    for port, pids in targets.items():
        for pid in pids:
            completed = run_hidden(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"], timeout=5.0
            )
            if completed.returncode != 0:
                failed.append(f"PID {pid}（{port}）")

    stopped = False
    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    while time.monotonic() < deadline:
        if not _port_open(MUSIC_BRIDGE_PORT) and not _port_open(MUSIC_WORKBENCH_PORT):
            stopped = True
            break
        time.sleep(0.3)

    status = music_workbench_status()
    status["stopped"] = stopped
    if stopped:
        status["message"] = "歌曲工作台已停止"
    else:
        detail = "停止命令已执行，但端口仍被占用"
        if failed:
            detail += f"（未能结束 {', '.join(failed)}）"
        status["message"] = f"{detail}；请到任务管理器手动处理"
    return status
