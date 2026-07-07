from __future__ import annotations

import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from atri_qq_bot.config import BotConfig, load_config
from atri_qq_bot.runtime.control import restart_background_services, run_hidden, runtime_status, tcp_rows
from atri_qq_bot.runtime.paths import PROJECT_ROOT


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    detail: str = ""


@dataclass(frozen=True)
class DesktopPetStatus:
    atri: bool
    napcat: bool
    ollama: bool
    webui_url: str
    onebot: str
    model: str
    reply_mode: str
    bot_qq: int

    @classmethod
    def from_runtime(cls, payload: dict[str, Any]) -> "DesktopPetStatus":
        return cls(
            atri=bool(payload.get("atri")),
            napcat=bool(payload.get("napcat")),
            ollama=bool(payload.get("ollama")),
            webui_url=str(payload.get("webui_url") or ""),
            onebot=str(payload.get("onebot") or ""),
            model=str(payload.get("model") or ""),
            reply_mode=str(payload.get("reply_mode") or ""),
            bot_qq=int(payload.get("bot_qq") or 0),
        )


class DesktopPetController:
    def __init__(self, config_loader: Callable[[], BotConfig] = load_config) -> None:
        self._config_loader = config_loader

    def status(self) -> DesktopPetStatus:
        config = self._config_loader()
        return DesktopPetStatus.from_runtime(runtime_status(config))

    def start_services(self) -> ActionResult:
        return self.start_atri_with_qq()

    def start_atri_with_qq(self) -> ActionResult:
        result = restart_background_services()
        if result.get("ok"):
            return ActionResult(True, str(result.get("message") or "亚托莉启动命令已发出"))
        return ActionResult(False, "亚托莉启动命令发送失败", str(result.get("error") or "未知错误"))

    def stop_atri_service(self) -> ActionResult:
        config = self._config_loader()
        completed = _stop_python_listener(int(config.port))
        output = _completed_output(completed)
        if completed.returncode == 0:
            return ActionResult(True, output or "Atri 服务已停止或当前未运行")
        return ActionResult(False, output or "停止失败：端口可能被非 Atri 进程占用")

    def open_webui(self) -> ActionResult:
        status = self.status()
        if not status.webui_url:
            return ActionResult(False, "WebUI 地址为空")
        webbrowser.open(status.webui_url)
        return ActionResult(True, f"已打开 WebUI：{status.webui_url}")

    def open_project_folder(self) -> ActionResult:
        try:
            _open_path(PROJECT_ROOT)
        except Exception as exc:
            return ActionResult(False, "打开项目目录失败", str(exc))
        return ActionResult(True, f"已打开项目目录：{PROJECT_ROOT}")


def _completed_output(completed: subprocess.CompletedProcess[bytes]) -> str:
    output = (completed.stdout or b"") + (completed.stderr or b"")
    return output.decode("utf-8", errors="replace").strip()


def _completed_text(returncode: int, output: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=["taskkill.exe"], returncode=returncode, stdout=output.encode("utf-8"), stderr=b"")


def _open_path(path: Path) -> None:
    if hasattr(subprocess, "STARTUPINFO"):
        subprocess.Popen(["explorer.exe", str(path)])
        return
    webbrowser.open(path.as_uri())


def _stop_python_listener(port: int) -> subprocess.CompletedProcess[bytes]:
    pids = sorted(
        {
            int(row["pid"])
            for row in tcp_rows()
            if row["state"] == "LISTENING" and row["local_port"] == port and isinstance(row["pid"], int)
        }
    )
    if not pids:
        return _completed_text(0, "Atri service is not running.")

    outputs: list[str] = []
    failed = 0
    for pid in pids:
        completed = run_hidden(["taskkill.exe", "/PID", str(pid), "/F"])
        output = _completed_output(completed)
        if completed.returncode == 0:
            outputs.append(output or f"Stopped Atri python process: {pid}")
        else:
            failed += 1
            outputs.append(output or f"Could not stop PID {pid}.")
    return _completed_text(0 if failed == 0 else 2, "\n".join(outputs))
