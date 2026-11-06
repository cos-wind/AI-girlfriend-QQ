from __future__ import annotations

import ctypes
import json
import os
import shutil
import socket
import subprocess
from atrium_runtime import is_packaged, worker_command, source_python
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from atri_shared.config import BotConfig
from .observability import napcat_webui_access
from atri_shared.runtime.paths import DATA_DIR, PROJECT_ROOT, TOOLS_DIR


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
    })
    # 登录二维码由 NapCat WebUI 管理；清理旧版本留下的二维码路径，避免
    # 桌面端或其他状态消费者误以为项目仍会打开本地二维码文件。
    payload.pop("qrcode", None)
    _write_napcat_state_file(payload)


def publish_onebot_probe_result(
    healthy: bool,
    *,
    detail: str = "",
    self_id: int | None = None,
    peer_uin: int | None = None,
) -> None:
    """发布 QQ 内核主动探测结果，区别于仅代表插件存活的 OneBot 心跳。

    ``peer_uin`` 是 NapCat 实际登录的 QQ 号（来自 ``get_login_info``）。它和
    ``BOT_QQ`` 不一致时，机器人会忽略所有事件（事件里的 ``self_id`` 不匹配），
    所以这里把它写进状态文件，供 WebUI 与日志把"没回复"的原因显示出来。
    """
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
    if peer_uin is not None:
        payload["peer_uin"] = int(peer_uin)
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


from atri_shared.runtime.process import (
    hidden_subprocess_startupinfo, run_hidden, is_port_listening, has_established_port,
    tcp_rows, _is_port_listening, _has_established_port, endpoint_port,
)


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

    OneBot 是否在线以 TCP 已建立连接为准；NapCat 状态文件只提供登录或
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
    # NapCat 登录号与 BOT_QQ 不一致时机器人不回复任何消息，这里暴露给 WebUI，
    # 让"发了消息没反应"在状态面板上就能看出原因。
    peer_uin = napcat_runtime.get("peer_uin")
    try:
        peer_uin = int(peer_uin) if peer_uin else None
    except (TypeError, ValueError):
        peer_uin = None
    account_mismatch = bool(peer_uin) and peer_uin != int(getattr(config, "bot_qq", 0) or 0)
    cognition_status = _cognition_status(config)
    ollama_running = _is_port_listening(rows, 11434)
    ollama_on_demand = bool(
        not ollama_running
        and _config_uses_local_ollama(config)
        and _ollama_executable_available()
    )
    vision_configured = bool(
        getattr(config, "toolbox_vision_enabled", False)
        and str(getattr(config, "toolbox_vision_model", "") or "").strip()
        and str(getattr(config, "toolbox_vision_base_url", "") or "").strip()
    )
    vision_primary_is_local = _is_local_ollama_url(
        str(getattr(config, "toolbox_vision_base_url", "") or "")
    )
    vision_available = bool(
        vision_configured
        and (
            not vision_primary_is_local
            or ollama_running
            or ollama_on_demand
        )
    )
    webui_url = f"http://{config.webui_host}:{config.webui_port}"
    webui_reachable = _is_port_listening(rows, int(config.webui_port))
    # MaiBot 是独立运行时，不属于当前 ATRI 进程。保留官方 WebUI 默认入口，
    # 让本机运维页可以明确显示“未启动”，避免把 ATRI WebUI 误认为 MaiBot。
    maibot_webui_url = "http://127.0.0.1:8001"
    return {
        "atri": _is_port_listening(rows, int(config.port)),
        "napcat": napcat_connected,
        "napcat_transport": napcat_transport_connected,
        "napcat_state": napcat_state,
        "napcat_detail": napcat_detail,
        "napcat_peer_uin": peer_uin,
        "napcat_account_mismatch": account_mismatch,
        "napcat_last_event_at": last_event_at or None,
        "napcat_event_age_seconds": round(event_age_seconds, 1) if event_age_seconds is not None else None,
        "napcat_probe_ok": probe_ok if probe_known else None,
        "napcat_probe_at": probe_at or None,
        "napcat_probe_age_seconds": round(probe_age_seconds, 1) if probe_age_seconds is not None else None,
        "ollama": ollama_running,
        "ollama_on_demand": ollama_on_demand,
        "voice": _is_port_listening(rows, 8790),
        "webui": True,
        "bot_qq": config.bot_qq,
        "onebot": f"ws://{config.host}:{config.port}/onebot",
        "webui_url": webui_url,
        "maibot_webui": {
            "url": maibot_webui_url,
            "reachable": _is_port_listening(rows, 8001),
        },
        "model": config.openai_model,
        "vision_model": config.toolbox_vision_model or config.openai_model,
        "vision_available": vision_available,
        "base_url": config.openai_base_url,
        "reply_mode": config.reply_mode,
        "cognition": cognition_status,
        "napcat_webui": napcat_webui,
    }


def _is_local_ollama_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return bool(
        "127.0.0.1:11434" in lowered
        or "localhost:11434" in lowered
        or "[::1]:11434" in lowered
    )


def _config_uses_local_ollama(config: BotConfig) -> bool:
    if _is_local_ollama_url(str(getattr(config, "toolbox_vision_base_url", "") or "")):
        return True
    fallback_url = str(
        getattr(config, "toolbox_vision_fallback_base_url", "") or ""
    ).strip()
    fallback_model = str(
        getattr(config, "toolbox_vision_fallback_model", "") or ""
    ).strip()
    if fallback_url:
        if _is_local_ollama_url(fallback_url):
            return True
    elif fallback_model and ":" in fallback_model:
        # 与 ToolAnalyzer 的兼容规则一致：未填写兜底地址的 Ollama 风格
        # 模型名默认指向本机 11434。
        return True
    return False


def _ollama_executable_available() -> bool:
    local = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Ollama"
        / "ollama.exe"
    )
    return local.is_file() or bool(shutil.which("ollama.exe"))


def _cognition_status(config: BotConfig) -> dict[str, Any]:
    if not bool(getattr(config, "cognition_shadow_enabled", False)):
        return {"enabled": False, "mode": "off", "available": False}
    try:
        from atri_bot.cognition import CognitionStateStore

        payload = CognitionStateStore(Path(config.cognition_state_path)).status()
        payload.update({"enabled": True, "mode": "shadow"})
        return payload
    except Exception as exc:
        return {
            "enabled": True,
            "mode": "shadow",
            "available": False,
            "error": str(exc)[:180],
        }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _launch_background_services(mode: str, success_message: str) -> dict[str, Any]:
    from atri_qq_bot.backend_isolation import ensure_legacy_available
    try:
        ensure_legacy_available()
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    launcher = TOOLS_DIR / "launch" / "qq_legacy" / "hidden_launcher.py"
    if not launcher.exists():
        return {"ok": False, "error": f"startup script not found: {launcher}"}
    env = None
    if is_packaged():
        command = worker_command("launcher", mode)
    else:
        command, env = source_python(str(launcher), mode)
    try:
        subprocess.Popen(
            command,
            env=env,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=hidden_subprocess_startupinfo(),
        )
        return {"ok": True, "message": success_message}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def start_background_services() -> dict[str, Any]:
    return _launch_background_services("core", "亚托莉启动命令已发出")


def restart_background_services() -> dict[str, Any]:
    return _launch_background_services("recover", "聊天重连命令已发出，QQ 登录保留")
