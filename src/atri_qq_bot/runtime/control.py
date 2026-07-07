from __future__ import annotations

import subprocess
from typing import Any

from ..config import BotConfig
from .paths import PROJECT_ROOT, TOOLS_DIR


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
    return any(row["local_port"] == port and row["state"] == "LISTENING" for row in tcp_rows())


def has_established_port(port: int) -> bool:
    return any(
        row["state"] == "ESTABLISHED" and (row["local_port"] == port or row["remote_port"] == port)
        for row in tcp_rows()
    )


def tcp_rows() -> list[dict[str, int | str | None]]:
    completed = run_hidden(["netstat.exe", "-ano", "-p", "TCP"])
    if completed.returncode != 0:
        return []
    output = completed.stdout.decode("utf-8", errors="replace")
    rows: list[dict[str, int | str | None]] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        rows.append(
            {
                "local_port": endpoint_port(parts[1]),
                "remote_port": endpoint_port(parts[2]),
                "state": parts[3].upper(),
                "pid": _int_or_none(parts[4]),
            }
        )
    return rows


def endpoint_port(endpoint: str) -> int | None:
    try:
        return int(endpoint.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def runtime_status(config: BotConfig) -> dict[str, Any]:
    return {
        "atri": is_port_listening(int(config.port)),
        "napcat": has_established_port(int(config.port)),
        "ollama": is_port_listening(11434),
        "webui": True,
        "bot_qq": config.bot_qq,
        "onebot": f"ws://{config.host}:{config.port}/onebot",
        "webui_url": f"http://{config.webui_host}:{config.webui_port}",
        "model": config.openai_model,
        "base_url": config.openai_base_url,
        "reply_mode": config.reply_mode,
    }


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
