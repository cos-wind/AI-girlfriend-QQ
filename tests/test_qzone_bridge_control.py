"""Bridge 手动启停与"不再随桌宠自动启动"的回归测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from atri_webui import qzone_bridge_control as control


@pytest.fixture(autouse=True)
def bridge_script(tmp_path, monkeypatch):
    directory = tmp_path / "tools" / "onebot-qzone"
    directory.mkdir(parents=True)
    script = directory / "start_bridge.ps1"
    script.write_text("# fixture only", encoding="utf-8")
    monkeypatch.setattr(control, "BRIDGE_DIR", directory)
    monkeypatch.setattr(control, "BRIDGE_SCRIPT", script)
    return tmp_path


def test_status_reports_not_running(monkeypatch) -> None:
    monkeypatch.setattr(control, "port_open", lambda *args, **kwargs: False)

    status = control.bridge_status()

    assert status["running"] is False
    assert status["port"] == 5700
    assert status["detail"] == "未运行"
    assert status["script_exists"] is True


def test_status_reports_online_when_bridge_is_logged_in(monkeypatch) -> None:
    monkeypatch.setattr(control, "port_open", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        control, "_bridge_status_payload", lambda: {"online": True, "good": True}
    )

    status = control.bridge_status()

    assert status["running"] is True
    assert status["detail"] == "运行中且已登录"


def test_start_bridge_does_not_spawn_when_port_already_listening(monkeypatch) -> None:
    monkeypatch.setattr(control, "port_open", lambda *args, **kwargs: True)
    monkeypatch.setattr(control, "_bridge_status_payload", lambda: {"online": True})
    spawned: list[object] = []
    monkeypatch.setattr(control.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    status = control.start_bridge()

    assert status["started"] is False
    assert spawned == []


def test_start_bridge_launches_script_and_waits_for_port(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_port_open(*args, **kwargs) -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    spawned: list[object] = []
    monkeypatch.setattr(control, "port_open", fake_port_open)
    monkeypatch.setattr(control, "_bridge_status_payload", lambda: {"online": True})
    monkeypatch.setattr(control.time, "sleep", lambda *_: None)
    monkeypatch.setattr(control.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    status = control.start_bridge()

    assert status["started"] is True
    assert len(spawned) == 1
    # 启动命令必须落到仓库内的 start_bridge.ps1，而不是任意路径。
    command = list(spawned[0][0])
    assert str(control.BRIDGE_SCRIPT) in command


def test_stop_bridge_reports_not_running(monkeypatch) -> None:
    monkeypatch.setattr(control, "port_open", lambda *args, **kwargs: False)

    status = control.stop_bridge()

    assert status["stopped"] is False
    assert status["message"] == "Bridge 当前未运行"


def test_stop_bridge_kills_listening_process_tree(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_port_open(*args, **kwargs) -> bool:
        calls["count"] += 1
        return calls["count"] == 1

    killed: list[int] = []
    monkeypatch.setattr(control, "port_open", fake_port_open)
    monkeypatch.setattr(control, "_bridge_status_payload", lambda: None)
    monkeypatch.setattr(control, "_pids_listening_on", lambda port: [4321])
    monkeypatch.setattr(
        control, "_kill_process_tree", lambda pid: killed.append(pid) or True
    )
    monkeypatch.setattr(control.time, "sleep", lambda *_: None)

    status = control.stop_bridge()

    assert killed == [4321]
    assert status["stopped"] is True
    assert status["message"] == "Bridge 已停止"


def _load_launcher_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "launch"
        / "qq_legacy"
        / "hidden_launcher.py"
    )
    spec = importlib.util.spec_from_file_location("atri_hidden_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_qzone_bridge_is_not_started_together_with_napcat(monkeypatch) -> None:
    launcher = _load_launcher_module()
    env = {"QZONE_BRIDGE_ENABLED": "true"}
    monkeypatch.setattr(
        launcher, "project_env_value", lambda name: env.get(name, "")
    )
    monkeypatch.setattr(launcher, "port_open", lambda *args, **kwargs: False)
    launched: list[object] = []
    monkeypatch.setattr(launcher, "popen_hidden", lambda *a, **k: launched.append(a))

    launcher.start_qzone_bridge_if_needed(wait_for_ready=False)

    assert launched == []


def test_qzone_bridge_autostarts_only_with_explicit_opt_in(monkeypatch, bridge_script) -> None:
    launcher = _load_launcher_module()
    monkeypatch.setattr(launcher, "PROJECT_DIR", bridge_script)
    env = {"QZONE_BRIDGE_ENABLED": "true", "QZONE_BRIDGE_AUTOSTART": "true"}
    monkeypatch.setattr(
        launcher, "project_env_value", lambda name: env.get(name, "")
    )
    monkeypatch.setattr(launcher, "port_open", lambda *args, **kwargs: False)
    launched: list[object] = []
    monkeypatch.setattr(launcher, "popen_hidden", lambda *a, **k: launched.append(a))

    launcher.start_qzone_bridge_if_needed(wait_for_ready=False)

    assert len(launched) == 1
