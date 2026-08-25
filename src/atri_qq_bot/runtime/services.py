from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .paths import PROJECT_ROOT, TOOLS_DIR


def _tcp_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _ollama_api_ready() -> bool:
    """Require the model registry API, not just Ollama's early-open TCP port."""
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return isinstance(payload.get("models"), list) and bool(payload["models"])
    except (OSError, ValueError, TypeError):
        return False


async def ensure_ollama_service(
    *,
    timeout_seconds: float = 20.0,
) -> bool:
    """确保本机 Ollama 服务可用，但不在 ATRI 启动时常驻加载模型。

    视觉、向量或记忆链路第一次真正需要本地模型时才调用这里。启动器自身有
    Windows 命名互斥锁，因此多个同时到达的请求不会重复启动 Ollama。
    这里只等待轻量的模型注册 API；具体模型仍由调用方按需加载，并通过
    ``keep_alive=0`` 在完成后释放，避免再次挤爆系统内存与 Windows Audio。
    """
    # 推理租约负责避免两个模型同时执行；Ollama 请求使用 keep_alive=0
    # 在完成后卸载模型。实机验证 4B 视觉模型与 GPT-SoVITS 短暂共存约占
    # 5.98/8 GB 显存，因此不能为一次视觉请求关闭热语音引擎，否则下一条
    # 语音需要重新加载 BERT/CNHuBERT，产生约一分钟冷启动。
    if await asyncio.to_thread(_ollama_api_ready):
        return True
    if not await asyncio.to_thread(_launch_runtime_mode, "ollama"):
        return False

    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(1.0, float(timeout_seconds))
    while loop.time() < deadline:
        if await asyncio.to_thread(_ollama_api_ready):
            return True
        await asyncio.sleep(0.25)
    return False


async def release_ollama_model(model: str, base_url: str) -> bool:
    """Unload one local chat model immediately after its response."""

    return await asyncio.to_thread(_release_ollama_model, model, base_url)


def _release_ollama_model(model: str, base_url: str) -> bool:
    name = str(model or "").strip()
    parsed = urlsplit(str(base_url or ""))
    if not name or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    native_root = urlunsplit((parsed.scheme or "http", parsed.netloc, "", "", ""))
    request = Request(
        f"{native_root}/api/generate",
        data=json.dumps(
            {"model": name, "prompt": "", "stream": False, "keep_alive": 0}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15.0) as response:
            response.read()
    except (OSError, ValueError):
        return False
    return True


def _launch_runtime_mode(mode: str) -> bool:
    # 启动器只负责拉起轻量运行时，不在这里加载具体模型；模型由真正需要它的
    # 视觉/embedding/语音调用按需加载，从而减少桌面端常驻内存和启动卡顿。
    launcher = TOOLS_DIR / "launch" / "qq_legacy" / "hidden_launcher.py"
    if not launcher.is_file():
        return False
    candidates = (
        PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    )
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        return False

    options: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        options["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = 0
            options["startupinfo"] = startupinfo
    try:
        subprocess.Popen([str(executable), str(launcher), mode], **options)
    except OSError:
        return False
    return True
