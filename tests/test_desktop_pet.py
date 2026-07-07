from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from atri_qq_bot.config import BotConfig
from atri_qq_bot.runtime.control import has_established_port, is_port_listening, restart_background_services
from atri_qq_bot.runtime.paths import TOOLS_DIR
from atri_desktop.app import DesktopPetApp
from atri_desktop.assets import EXPRESSIONS, expression_for_status
from atri_desktop.controller import DesktopPetController, DesktopPetStatus


def _config(tmp_path: Path) -> BotConfig:
    return BotConfig(
        bot_qq=3380609082,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
    )


def test_desktop_pet_status_maps_runtime_payload() -> None:
    status = DesktopPetStatus.from_runtime(
        {
            "atri": True,
            "napcat": False,
            "ollama": True,
            "webui_url": "http://127.0.0.1:8787",
            "onebot": "ws://127.0.0.1:8765/onebot",
            "model": "gpt-4.1-mini",
            "reply_mode": "mention",
            "bot_qq": 3380609082,
        }
    )

    assert status.atri is True
    assert status.napcat is False
    assert status.webui_url == "http://127.0.0.1:8787"
    assert status.onebot.endswith("/onebot")
    assert status.bot_qq == 3380609082


def test_desktop_pet_opens_webui_from_runtime_status(monkeypatch, tmp_path) -> None:
    opened: list[str] = []

    monkeypatch.setattr(
        "atri_desktop.controller.runtime_status",
        lambda config: {
            "atri": True,
            "napcat": True,
            "ollama": False,
            "webui_url": "http://127.0.0.1:8787",
            "onebot": "ws://127.0.0.1:8765/onebot",
            "model": config.openai_model,
            "reply_mode": config.reply_mode,
            "bot_qq": config.bot_qq,
        },
    )
    monkeypatch.setattr("atri_desktop.controller.webbrowser.open", opened.append)

    controller = DesktopPetController(config_loader=lambda: _config(tmp_path))
    result = controller.open_webui()

    assert result.ok is True
    assert opened == ["http://127.0.0.1:8787"]


def test_desktop_pet_stop_reports_success(monkeypatch, tmp_path) -> None:
    completed = subprocess.CompletedProcess(
        args=["taskkill.exe"],
        returncode=0,
        stdout="Atri service is not running.".encode("utf-8"),
        stderr=b"",
    )
    monkeypatch.setattr("atri_desktop.controller._stop_python_listener", lambda port: completed)

    controller = DesktopPetController(config_loader=lambda: _config(tmp_path))
    result = controller.stop_atri_service()

    assert result.ok is True
    assert "not running" in result.message


def test_desktop_pet_default_start_launches_full_stack(monkeypatch, tmp_path) -> None:
    called: list[bool] = []

    def fake_restart() -> dict[str, object]:
        called.append(True)
        return {"ok": True, "message": "full stack start sent"}

    monkeypatch.setattr("atri_desktop.controller.restart_background_services", fake_restart)
    controller = DesktopPetController(config_loader=lambda: _config(tmp_path))

    result = controller.start_services()

    assert result.ok is True
    assert called == [True]


def test_runtime_start_uses_hidden_python_launcher(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakePopen:
        def __init__(self, command, **kwargs):
            calls.append((list(command), kwargs))

    monkeypatch.setattr("atri_qq_bot.runtime.control.subprocess.Popen", FakePopen)

    result = restart_background_services()

    assert result["ok"] is True
    assert calls
    command, kwargs = calls[0]
    assert command[-1].endswith("hidden_launcher.py")
    assert not any("powershell" in item.lower() or "cmd" in item.lower() or "wscript" in item.lower() for item in command)
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_runtime_status_uses_netstat_without_powershell(monkeypatch) -> None:
    calls: list[list[str]] = []
    output = """
  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       100
  TCP    127.0.0.1:8765         127.0.0.1:59351        ESTABLISHED     100
  TCP    127.0.0.1:59351        127.0.0.1:8765         ESTABLISHED     200
"""

    def fake_run_hidden(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=output.encode("utf-8"), stderr=b"")

    monkeypatch.setattr("atri_qq_bot.runtime.control.run_hidden", fake_run_hidden)

    assert is_port_listening(8765) is True
    assert has_established_port(8765) is True
    assert all(command[0] == "netstat.exe" for command in calls)


def test_desktop_pet_menu_keeps_single_start_entry(monkeypatch) -> None:
    labels: list[tuple[str, str]] = []

    class FakeMenu:
        def __init__(self, root, tearoff=False):
            self.root = root
            self.tearoff = tearoff

        def add_command(self, *, label, command):
            labels.append(("command", label))

        def add_separator(self):
            labels.append(("separator", ""))

        def add_cascade(self, *, label, menu):
            labels.append(("cascade", label))

        def add_checkbutton(self, *, label, variable, command):
            labels.append(("checkbutton", label))

    app = DesktopPetApp.__new__(DesktopPetApp)
    app.root = object()
    app.refresh_status = lambda: None
    app.start_services = lambda: None
    app.stop_atri = lambda: None
    app.open_webui = lambda: None
    app.open_project_folder = lambda: None
    app.show_status_detail = lambda: None
    app.request_close = lambda: None
    app._sync_bubble = lambda: None
    app._sync_topmost = lambda: None
    app.bubble_visible = object()
    app.topmost_var = object()

    monkeypatch.setattr("atri_desktop.app.tk.Menu", FakeMenu)
    app._build_menu()

    command_labels = [label for kind, label in labels if kind == "command"]
    assert command_labels.count("启动亚托莉") == 1
    assert not any("仅启动" in label or "完整" in label or "Python" in label for label in command_labels)


def test_desktop_pet_constructor_does_not_auto_start_services(monkeypatch) -> None:
    calls: list[str] = []

    class FakeRoot:
        def title(self, value: str) -> None:
            calls.append(f"title:{value}")

        def protocol(self, name: str, callback) -> None:
            calls.append(f"protocol:{name}")

        def overrideredirect(self, value: bool) -> None:
            calls.append(f"overrideredirect:{value}")

        def attributes(self, *args):
            calls.append("attributes:" + ",".join(str(item) for item in args))

        def configure(self, **kwargs) -> None:
            calls.append("configure")

    class FakeController:
        def start_services(self) -> None:
            calls.append("start_services")

    monkeypatch.setattr(DesktopPetApp, "_set_window_icon", lambda self: calls.append("icon"))
    monkeypatch.setattr(DesktopPetApp, "_apply_transparency", lambda self: calls.append("transparent"))
    monkeypatch.setattr(DesktopPetApp, "_build_ui", lambda self: calls.append("ui"))
    monkeypatch.setattr(DesktopPetApp, "_build_menu", lambda self: calls.append("menu"))
    monkeypatch.setattr(DesktopPetApp, "_place_initially", lambda self: calls.append("place"))
    monkeypatch.setattr(DesktopPetApp, "_schedule_queue_poll", lambda self: calls.append("poll"))
    monkeypatch.setattr(DesktopPetApp, "refresh_status", lambda self: calls.append("refresh_status"))
    monkeypatch.setattr("atri_desktop.app.tk.StringVar", lambda value=None: SimpleNamespace(value=value))
    monkeypatch.setattr("atri_desktop.app.tk.BooleanVar", lambda value=None: SimpleNamespace(value=value))

    DesktopPetApp(FakeRoot(), controller=FakeController())

    assert "refresh_status" in calls
    assert "start_services" not in calls


def test_desktop_pet_installer_only_writes_gui_shortcut() -> None:
    script = (TOOLS_DIR / "desktop_pet" / "install-desktop-pet.ps1").read_text(encoding="utf-8")

    assert "$shortcut.TargetPath = $GuiLauncher" in script
    assert "wscript.exe" not in script
    assert "start-desktop-pet.vbs" not in script


def test_desktop_pet_expression_assets_exist() -> None:
    assert len(EXPRESSIONS) == 8
    assert {item.key for item in EXPRESSIONS} >= {"idle", "happy", "idea", "cry"}
    for expression in EXPRESSIONS:
        assert expression.path.exists()
        assert expression.path.suffix == ".png"


def test_desktop_pet_expression_tracks_runtime_status() -> None:
    assert expression_for_status(False, False).key == "idle"
    assert expression_for_status(True, False).key == "idea"
    assert expression_for_status(True, True).key == "happy"


def test_desktop_pet_start_button_ignores_duplicate_clicks() -> None:
    calls: list[str] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> str:
            calls.append(f"after:{delay_ms}")
            return "startup"

    class FakeController:
        def start_services(self) -> ActionResult:
            calls.append("start_services")
            return ActionResult(True, "ok")

    app = DesktopPetApp.__new__(DesktopPetApp)
    app.root = FakeRoot()
    app.controller = FakeController()
    app.startup_guard_after_id = None
    app.closing = False
    app.busy = False
    app._run_background = lambda name, func: calls.append(name)
    app._say = lambda message: calls.append(message)

    app.start_services()
    app.start_services()

    assert calls == ["after:90000", "start", "亚托莉正在启动中，稍等一下。"]


def test_desktop_pet_close_hides_window_before_destroying() -> None:
    calls: list[tuple[str, object]] = []

    class FakeRoot:
        def after_cancel(self, after_id: str) -> None:
            calls.append(("after_cancel", after_id))

        def attributes(self, name: str, value: object) -> None:
            calls.append(("attributes", (name, value)))

        def overrideredirect(self, value: bool) -> None:
            calls.append(("overrideredirect", value))

        def lower(self) -> None:
            calls.append(("lower", None))

        def winfo_screenwidth(self) -> int:
            return 1920

        def winfo_screenheight(self) -> int:
            return 1080

        def geometry(self, spec: str) -> None:
            calls.append(("geometry", spec))

        def withdraw(self) -> None:
            calls.append(("withdraw", None))

        def update_idletasks(self) -> None:
            calls.append(("update_idletasks", None))

        def update(self) -> None:
            calls.append(("update", None))

        def destroy(self) -> None:
            calls.append(("destroy", None))

    class FakeMenu:
        def unpost(self) -> None:
            calls.append(("menu_unpost", None))

        def grab_release(self) -> None:
            calls.append(("menu_grab_release", None))

    class FakeLabel:
        def configure(self, **kwargs) -> None:
            calls.append(("pet_configure", kwargs))

        def pack_forget(self) -> None:
            calls.append(("bubble_pack_forget", None))

    app = DesktopPetApp.__new__(DesktopPetApp)
    app.root = FakeRoot()
    app.menu = FakeMenu()
    app.pet_label = FakeLabel()
    app.bubble = FakeLabel()
    app.closing = False
    app.destroyed = False
    app.busy = True
    app.queue_after_id = "queue"
    app.status_after_id = "status"
    app.action_after_id = "action"
    app._redraw_desktop_region = lambda rect: calls.append(("redraw", rect))
    app._desktop_rect = lambda: (0, 0, 1920, 1080)

    app.close()

    assert app.closing is True
    assert app.busy is False
    assert app.queue_after_id is None
    assert app.status_after_id is None
    assert app.action_after_id is None
    assert ("after_cancel", "queue") in calls
    assert ("after_cancel", "status") in calls
    assert ("after_cancel", "action") in calls
    assert ("pet_configure", {"image": "", "text": ""}) in calls
    assert ("bubble_pack_forget", None) in calls
    assert ("overrideredirect", False) in calls
    assert ("geometry", "1x1+11920+11080") in calls
    assert calls.index(("geometry", "1x1+11920+11080")) < calls.index(("withdraw", None))
    withdraw_index = calls.index(("withdraw", None))
    destroy_index = calls.index(("destroy", None))
    assert any(index > withdraw_index and call == ("update", None) for index, call in enumerate(calls))
    assert withdraw_index < destroy_index
    assert ("destroy", None) in calls
    assert ("redraw", (0, 0, 1920, 1080)) in calls

    destroy_count = calls.count(("destroy", None))
    app.destroy()

    assert calls.count(("destroy", None)) == destroy_count


def test_desktop_pet_menu_exit_closes_after_tk_menu_event_finishes() -> None:
    calls: list[tuple[str, object]] = []

    class FakeRoot:
        def after_idle(self, callback) -> str:
            calls.append(("after_idle", None))
            assert callback == app.close
            return "close"

    class FakeMenu:
        def unpost(self) -> None:
            calls.append(("menu_unpost", None))

        def grab_release(self) -> None:
            calls.append(("menu_grab_release", None))

    app = DesktopPetApp.__new__(DesktopPetApp)
    app.root = FakeRoot()
    app.menu = FakeMenu()
    app.closing = False

    app.request_close()

    assert calls == [("after_idle", None)]


def test_hidden_launcher_restarts_when_port_is_stale_python_listener(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    events: list[object] = []

    class FakePath:
        def __init__(self, value: str, exists: bool) -> None:
            self.value = value
            self._exists = exists

        def exists(self) -> bool:
            return self._exists

        def __str__(self) -> str:
            return self.value

    port_checks = iter([True, True, False, False, True])

    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: False)
    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: next(port_checks))
    monkeypatch.setattr(hidden_launcher, "listening_pids", lambda port: [41])
    monkeypatch.setattr(hidden_launcher, "process_name_by_pid", lambda pid: "pythonw.exe")
    monkeypatch.setattr(hidden_launcher, "taskkill_pid", lambda pid: events.append(("stop", pid)))
    monkeypatch.setattr(hidden_launcher, "time", SimpleNamespace(sleep=lambda seconds: events.append(("sleep", seconds))))
    monkeypatch.setattr(hidden_launcher, "log", lambda message: events.append(("log", message)))
    monkeypatch.setattr(hidden_launcher, "PROJECT_PYTHONW", FakePath(r"D:\Codex project\AI_ATRI\.venv\Scripts\pythonw.exe", True))
    monkeypatch.setattr(hidden_launcher, "PROJECT_PYTHON", FakePath(r"D:\Codex project\AI_ATRI\.venv\Scripts\python.exe", True))

    def fake_popen(args, **kwargs):
        events.append(("popen", [str(item) for item in args], kwargs))
        return object()

    monkeypatch.setattr(hidden_launcher, "popen_hidden", fake_popen)

    hidden_launcher.start_atri_if_needed()

    assert ("stop", 41) in events
    assert any(item[0] == "popen" and item[1][-2:] == ["-m", "atri_qq_bot"] for item in events if isinstance(item, tuple))


def test_hidden_launcher_detects_onebot_connection_without_webui(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    output = """
  TCP    127.0.0.1:8765         127.0.0.1:59351        ESTABLISHED     100
  TCP    127.0.0.1:59351        127.0.0.1:8765         ESTABLISHED     200
"""

    monkeypatch.setattr(hidden_launcher, "status_payload", lambda: {})
    monkeypatch.setattr(
        hidden_launcher,
        "run_hidden",
        lambda args: subprocess.CompletedProcess(args=args, returncode=0, stdout=output, stderr=""),
    )

    assert hidden_launcher.bot_connected() is True
