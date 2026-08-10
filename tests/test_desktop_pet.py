from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from atri_qq_bot.config import BotConfig
from atri_qq_bot.runtime.control import (
    has_established_port,
    is_port_listening,
    restart_background_services,
    runtime_status,
)
from atri_qq_bot.runtime.paths import TOOLS_DIR
from atri_desktop.app import COLOR_KEY_RGB, DesktopPetApp, _prepare_color_key_image, _scaled_pet_size
from atri_desktop.assets import EXPRESSIONS, expression_for_status
from atri_desktop.controller import DesktopPetController, DesktopPetStatus, _stop_python_listener


def _config(tmp_path: Path) -> BotConfig:
    return BotConfig(
        bot_qq=111111111,
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
            "vision_model": "qwen3-vl:4b-instruct",
            "reply_mode": "mention",
            "bot_qq": 111111111,
            "napcat_state": "login_required",
            "napcat_detail": "QQ 登录已失效，需要扫码登录",
        }
    )

    assert status.atri is True
    assert status.napcat is False
    assert status.webui_url == "http://127.0.0.1:8787"
    assert status.onebot.endswith("/onebot")
    assert status.bot_qq == 111111111
    assert status.vision_model == "qwen3-vl:4b-instruct"
    assert status.napcat_state == "login_required"
    assert "扫码" in status.napcat_detail


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


def test_desktop_pet_stop_kills_process_tree_and_waits_for_port_release(monkeypatch) -> None:
    rows = iter(
        [
            [{"state": "LISTENING", "local_port": 8765, "pid": 42}],
            [],
        ]
    )
    calls: list[list[str]] = []

    def fake_run_hidden(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("atri_desktop.controller.tcp_rows", lambda: next(rows))
    monkeypatch.setattr("atri_desktop.controller.run_hidden", fake_run_hidden)

    completed = _stop_python_listener(8765)

    assert completed.returncode == 0
    assert calls == [["taskkill.exe", "/PID", "42", "/T", "/F"]]
    assert "Atri 服务已停止" in completed.stdout.decode("utf-8")


def test_desktop_pet_stop_shows_immediate_feedback(monkeypatch) -> None:
    messages: list[str] = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            return None

    app = DesktopPetApp.__new__(DesktopPetApp)
    app.controller = SimpleNamespace(stop_atri_service=lambda: ActionResult(True, "ok"))
    app.closing = False
    app.busy = False
    app._say = messages.append
    app.results = SimpleNamespace(put=lambda item: None)

    monkeypatch.setattr("atri_desktop.app.threading.Thread", FakeThread)

    app.stop_atri()

    assert app.busy is True
    assert messages == ["正在停止 Atri..."]


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


def test_runtime_status_uses_native_tcp_table_without_subprocess(monkeypatch) -> None:
    rows = [
        {"local_port": 8765, "remote_port": 0, "state": "LISTENING", "pid": 100},
        {"local_port": 8765, "remote_port": 59351, "state": "ESTABLISHED", "pid": 100},
        {"local_port": 59351, "remote_port": 8765, "state": "ESTABLISHED", "pid": 200},
    ]
    subprocess_calls: list[list[str]] = []

    monkeypatch.setattr("atri_qq_bot.runtime.control._windows_tcp_rows", lambda: rows)
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control.run_hidden",
        lambda command: subprocess_calls.append(command),
    )

    assert is_port_listening(8765) is True
    assert has_established_port(8765) is True
    assert subprocess_calls == []


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
        with Image.open(expression.path) as image:
            assert image.size == (512, 512)
            assert image.mode == "RGBA"
            alpha = image.getchannel("A")
            assert alpha.getextrema() == (0, 255)
            assert alpha.getpixel((0, 0)) == 0
            assert alpha.getbbox() is not None


def test_desktop_pet_color_key_image_has_no_semitransparent_edge_pixels() -> None:
    source = Image.new("RGBA", (3, 1))
    source.putdata(
        [
            (0, 0, 0, 0),
            (200, 150, 100, 95),
            (200, 150, 100, 96),
        ]
    )

    result = _prepare_color_key_image(source)

    assert result.mode == "RGB"
    assert list(result.get_flattened_data()) == [COLOR_KEY_RGB, COLOR_KEY_RGB, (200, 150, 100)]


def test_desktop_pet_render_size_tracks_monitor_dpi() -> None:
    assert _scaled_pet_size(96) == 96
    assert _scaled_pet_size(144) == 144
    assert _scaled_pet_size(192) == 192


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


def test_hidden_launcher_keeps_listening_atri_while_napcat_connects(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    events: list[object] = []

    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: False)
    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: True)
    monkeypatch.setattr(
        hidden_launcher,
        "taskkill_pid",
        lambda pid: events.append(("stop", pid)),
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: events.append(("log", message)))

    def fake_popen(args, **kwargs):
        events.append(("popen", [str(item) for item in args], kwargs))
        return object()

    monkeypatch.setattr(hidden_launcher, "popen_hidden", fake_popen)

    hidden_launcher.start_atri_if_needed()

    assert not any(item[0] in {"stop", "popen"} for item in events)
    assert any(
        item[0] == "log" and "keeping it alive" in item[1]
        for item in events
    )


def test_hidden_launcher_starts_ollama_with_configured_models_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    ollama = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    ollama.parent.mkdir(parents=True)
    ollama.write_text("fake", encoding="utf-8")
    models_path = tmp_path / "models"
    events: list[tuple[str, object, object]] = []
    port_checks = iter([False, True])

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: next(port_checks))
    monkeypatch.setattr(hidden_launcher, "ollama_models_path", lambda: models_path)
    monkeypatch.setattr(hidden_launcher, "time", SimpleNamespace(sleep=lambda seconds: None))
    monkeypatch.setattr(hidden_launcher, "log", lambda message: events.append(("log", message, None)))

    def fake_popen(args, **kwargs):
        events.append(("popen", [str(item) for item in args], kwargs))
        return object()

    monkeypatch.setattr(hidden_launcher, "popen_hidden", fake_popen)

    hidden_launcher.start_ollama_if_needed()

    popen_events = [event for event in events if event[0] == "popen"]
    assert popen_events
    assert popen_events[0][1] == [str(ollama), "serve"]
    assert popen_events[0][2]["env"]["OLLAMA_MODELS"] == str(models_path)
    assert models_path.exists()


def test_hidden_launcher_starts_core_before_optional_services(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    events: list[object] = []
    monkeypatch.setattr(hidden_launcher, "acquire_single_instance_mutex", lambda name: True)
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)
    monkeypatch.setattr(
        hidden_launcher,
        "start_atri_if_needed",
        lambda *, wait_for_ready: events.append(("atri", wait_for_ready)),
    )
    monkeypatch.setattr(hidden_launcher, "start_napcat_if_needed", lambda: events.append("napcat"))
    monkeypatch.setattr(
        hidden_launcher,
        "start_gpt_sovits_if_needed",
        lambda: events.append("gpt-sovits"),
    )
    monkeypatch.setattr(
        hidden_launcher,
        "start_ollama_if_needed",
        lambda *, wait_for_ready: events.append(("ollama", wait_for_ready)),
    )
    monkeypatch.setattr(
        hidden_launcher,
        "start_voice_if_needed",
        lambda *, wait_for_ready: events.append(("voice", wait_for_ready)),
    )

    assert hidden_launcher.main() == 0
    assert events == [
        ("atri", False),
        "napcat",
        "gpt-sovits",
        ("ollama", False),
        ("voice", False),
    ]


def test_hidden_launcher_preflights_napcat_before_stopping_qq(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: False)
    monkeypatch.setattr(hidden_launcher, "required_napcat_files", lambda: None)
    monkeypatch.setattr(
        hidden_launcher,
        "taskkill",
        lambda name: events.append(("stop", name)),
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)

    hidden_launcher.start_napcat_if_needed()

    assert events == []


def test_hidden_launcher_cold_start_skips_unnecessary_process_stops(
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    required = tuple(Path(f"required-{index}") for index in range(5))
    events: list[object] = []
    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: False)
    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: False)
    monkeypatch.setattr(hidden_launcher, "required_napcat_files", lambda: required)
    monkeypatch.setattr(hidden_launcher, "bot_qq_uin", lambda: "100000001")
    monkeypatch.setattr(hidden_launcher, "process_rows", lambda: [])
    monkeypatch.setattr(
        hidden_launcher,
        "taskkill",
        lambda name: events.append(("stop", name)),
    )
    monkeypatch.setattr(
        hidden_launcher,
        "launch_napcat",
        lambda files: events.append(("launch", files)) or True,
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)

    hidden_launcher.start_napcat_if_needed()

    assert events == [("launch", required)]


def test_hidden_launcher_preserves_running_login_session(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    required = tuple(Path(f"required-{index}") for index in range(5))
    events: list[object] = []
    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: False)
    monkeypatch.setattr(hidden_launcher, "required_napcat_files", lambda: required)
    monkeypatch.setattr(hidden_launcher, "bot_qq_uin", lambda: "100000001")
    monkeypatch.setattr(
        hidden_launcher,
        "process_rows",
        lambda: [
            {"name": "QQ.exe", "pid": "10"},
            {"name": "NapCatWinBootMain.exe", "pid": "11"},
        ],
    )
    monkeypatch.setattr(hidden_launcher, "project_qq_pids", lambda: [10])
    monkeypatch.setattr(
        hidden_launcher,
        "taskkill",
        lambda name: events.append(("stop", name)),
    )
    monkeypatch.setattr(
        hidden_launcher,
        "launch_napcat",
        lambda files: events.append(("launch", files)) or True,
    )
    monkeypatch.setattr(
        hidden_launcher,
        "show_qq_window",
        lambda **kwargs: events.append(("show", kwargs)) or True,
    )
    monkeypatch.setattr(
        hidden_launcher,
        "fresh_napcat_qrcode",
        lambda napcat_dir: Path("qrcode.png"),
    )
    monkeypatch.setattr(
        hidden_launcher,
        "publish_napcat_state",
        lambda state, **kwargs: events.append(("state", state, kwargs)),
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: events.append(("log", message)))

    hidden_launcher.start_napcat_if_needed()

    assert not any(event[0] in {"stop", "launch"} for event in events)
    assert any(event[0] == "show" for event in events)
    assert any(event[:2] == ("state", "login_required") for event in events)


def test_hidden_launcher_detects_only_fresh_login_qrcode(tmp_path: Path, monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    qrcode = tmp_path / "cache" / "qrcode.png"
    qrcode.parent.mkdir()
    qrcode.write_bytes(b"png")
    monkeypatch.setattr(hidden_launcher.time, "time", lambda: 1_000.0)
    os.utime(qrcode, (950.0, 950.0))

    assert hidden_launcher.fresh_napcat_qrcode(tmp_path) == qrcode

    os.utime(qrcode, (100.0, 100.0))
    assert hidden_launcher.fresh_napcat_qrcode(tmp_path) is None


def test_runtime_status_surfaces_recent_napcat_login_state(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "napcat-state.json"
    state_path.write_text(
        '{"state":"login_required","detail":"QQ 登录已失效，需要扫码登录","updated_at":1000}',
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.runtime.control.NAPCAT_STATE_FILE", state_path)
    monkeypatch.setattr("atri_qq_bot.runtime.control.time.time", lambda: 1001.0)
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control.tcp_rows",
        lambda: [{"local_port": 8765, "remote_port": 0, "state": "LISTENING", "pid": 100}],
    )

    status = runtime_status(_config(tmp_path))

    assert status["napcat"] is False
    assert status["napcat_state"] == "login_required"
    assert "扫码" in status["napcat_detail"]


def test_runtime_status_does_not_keep_connected_state_without_tcp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "napcat-state.json"
    state_path.write_text(
        '{"state":"connected","detail":"NapCat 已连接","updated_at":1000,"last_event_at":2000}',
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.runtime.control.NAPCAT_STATE_FILE", state_path)
    monkeypatch.setattr("atri_qq_bot.runtime.control.time.time", lambda: 1001.0)
    monkeypatch.setattr("atri_qq_bot.runtime.control.tcp_rows", lambda: [])

    status = runtime_status(_config(tmp_path))

    assert status["napcat"] is False
    assert status["napcat_state"] == "disconnected"
    assert status["napcat_detail"] == ""


def test_runtime_status_prefers_live_onebot_connection_over_stale_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "napcat-state.json"
    state_path.write_text(
        '{"state":"connected","detail":"NapCat 已连接","updated_at":1000}',
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.runtime.control.NAPCAT_STATE_FILE", state_path)
    monkeypatch.setattr("atri_qq_bot.runtime.control.time.time", lambda: 2000.0)
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control.tcp_rows",
        lambda: [
            {"local_port": 8765, "remote_port": 53698, "state": "ESTABLISHED", "pid": 100},
            {"local_port": 8765, "remote_port": 0, "state": "LISTENING", "pid": 100},
        ],
    )

    status = runtime_status(_config(tmp_path))

    assert status["napcat"] is True
    assert status["napcat_state"] == "connected"


def test_runtime_status_marks_silent_onebot_transport_as_event_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "napcat-state.json"
    state_path.write_text(
        '{"state":"connected","detail":"NapCat 已连接","updated_at":1000,"last_event_at":800}',
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.runtime.control.NAPCAT_STATE_FILE", state_path)
    monkeypatch.setattr("atri_qq_bot.runtime.control.time.time", lambda: 1000.0)
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control.tcp_rows",
        lambda: [
            {"local_port": 8765, "remote_port": 50001, "state": "ESTABLISHED", "pid": 100},
            {"local_port": 8765, "remote_port": 0, "state": "LISTENING", "pid": 100},
        ],
    )

    status = runtime_status(_config(tmp_path))

    assert status["napcat"] is False
    assert status["napcat_transport"] is True
    assert status["napcat_state"] == "event_stale"
    assert "心跳" in status["napcat_detail"]


def test_runtime_status_does_not_trust_heartbeat_after_qq_probe_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "napcat-state.json"
    state_path.write_text(
        '{"state":"qq_offline","detail":"网络连接异常!","updated_at":1000,'
        '"last_event_at":1000,"probe_at":1000,"probe_ok":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.runtime.control.NAPCAT_STATE_FILE", state_path)
    monkeypatch.setattr("atri_qq_bot.runtime.control.time.time", lambda: 1001.0)
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control.tcp_rows",
        lambda: [
            {"local_port": 8765, "remote_port": 50001, "state": "ESTABLISHED", "pid": 100},
            {"local_port": 8765, "remote_port": 0, "state": "LISTENING", "pid": 100},
        ],
    )

    status = runtime_status(_config(tmp_path))

    assert status["napcat"] is False
    assert status["napcat_transport"] is True
    assert status["napcat_probe_ok"] is False
    assert status["napcat_state"] == "qq_offline"
    assert status["napcat_detail"] == "网络连接异常!"


def test_desktop_pet_status_message_keeps_bubble_compact() -> None:
    from atri_desktop.app import status_bubble_message

    status = DesktopPetStatus.from_runtime(
        {
            "atri": True,
            "napcat": True,
            "model": "deepseek-v4-flash",
            "napcat_state": "connected",
        }
    )

    message = status_bubble_message(status)
    assert message in {"后台连接正常。", "高性能运行中。", "Atri 和 NapCat 都在线。"}
    assert "deepseek-v4-flash" not in message


def test_hidden_launcher_builds_no_console_napcat_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    source = tmp_path / "NapCatWinBootMain.exe"
    cached = tmp_path / "runtime" / "NapCatWinBootMain.exe"
    payload = bytearray(512)
    payload[:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\0\0"
    optional_header = 0x80 + 24
    payload[optional_header : optional_header + 2] = (0x20B).to_bytes(2, "little")
    payload[optional_header + 68 : optional_header + 70] = (3).to_bytes(2, "little")
    logging_offset = 320
    logging_switch = "--enable-logging".encode("utf-16-le")
    payload[logging_offset : logging_offset + len(logging_switch)] = logging_switch
    source.write_bytes(payload)
    monkeypatch.setattr(hidden_launcher, "NAPCAT_LAUNCHER_CACHE", cached)

    result = hidden_launcher.prepare_napcat_no_console_launcher(source)
    patched = result.read_bytes()

    assert result == cached
    assert source.read_bytes() == payload
    assert int.from_bytes(
        patched[optional_header + 68 : optional_header + 70],
        "little",
    ) == 2
    assert "--enable-logging".encode("utf-16-le") not in patched


def test_hidden_launcher_builds_isolated_project_qq_arguments(tmp_path: Path) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    qq_exe = tmp_path / "compatible" / "QQ.exe"
    profile = tmp_path / "atri-profile"

    arguments = hidden_launcher.isolated_qq_arguments(
        qq_exe,
        "100000001",
        profile,
    )

    assert arguments[0] == str(qq_exe)
    assert arguments[1:4] == ["--enable-logging", "-q", "100000001"]
    assert arguments[4] == f"--user-data-dir={profile}"


def test_hidden_launcher_rejects_desktop_qq_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    appdata = tmp_path / "AppData" / "Roaming"
    qq_exe = tmp_path / "compatible" / "QQ.exe"
    qq_exe.parent.mkdir(parents=True)
    qq_exe.write_bytes(b"MZ")
    monkeypatch.setenv("APPDATA", str(appdata))

    try:
        hidden_launcher.validate_qq_isolation(qq_exe, appdata / "QQ")
    except ValueError as exc:
        assert "desktop QQ profile" in str(exc)
    else:
        raise AssertionError("desktop QQ profile must be rejected")


def test_hidden_launcher_can_start_atri_without_waiting(monkeypatch) -> None:
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

    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: False)
    monkeypatch.setattr(
        hidden_launcher,
        "PROJECT_PYTHONW",
        FakePath("pythonw.exe", True),
    )
    monkeypatch.setattr(hidden_launcher, "PROJECT_PYTHON", FakePath("python.exe", True))
    monkeypatch.setattr(
        hidden_launcher,
        "popen_hidden",
        lambda args, **kwargs: events.append(("launch", args)),
    )
    monkeypatch.setattr(
        hidden_launcher.time,
        "sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)

    hidden_launcher.start_atri_if_needed(wait_for_ready=False)

    assert [event[0] for event in events] == ["launch"]


def test_hidden_launcher_loads_no_window_compat_for_voice_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    runtime_root = tmp_path / "voice-runtime"
    pythonw = runtime_root / ".venv" / "Scripts" / "pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.write_bytes(b"")
    launches: list[dict[str, object]] = []

    monkeypatch.setattr(hidden_launcher, "voice_enabled", lambda: True)
    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: False)
    monkeypatch.setattr(
        hidden_launcher,
        "voice_runtime_candidates",
        lambda: (runtime_root,),
    )
    monkeypatch.setattr(
        hidden_launcher,
        "voice_models_root",
        lambda: tmp_path / "models",
    )
    monkeypatch.setattr(
        hidden_launcher,
        "popen_hidden",
        lambda args, **kwargs: launches.append({"args": args, **kwargs}),
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)

    hidden_launcher.start_voice_if_needed(wait_for_ready=False)

    assert len(launches) == 1
    environment = launches[0]["env"]
    compat_path = str(hidden_launcher.PROJECT_DIR / "tools" / "voice" / "compat")
    assert compat_path in environment["PYTHONPATH"].split(os.pathsep)


def test_hidden_launcher_hides_qq_while_waiting_for_quick_login(
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    events: list[str] = []
    monkeypatch.setattr(
        hidden_launcher,
        "hide_qq_windows",
        lambda: events.append("hide") or True,
    )
    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: True)
    monkeypatch.setattr(hidden_launcher.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)

    assert hidden_launcher.wait_for_connection(
        1,
        keep_qq_hidden=True,
    ) is True
    assert events == ["hide", "hide"]


def test_hidden_launcher_does_not_show_qq_when_already_connected(
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    events: list[str] = []
    monkeypatch.setattr(hidden_launcher, "port_open", lambda port: True)
    monkeypatch.setattr(hidden_launcher, "bot_connected", lambda: True)
    monkeypatch.setattr(
        hidden_launcher,
        "show_qq_window",
        lambda **kwargs: events.append("show") or True,
    )
    monkeypatch.setattr(hidden_launcher, "log", lambda message: None)

    hidden_launcher.start_napcat_if_needed()

    assert events == []


def test_hidden_launcher_uses_no_console_process_flags(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(hidden_launcher.subprocess, "Popen", fake_popen)

    hidden_launcher.popen_hidden(["example.exe", "serve"])

    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert int(captured["creationflags"]) & getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )


def test_hidden_launcher_detects_onebot_connection_without_webui(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    monkeypatch.setattr(hidden_launcher, "status_payload", lambda: {})
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control.has_established_port",
        lambda port: port == hidden_launcher.BOT_PORT,
    )

    assert hidden_launcher.bot_connected() is True


def test_hidden_launcher_trusts_failed_active_probe_over_local_tcp(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    monkeypatch.setattr(
        hidden_launcher,
        "status_payload",
        lambda: {"napcat": False, "napcat_state": "qq_offline"},
    )
    monkeypatch.setattr(hidden_launcher, "onebot_connection_established", lambda: True)

    assert hidden_launcher.bot_connected() is False


def test_hidden_launcher_reads_bot_qq_from_project_config(monkeypatch) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    monkeypatch.setattr(
        hidden_launcher,
        "project_env_value",
        lambda name: "100000001" if name == "BOT_QQ" else "",
    )
    monkeypatch.delenv("BOT_QQ", raising=False)

    assert hidden_launcher.bot_qq_uin() == "100000001"


def test_hidden_launcher_discovers_versioned_napcat_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools.launch.qq_legacy import hidden_launcher

    runtime = (
        tmp_path
        / "NapCat.44498.Shell"
        / "versions"
        / "9.9.26-44498"
        / "resources"
        / "app"
        / "napcat"
    )
    runtime.mkdir(parents=True)
    for name in (
        "NapCatWinBootMain.exe",
        "NapCatWinBootHook.dll",
        "napcat.mjs",
        "qqnt.json",
    ):
        (runtime / name).write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(hidden_launcher, "project_env_value", lambda name: "")
    monkeypatch.delenv("NAPCAT_DIR", raising=False)

    assert hidden_launcher.find_napcat_dir((tmp_path,)) == runtime
