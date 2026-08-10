from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import time
from ctypes import wintypes
from typing import Any

from ..config import BotConfig
from .observability import napcat_webui_access
from .paths import DATA_DIR, PROJECT_ROOT, TOOLS_DIR


NAPCAT_STATE_FILE = DATA_DIR / "runtime" / "napcat-state.json"
NAPCAT_STATE_MAX_AGE_SECONDS = 600
# NapCat 的反向 WebSocket 即使 QQ 客户端已掉线也可能暂时保持连接。
# 正常情况下 OneBot 会每 30 秒上报一次心跳，因此连续两轮没有任何
# OneBot 负载时，不能再把“TCP 已建立”误显示为“可收发消息”。
ONEBOT_EVENT_STALE_SECONDS = 90
ONEBOT_PROBE_STALE_SECONDS = 75


def publish_napcat_runtime_state(state: str, *, detail: str = "") -> None:
    payload = _read_napcat_state_file()
    if state in {"starting", "recovering", "probing", "disconnected", "login_required"}:
        payload.pop("probe_ok", None)
        payload.pop("probe_at", None)
        payload.pop("probe_self_id", None)
    payload.update({
        "state": state,
        "detail": detail,
        "updated_at": time.time(),
        "qrcode": payload.get("qrcode", ""),
    })
    _write_napcat_state_file(payload)


def publish_onebot_probe_result(
    healthy: bool,
    *,
    detail: str = "",
    self_id: int | None = None,
) -> None:
    """发布 QQ 内核主动探测结果，区别于仅代表插件存活的 OneBot 心跳。"""
    now = time.time()
    payload = _read_napcat_state_file()
    payload.update(
        {
            "state": "connected" if healthy else "qq_offline",
            "detail": detail or (
                "QQ 登录与消息服务正常"
                if healthy
                else "QQ 消息服务不可用，NapCat 可能处于假在线状态"
            ),
            "updated_at": now,
            "probe_at": now,
            "probe_ok": bool(healthy),
            "probe_self_id": int(self_id) if self_id else None,
        }
    )
    _write_napcat_state_file(payload)


def publish_onebot_event_activity(*, is_message: bool = False) -> None:
    """记录 NapCat 最近一次真实 OneBot 负载。

    该时间戳包含心跳、消息和动作回包。它不是聊天审计日志，只用于识别
    “本地 WebSocket 未断、但 QQ/NapCat 已经不再投递事件”的假在线状态。
    """
    now = time.time()
    payload = _read_napcat_state_file()
    payload["last_event_at"] = now
    if is_message:
        payload["last_message_at"] = now
    # 保持连接态的更新时间新鲜，避免健康心跳被 _recent_napcat_state 丢弃。
    payload["updated_at"] = now
    _write_napcat_state_file(payload)


def _read_napcat_state_file() -> dict[str, Any]:
    try:
        payload = json.loads(NAPCAT_STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def _write_napcat_state_file(payload: dict[str, Any]) -> None:
    try:
        NAPCAT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = NAPCAT_STATE_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, NAPCAT_STATE_FILE)
    except OSError:
        return


def hidden_subprocess_startupinfo() -> Any | None:
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = 0
    return startupinfo


def run_hidden(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        startupinfo=hidden_subprocess_startupinfo(),
    )


def is_port_listening(port: int) -> bool:
    return _is_port_listening(tcp_rows(), port)


def has_established_port(port: int) -> bool:
    return _has_established_port(tcp_rows(), port)


def _is_port_listening(rows: list[dict[str, int | str | None]], port: int) -> bool:
    return any(row["local_port"] == port and row["state"] == "LISTENING" for row in rows)


def _has_established_port(rows: list[dict[str, int | str | None]], port: int) -> bool:
    return any(
        row["state"] == "ESTABLISHED" and (row["local_port"] == port or row["remote_port"] == port)
        for row in rows
    )


def tcp_rows() -> list[dict[str, int | str | None]]:
    if os.name != "nt":
        return []
    return _windows_tcp_rows()


class _MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("state", wintypes.DWORD),
        ("local_address", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("remote_address", wintypes.DWORD),
        ("remote_port", wintypes.DWORD),
        ("pid", wintypes.DWORD),
    ]


_TCP_STATES = {
    1: "CLOSED",
    2: "LISTENING",
    3: "SYN_SENT",
    4: "SYN_RECEIVED",
    5: "ESTABLISHED",
    6: "FIN_WAIT_1",
    7: "FIN_WAIT_2",
    8: "CLOSE_WAIT",
    9: "CLOSING",
    10: "LAST_ACK",
    11: "TIME_WAIT",
    12: "DELETE_TCB",
}


def _windows_tcp_rows() -> list[dict[str, int | str | None]]:
    get_table = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD

    size = wintypes.DWORD(0)
    # AF_INET + TCP_TABLE_OWNER_PID_ALL. The table can grow between the size
    # probe and read, so retry a bounded number of times.
    result = get_table(None, ctypes.byref(size), False, socket.AF_INET, 5, 0)
    if result not in {0, 122} or size.value <= 0:
        return []
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = get_table(buffer, ctypes.byref(size), False, socket.AF_INET, 5, 0)
        if result == 122:
            continue
        if result != 0:
            return []
        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        if count == 0:
            return []
        row_array = ctypes.cast(
            ctypes.byref(buffer, ctypes.sizeof(wintypes.DWORD)),
            ctypes.POINTER(_MibTcpRowOwnerPid * count),
        ).contents
        return [
            {
                "local_port": socket.ntohs(row.local_port & 0xFFFF),
                "remote_port": socket.ntohs(row.remote_port & 0xFFFF),
                "state": _TCP_STATES.get(int(row.state), str(int(row.state))),
                "pid": int(row.pid),
            }
            for row in row_array
        ]
    return []


def endpoint_port(endpoint: str) -> int | None:
    try:
        return int(endpoint.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _recent_napcat_state() -> dict[str, Any]:
    payload = _read_napcat_state_file()
    try:
        updated_at = float(payload.get("updated_at", 0))
    except (TypeError, ValueError):
        return {}
    if time.time() - updated_at > NAPCAT_STATE_MAX_AGE_SECONDS:
        return {}
    if not isinstance(payload.get("state"), str):
        return {}
    return payload


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def runtime_status(config: BotConfig) -> dict[str, Any]:
    """汇总桌宠与 WebUI 共用的只读运行状态。

    OneBot 是否在线以 TCP 已建立连接为准；NapCat 状态文件只提供扫码或
    重连过程的说明，避免历史状态把断线误显示为在线。
    """
    rows = tcp_rows()
    napcat_runtime = _recent_napcat_state()
    # The TCP connection is the live source of truth.  The state file is only
    # a short-lived diagnostic for login/connection explanations; it can be
    # stale when Atri has been running for longer than its freshness window.
    napcat_transport_connected = _has_established_port(rows, int(config.port))
    last_event_at = _float_or_zero(napcat_runtime.get("last_event_at"))
    # 新建连接在收到第一帧心跳前没有 last_event_at；此时以连接状态写入
    # 时间作为宽限期起点，避免“永远没有第一帧也始终显示正常”。
    activity_reference_at = last_event_at or _float_or_zero(napcat_runtime.get("updated_at"))
    event_age_seconds = (
        max(0.0, time.time() - activity_reference_at)
        if activity_reference_at
        else None
    )
    event_stale = bool(
        napcat_transport_connected
        and event_age_seconds is not None
        and event_age_seconds > ONEBOT_EVENT_STALE_SECONDS
    )
    probe_known = isinstance(napcat_runtime.get("probe_ok"), bool)
    probe_ok = bool(napcat_runtime.get("probe_ok")) if probe_known else False
    probe_at = _float_or_zero(napcat_runtime.get("probe_at"))
    probe_age_seconds = max(0.0, time.time() - probe_at) if probe_at else None
    probe_stale = bool(
        napcat_transport_connected
        and probe_known
        and probe_age_seconds is not None
        and probe_age_seconds > ONEBOT_PROBE_STALE_SECONDS
    )
    # 主动 get_status 探针一旦可用，就以 QQ 内核状态为准；心跳只作为
    # 旧版本/刚连接时的短暂兼容信号，不能覆盖明确的离线结果。
    napcat_connected = bool(
        napcat_transport_connected
        and not event_stale
        and (probe_ok and not probe_stale if probe_known else True)
    )
    if not napcat_transport_connected and napcat_runtime.get("state") == "connected":
        napcat_runtime = {}
    if probe_known and not probe_ok:
        napcat_state = str(napcat_runtime.get("state") or "qq_offline")
        napcat_detail = str(
            napcat_runtime.get("detail")
            or "QQ 消息服务不可用，NapCat 本地连接仍在但无法正常收发"
        )
    elif probe_stale:
        napcat_state = "probe_stale"
        napcat_detail = "QQ 状态主动探针已超时，不能确认当前消息链路可用"
    elif event_stale:
        napcat_state = "event_stale"
        napcat_detail = "NapCat 本地已连，但超过 90 秒未收到 OneBot 心跳；QQ/NapCat 事件流可能已掉线"
    elif napcat_connected:
        napcat_state = "connected"
        napcat_detail = (
            "QQ 登录与消息服务正常"
            if probe_known
            else "NapCat 已连接，正在确认 QQ 消息服务"
        )
    else:
        napcat_state = str(napcat_runtime.get("state") or "disconnected")
        napcat_detail = str(napcat_runtime.get("detail") or "")
    napcat_webui = napcat_webui_access()
    return {
        "atri": _is_port_listening(rows, int(config.port)),
        "napcat": napcat_connected,
        "napcat_transport": napcat_transport_connected,
        "napcat_state": napcat_state,
        "napcat_detail": napcat_detail,
        "napcat_last_event_at": last_event_at or None,
        "napcat_event_age_seconds": round(event_age_seconds, 1) if event_age_seconds is not None else None,
        "napcat_probe_ok": probe_ok if probe_known else None,
        "napcat_probe_at": probe_at or None,
        "napcat_probe_age_seconds": round(probe_age_seconds, 1) if probe_age_seconds is not None else None,
        "ollama": _is_port_listening(rows, 11434),
        "voice": _is_port_listening(rows, 8790),
        "webui": True,
        "bot_qq": config.bot_qq,
        "onebot": f"ws://{config.host}:{config.port}/onebot",
        "webui_url": f"http://{config.webui_host}:{config.webui_port}",
        "model": config.openai_model,
        "vision_model": config.toolbox_vision_model or config.openai_model,
        "base_url": config.openai_base_url,
        "reply_mode": config.reply_mode,
        "napcat_webui": napcat_webui,
    }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def restart_background_services() -> dict[str, Any]:
    launcher = TOOLS_DIR / "launch" / "qq_legacy" / "hidden_launcher.py"
    if not launcher.exists():
        return {"ok": False, "error": f"startup script not found: {launcher}"}
    pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if pythonw.exists():
        command = [str(pythonw), str(launcher)]
    elif python.exists():
        command = [str(python), str(launcher)]
    else:
        return {"ok": False, "error": f"python runtime not found under {PROJECT_ROOT / '.venv'}"}
    try:
        subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=hidden_subprocess_startupinfo(),
        )
        return {"ok": True, "message": "亚托莉启动命令已发出"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
