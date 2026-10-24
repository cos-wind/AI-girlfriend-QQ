from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from atri_webui import service_control


@pytest.fixture(autouse=True)
def default_voice_port(monkeypatch):
    monkeypatch.setattr(service_control, "local_voice_port", lambda default=8790: default)


def _load_launcher_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "launch"
        / "qq_legacy"
        / "hidden_launcher.py"
    )
    spec = importlib.util.spec_from_file_location("atri_service_control_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _patch_port_state(
    monkeypatch: pytest.MonkeyPatch, *, ports: set[int]
) -> None:
    """让端口探测只认给定的开放端口，并让等待立即成功。"""

    def fake_port_open(port: int, host: str = "127.0.0.1") -> bool:
        return int(port) in ports

    def fake_wait(port: int, wait_seconds: float) -> bool:
        ports.add(int(port))
        return True

    monkeypatch.setattr(service_control, "_port_open", fake_port_open)
    monkeypatch.setattr(service_control, "_wait_for_port", fake_wait)


def test_voice_service_status_reports_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_port_state(monkeypatch, ports={service_control.VOICE_SERVICE_PORT})
    monkeypatch.setattr(
        service_control,
        "_probe_json",
        lambda port, path: {"ok": True, "service": "atri-voice", "ready": False},
    )
    monkeypatch.setattr(
        service_control,
        "_launcher_command",
        lambda mode: ["pythonw.exe", "hidden_launcher.py", mode],
    )

    status = service_control.voice_service_status()

    assert status["running"] is True
    assert status["ready"] is False
    assert "预热" in status["detail"]


def test_voice_service_start_forces_start_and_uses_voice_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ports: set[int] = set()
    _patch_port_state(monkeypatch, ports=ports)
    monkeypatch.setattr(
        service_control,
        "_probe_json",
        lambda port, path: {"ok": True, "service": "atri-voice", "ready": False},
    )
    monkeypatch.setattr(
        service_control,
        "_launcher_command",
        lambda mode: ["pythonw.exe", "hidden_launcher.py", mode],
    )
    launched: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        service_control.subprocess,
        "Popen",
        lambda command, **kwargs: launched.append((command, kwargs)),
    )

    status = service_control.start_voice_service()

    assert len(launched) == 1
    command, options = launched[0]
    assert command[-1] == "voice-asr"
    assert options["env"]["ATRI_VOICE_FORCE_START"] == "1"  # type: ignore[index]
    assert status["started"] is True
    assert status["ok"] is True
    assert status["running"] is True


def test_voice_service_start_reports_missing_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_port_state(monkeypatch, ports=set())
    monkeypatch.setattr(service_control, "_launcher_command", lambda mode: None)

    with pytest.raises(FileNotFoundError):
        service_control.start_voice_service()


def test_voice_service_stop_kills_listener_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认 ATRI 身份后停止监听进程，随后端口不再监听。"""

    ports = {service_control.VOICE_SERVICE_PORT}
    _patch_port_state(monkeypatch, ports=ports)
    monkeypatch.setattr(service_control, "_probe_json", lambda port, path: {
        "ok": True, "service": "atri-voice", "ready": True,
    })
    pid_calls = {"count": 0}

    def fake_listening_pids(port: int) -> list[int]:
        pid_calls["count"] += 1
        return [4321] if pid_calls["count"] == 1 else []

    monkeypatch.setattr(service_control, "_listening_pids", fake_listening_pids)
    kill_commands: list[list[str]] = []

    def fake_run_hidden(command: list[str], **kwargs: object):
        kill_commands.append(command)
        ports.clear()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(service_control, "run_hidden", fake_run_hidden)

    status = service_control.stop_voice_service()

    assert kill_commands == [["taskkill.exe", "/PID", "4321", "/T", "/F"]]
    assert status["stopped"] is True
    assert status["running"] is False


def test_voice_service_stop_when_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_port_state(monkeypatch, ports=set())
    monkeypatch.setattr(service_control, "_probe_json", lambda port, path: None)
    monkeypatch.setattr(service_control, "_listening_pids", lambda port: [])

    status = service_control.stop_voice_service()

    assert status["stopped"] is False
    assert "未运行" in status["message"]


def test_page_signature_tracks_every_page_part(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """改 body/script 部分也要能触发页面刷新，否则界面改动必须重启进程。"""

    from atri_webui import server as webui_server

    monkeypatch.setattr(webui_server, "_PAGE_DIR", tmp_path)
    index = tmp_path / "index.py"
    index.write_text("# index\n", encoding="utf-8")
    first = webui_server._page_signature()
    assert first > 0

    time.sleep(0.01)
    (tmp_path / "script_part.py").write_text("# part\n", encoding="utf-8")

    assert webui_server._page_signature() > first


def test_launcher_force_start_bypasses_disabled_voice_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _load_launcher_module()
    monkeypatch.setattr(launcher, "project_env_value", lambda name: "")
    monkeypatch.setattr(launcher, "port_open", lambda *args, **kwargs: True)
    monkeypatch.setattr(launcher, "voice_ready", lambda: True)
    messages: list[str] = []
    monkeypatch.setattr(launcher, "log", messages.append)

    launcher.start_voice_if_needed(wait_for_ready=True)
    assert messages == []

    monkeypatch.setenv("ATRI_VOICE_FORCE_START", "1")
    launcher.start_voice_if_needed(wait_for_ready=True)

    assert launcher.voice_force_start_requested() is True
    assert any("already ready" in message for message in messages)


def test_music_workbench_status_splits_web_bridge_and_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """界面没起但桥接在跑时必须说清是哪一半，不能一律报「不可达」。"""

    _patch_port_state(monkeypatch, ports={service_control.MUSIC_BRIDGE_PORT})
    monkeypatch.setattr(service_control, "_probe_json", lambda port, path: None)

    status = service_control.music_workbench_status()

    assert status["bridge"]["running"] is True
    assert status["web"]["running"] is False
    assert status["voice_service"]["running"] is False
    assert "界面" in status["detail"]


def test_start_music_workbench_calls_the_other_projects_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """本项目不再拥有桥接进程：只调用 AI_music 自己的启动脚本。"""

    script = tmp_path / "scripts" / "start.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# launcher\n", encoding="utf-8")
    monkeypatch.setattr(service_control, "MUSIC_WORKBENCH_SCRIPT", script)
    monkeypatch.setattr(service_control.shutil, "which", lambda name: "pwsh.exe")
    _patch_port_state(monkeypatch, ports=set())
    monkeypatch.setattr(service_control, "_probe_json", lambda port, path: None)
    launched: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        service_control.subprocess,
        "Popen",
        lambda command, **kwargs: launched.append((command, kwargs)),
    )

    status = service_control.start_music_workbench()

    assert len(launched) == 1
    command, options = launched[0]
    assert command[0] == "pwsh.exe"
    assert str(script) in command
    assert options["cwd"] == str(service_control.MUSIC_WORKBENCH_ROOT)
    assert status["started"] is True
    assert status["message"].startswith("工作台已启动")


def test_start_music_workbench_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        service_control, "MUSIC_WORKBENCH_SCRIPT", tmp_path / "missing.ps1"
    )
    _patch_port_state(monkeypatch, ports=set())

    with pytest.raises(FileNotFoundError):
        service_control.start_music_workbench()


def test_music_launch_can_submit_without_waiting(monkeypatch, tmp_path):
    script = tmp_path / "start.ps1"
    script.write_text("# launcher\n", encoding="utf-8")
    monkeypatch.setattr(service_control, "MUSIC_WORKBENCH_SCRIPT", script)
    monkeypatch.setattr(service_control, "_port_open", lambda *_: False)
    monkeypatch.setattr(service_control.shutil, "which", lambda _: "pwsh.exe")
    monkeypatch.setattr(service_control.subprocess, "Popen", lambda *a, **kw: None)
    monkeypatch.setattr(service_control, "_wait_for_port", lambda *_: pytest.fail("must not wait twice"))
    assert service_control.start_music_workbench(wait_seconds=0)["started"]
