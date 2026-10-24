from __future__ import annotations

import asyncio
import csv
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from atri_qq_bot.runtime.paths import PROJECT_ROOT


def _tcp_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


async def gpt_sovits_runtime_ready() -> bool:
    """Non-mutating readiness probe used to size a conversational deadline."""
    return await asyncio.to_thread(_tcp_open, 9880)


async def ensure_gpt_sovits_runtime(*, timeout_seconds: float = 120.0) -> bool:
    """在全局推理租约内准备 GPT-SoVITS，并在推理前卸载 Ollama 模型。"""
    if await asyncio.to_thread(_tcp_open, 9880):
        # 热服务也可能遇到刚被聊天/视觉加载的 Ollama runner。每次 TTS
        # 推理前清掉它，避免 8GB 显存换页把数秒推理拖到二十秒以上。
        return await asyncio.to_thread(_stop_ollama_runtime_for_voice)
    if not await asyncio.to_thread(_stop_ollama_runtime_for_voice):
        return False
    if not await asyncio.to_thread(_launch_gpt_sovits):
        return False

    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(5.0, float(timeout_seconds))
    while loop.time() < deadline:
        if await asyncio.to_thread(_tcp_open, 9880):
            return True
        await asyncio.sleep(0.5)
    return False


async def stop_gpt_sovits_runtime() -> None:
    await asyncio.to_thread(_stop_gpt_sovits)


async def prepare_asr_runtime(*, requires_gpu: bool = True) -> bool:
    """按 ASR 的实际设备释放冲突资源。

    SenseVoice 当前默认运行在 CPU。CPU ASR 不会与 GPT-SoVITS 争用显存，
    因此不应为了每条语音输入把已经热好的 TTS 进程停掉；否则下一条语音
    回复必然重新经历 GPT-SoVITS 冷启动。只有 GPU ASR 才需要执行这套释放。
    """
    if not requires_gpu:
        return True
    await asyncio.to_thread(_stop_gpt_sovits)
    return await asyncio.to_thread(_stop_ollama_runtime_for_voice)


def _release_ollama_models_for_voice() -> bool:
    """只卸载 Ollama 当前驻留模型，保留轻量 HTTP 服务在线。

    GPT-SoVITS 可以与单个 4B Ollama 模型短暂共存，但合成时仍应独占主要
    显存，避免换页拖慢推理。保留 Ollama 服务本身可让后续视觉、记忆请求
    直接重新加载模型，也不会误伤其他项目的服务进程。
    """
    if not _tcp_open(11434):
        return True
    try:
        with urlopen("http://127.0.0.1:11434/api/ps", timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        models = {
            str(item.get("name") or item.get("model") or "").strip()
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        models.discard("")
        for model in models:
            request = Request(
                "http://127.0.0.1:11434/api/generate",
                data=json.dumps(
                    {
                        "model": model,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": 0,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10.0) as response:
                response.read()
        return _wait_for_ollama_models_to_unload()
    except (OSError, URLError, ValueError, TypeError, json.JSONDecodeError):
        # 无法确认显存/提交内存已释放时拒绝启动第二个重模型，宁可让本次
        # 合成给出可诊断错误，也不能把整台电脑拖入内存压力。
        return False


def _wait_for_ollama_models_to_unload() -> bool:
    for _ in range(20):
        try:
            with urlopen("http://127.0.0.1:11434/api/ps", timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if not payload.get("models"):
                return True
        except (OSError, URLError, ValueError, TypeError, json.JSONDecodeError):
            return False
        import time

        time.sleep(0.25)
    return False


def _stop_ollama_runtime_for_voice() -> bool:
    """卸载 Ollama 模型，但保留轻量 HTTP 服务。

    真正占显存和提交内存的是 runner；保留 ``ollama serve`` 可避免每次语音
    结束后重新创建服务进程，同时仍给 GPT-SoVITS 留出足够内存，保护系统声音。
    """
    if not _tcp_open(11434):
        return True
    return _release_ollama_models_for_voice()


def _ollama_listener_pid() -> int | None:
    completed = _run_capture(["netstat.exe", "-ano", "-p", "TCP"])
    for line in completed.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        if fields[3].upper() != "LISTENING":
            continue
        local_address = fields[1].rsplit(":", 1)
        if len(local_address) == 2 and local_address[1] == "11434":
            try:
                return int(fields[4])
            except ValueError:
                return None
    return None


def _windows_process_name(pid: int) -> str:
    output = _run_capture(
        ["tasklist.exe", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"]
    ).strip()
    if not output or output.startswith("INFO:"):
        return ""
    try:
        row = next(csv.reader([output]))
    except (csv.Error, StopIteration):
        return ""
    return str(row[0] if row else "").strip()


def _detached_flags() -> int:
    """让子进程脱离父进程 —— 服务重启/退出时不把引擎一起带走。"""
    return int(
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def _launch_gpt_sovits_via_python() -> bool:
    """用 `tools/voice/run-gpt-sovits.py` 拉起 9880（首选路径）。

    为什么优先它：`start-gpt-sovits.ps1` 走 `Start-Process`，而 PowerShell 5.1
    会把进程环境拷进大小写不敏感的字典 —— 当宿主 shell 同时导出了 `Path` 和
    `PATH`（Git Bash、部分启动器都会）时，`Start-Process` 直接抛
    「已添加项。字典中的关键字:"Path"所添加的关键字:"PATH"」，
    9880 永远起不来，8790 只会回一句「GPT-SoVITS 按需启动失败」，
    本文件同目录的 `run-gpt-sovits.py` 就是为此写的。
    """
    launcher = PROJECT_ROOT / "tools" / "voice" / "run-gpt-sovits.py"
    if not launcher.is_file():
        return False
    try:
        subprocess.Popen(
            [sys.executable, str(launcher)],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_detached_flags(),
        )
    except OSError:
        return False
    return True


def _launch_gpt_sovits() -> bool:
    marker = PROJECT_ROOT / "data" / "runtime" / "gpt-sovits" / ".dependencies-ready"
    if not marker.is_file():
        return False
    if _launch_gpt_sovits_via_python():
        return True
    script = PROJECT_ROOT / "tools" / "voice" / "start-gpt-sovits.ps1"
    if not script.is_file():
        return False
    try:
        subprocess.Popen(
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
                str(script),
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            startupinfo=_startupinfo(),
        )
    except OSError:
        return False
    return True


def _stop_gpt_sovits() -> None:
    if not _tcp_open(9880):
        return
    script = PROJECT_ROOT / "tools" / "voice" / "stop-gpt-sovits.ps1"
    if not script.is_file():
        return
    _run_hidden(
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
            str(script),
        ]
    )


def _run_hidden(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            startupinfo=_startupinfo(),
            check=False,
            timeout=10.0,
        )
    except subprocess.TimeoutExpired:
        # Never hold the shared inference lease indefinitely on cleanup.
        return


def _run_capture(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        startupinfo=_startupinfo(),
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return str(completed.stdout or "")


def _startupinfo() -> Any | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    info.wShowWindow = 0
    return info
