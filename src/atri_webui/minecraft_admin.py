from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from atri_qq_bot.runtime import PROJECT_ROOT


MINECRAFT_BRIDGE_CONFIG_PATH = PROJECT_ROOT / "data" / "minecraft_bridge.json"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8792"
ALLOWED_COMMANDS = frozenset({"follow", "wait", "free", "stop", "report"})


def _bridge_url(value: Any) -> str:
    raw = str(value or DEFAULT_BRIDGE_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("桥接地址只能是本机 HTTP 地址，例如 http://127.0.0.1:8792")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("桥接端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("桥接地址必须包含有效端口")
    return f"http://{parsed.hostname}:{port}"


def load_minecraft_bridge_config() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    try:
        loaded = json.loads(MINECRAFT_BRIDGE_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    except (FileNotFoundError, OSError, ValueError):
        pass
    try:
        bridge_url = _bridge_url(payload.get("bridge_url"))
    except ValueError:
        bridge_url = DEFAULT_BRIDGE_URL
    return {
        "enabled": bool(payload.get("enabled", False)),
        "bridge_url": bridge_url,
    }


def save_minecraft_bridge_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("配置必须是 JSON 对象")
    config = {
        "enabled": bool(payload.get("enabled", False)),
        "bridge_url": _bridge_url(payload.get("bridge_url")),
    }
    MINECRAFT_BRIDGE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MINECRAFT_BRIDGE_CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(MINECRAFT_BRIDGE_CONFIG_PATH)
    return config


def minecraft_dashboard() -> dict[str, Any]:
    config = load_minecraft_bridge_config()
    bridge: dict[str, Any] = {
        "reachable": False,
        "health": {},
        "state": {},
        "error": "",
    }
    try:
        bridge["health"] = _request(config["bridge_url"], "GET", "/v1/health")
        bridge["state"] = _request(config["bridge_url"], "GET", "/v1/state")
        bridge["reachable"] = True
    except (OSError, ValueError) as exc:
        bridge["error"] = str(exc)
    return {"ok": True, "config": config, "bridge": bridge}


def send_minecraft_command(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("命令必须是 JSON 对象")
    command = str(payload.get("command") or "").strip().lower()
    if command not in ALLOWED_COMMANDS:
        raise ValueError("只允许 follow、wait、free、stop、report")
    maid_uuid = payload.get("maidUuid")
    if maid_uuid is not None and not isinstance(maid_uuid, str):
        raise ValueError("maidUuid 必须是字符串")
    config = load_minecraft_bridge_config()
    if not config["enabled"]:
        raise ValueError("请先启用 Minecraft 女仆桥接")
    body: dict[str, Any] = {"command": command}
    if maid_uuid:
        body["maidUuid"] = maid_uuid
    result = _request(config["bridge_url"], "POST", "/v1/command", body)
    return {"ok": True, "result": result}


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{_bridge_url(base_url)}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=2.5) as response:
            raw = response.read(512 * 1024)
    except HTTPError as exc:
        detail = exc.read(64 * 1024).decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", detail)
        except ValueError:
            message = detail
        raise ValueError(f"Minecraft 桥接拒绝请求：{message}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise OSError(f"无法连接 Minecraft 桥接：{reason}") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Minecraft 桥接返回了无效 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("Minecraft 桥接响应必须是 JSON 对象")
    return result

