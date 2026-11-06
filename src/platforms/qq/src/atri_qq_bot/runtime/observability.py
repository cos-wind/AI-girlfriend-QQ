"""QQ 专用的 NapCat WebUI 配置读取与连接探测。

本模块只读取项目目录和 NapCat 的配置文件，不会改写 NapCat 配置、
不会发送 QQ 消息。这样 WebUI、桌宠和启动入口可以共享同一份运行状态，
同时避免把 Token 写入项目日志。
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import dotenv_values

from atri_shared.runtime.paths import ENV_PATH


def napcat_webui_access(config_path: Path | None = None) -> dict[str, Any]:
    """从 NapCat ``webui.json`` 读取本机访问地址，不在日志中记录 Token。"""

    config_path = config_path or _find_napcat_webui_config()
    if config_path is None:
        return {"configured": False, "reachable": False, "reason": "未找到 NapCat webui.json"}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"configured": False, "reachable": False, "reason": f"无法读取 NapCat WebUI 配置：{exc}"}
    host = str(payload.get("host") or "127.0.0.1")
    port = int(payload.get("port") or 6099)
    token = str(payload.get("token") or "")
    local_host = "127.0.0.1" if host in {"::", "0.0.0.0", "localhost"} else host
    url = f"http://{local_host}:{port}/webui"
    if token:
        url += f"?token={quote(token, safe='')}"
    return {
        "configured": not bool(payload.get("disableWebUI", False)),
        "reachable": _port_reachable(local_host, port),
        "host": host,
        "port": port,
        "url": url,
        "token_configured": bool(token),
        "config_path": str(config_path),
        "reason": "" if not bool(payload.get("disableWebUI", False)) else "NapCat WebUI 已在配置中禁用",
    }


def _find_napcat_webui_config() -> Path | None:
    from atrium_runtime import is_packaged, user_root
    values = dotenv_values(ENV_PATH)
    workdir = str(values.get("NAPCAT_WORKDIR") or os.getenv("NAPCAT_WORKDIR") or "").strip()
    if workdir:
        root = Path(workdir).expanduser()
        if not root.is_absolute():
            root = user_root() / root
        return root / "config" / "webui.json"
    configured = str(values.get("NAPCAT_DIR") or os.getenv("NAPCAT_DIR") or "").strip()
    configured_path = Path(configured).expanduser()
    if not configured_path.is_absolute():
        configured_path = user_root() / configured_path
    roots = [configured_path] if configured else []
    roots.append(user_root() / "components" / "napcat")
    if not is_packaged() and os.getenv("LOCALAPPDATA"):
        roots.append(Path(os.environ["LOCALAPPDATA"]) / "NapCat")
    for root in roots:
        direct = root / "config" / "webui.json"
        if direct.is_file():
            return direct
        if root.is_dir():
            candidates = list(root.glob("NapCat*.Shell/versions/*/resources/app/napcat/config/webui.json"))
            if candidates:
                return max(candidates, key=lambda item: item.stat().st_mtime)
    return None


def _port_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False
