from __future__ import annotations

import http.server
import json
import threading
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from atri_webui import server as webui_server


def _request(port: int, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_service_switch_routes_serve_status_and_start(
    monkeypatch: Any,
) -> None:
    """语音服务开关与歌曲工作台入口必须真的挂在 WebUI 路由上。

    这里只替换底层函数，避免测试真的去拉起重服务或调用外部启动脚本。
    """

    monkeypatch.setattr(
        webui_server,
        "music_workbench_status",
        lambda: {
            "ok": True,
            "service": "music_workbench",
            "web": {"running": False, "port": 3000, "url": "http://127.0.0.1:3000/workbench"},
            "bridge": {"running": False, "port": 8793},
            "voice_service": {"running": False, "port": 8790, "ready": False},
            "detail": "工作台未运行",
        },
    )
    monkeypatch.setattr(
        webui_server,
        "start_music_workbench",
        lambda: {
            "ok": True,
            "service": "music_workbench",
            "web": {"running": True, "port": 3000, "url": "http://127.0.0.1:3000/workbench"},
            "bridge": {"running": True, "port": 8793},
            "voice_service": {"running": False, "port": 8790, "ready": False},
            "started": True,
            "message": "工作台已启动",
        },
    )
    monkeypatch.setattr(
        webui_server,
        "voice_service_status",
        lambda **kwargs: {
            "ok": True,
            "service": "voice_service",
            "running": False,
            "port": 8790,
            "detail": "未运行",
            "enabled": bool(kwargs.get("enabled", True)),
        },
    )
    monkeypatch.setattr(
        webui_server,
        "start_voice_service",
        lambda: {
            "ok": True,
            "service": "voice_service",
            "running": True,
            "port": 8790,
            "detail": "运行中",
            "started": True,
            "message": "语音服务已启动",
        },
    )
    monkeypatch.setattr(
        webui_server,
        "stop_voice_service",
        lambda: {
            "ok": True,
            "service": "voice_service",
            "running": False,
            "port": 8790,
            "detail": "未运行",
            "stopped": True,
            "message": "语音服务已停止",
        },
    )

    class Handler(webui_server.AtriWebUIHandler):
        webui_state = SimpleNamespace(
            config=SimpleNamespace(voice_asr_enabled=True, voice_tts_enabled=False)
        )

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port

        status, payload = _request(port, "/api/music/entry-status")
        assert status == 200
        assert payload["service"] == "music_workbench"
        assert payload["web"]["running"] is False

        status, payload = _request(port, "/api/music/entry-start", {})
        assert status == 200
        assert payload["started"] is True
        assert payload["message"] == "工作台已启动"

        status, payload = _request(port, "/api/voice/service")
        assert status == 200
        assert payload["service"] == "voice_service"
        assert payload["enabled"] is True

        status, payload = _request(port, "/api/voice/service", {"action": "start"})
        assert status == 200
        assert payload["message"] == "语音服务已启动"

        status, payload = _request(port, "/api/voice/service", {"action": "stop"})
        assert status == 200
        assert payload["stopped"] is True
        assert payload["message"] == "语音服务已停止"

        status, payload = _request(port, "/api/voice/service", {"action": "pause"})
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()


def test_voice_payload_route_survives_the_migration(monkeypatch: Any) -> None:
    """`/api/voice` 是「测试」页 TTS/ASR 面板的数据源。

    迁移时最容易在这里留下指向已删函数的悬空调用（`_music_bridge_request` 等），
    而这种错误只在真正请求时才炸 —— 所以这条用例必须走 HTTP，而不是只查源码。
    """

    monkeypatch.setattr(webui_server, "config_payload", lambda config: {})
    monkeypatch.setattr(webui_server, "voice_profiles_payload", lambda: [])
    monkeypatch.setattr(webui_server, "voice_candidates_payload", lambda: [])
    monkeypatch.setattr(webui_server, "asr_lexicon_text", lambda: "")
    monkeypatch.setattr(webui_server, "tts_pronunciation_text", lambda: "")
    monkeypatch.setattr(webui_server, "load_voice_behavior", lambda: {})

    def fake_run_coro(coro: Any) -> dict[str, Any]:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return {"ok": False, "error": "stub", "ready": False}

    monkeypatch.setattr(webui_server, "run_coro", fake_run_coro)

    class Handler(webui_server.AtriWebUIHandler):
        webui_state = SimpleNamespace(
            config=SimpleNamespace(voice_asr_enabled=False, voice_tts_enabled=False)
        )

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _request(server.server_port, "/api/voice")
        assert status == 200
        assert payload["ok"] is True
        assert payload["service"]["ok"] is False
        # 桥接探测已随工作流迁出：负载里不应再有 music_service。
        assert "music_service" not in payload
    finally:
        server.shutdown()
        server.server_close()


def test_migrated_music_routes_are_gone() -> None:
    """迁走的转发路由必须真的从路由表里消失，而不是只从页面上摘掉。"""

    class Handler(webui_server.AtriWebUIHandler):
        webui_state = SimpleNamespace(
            config=SimpleNamespace(voice_asr_enabled=False, voice_tts_enabled=False)
        )

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        for path in (
            "/api/music/projects",
            "/api/music/capabilities",
            "/api/music/sources",
            "/api/music/bridge",
            "/api/music/project",
            "/api/music/project/audio",
            "/api/music/project/waveform",
            "/api/music/project/log",
            "/api/voice/singing/jobs",
            "/api/voice/singing/job",
        ):
            status, payload = _request(port, path)
            assert status == 404, path
            assert payload["ok"] is False
        for path in (
            "/api/music/bridge",
            "/api/music/project/create",
            "/api/music/project/stems",
            "/api/music/project/stage",
            "/api/music/project/pipeline",
            "/api/music/project/confirm",
            "/api/music/project/rollback",
            "/api/music/project/reset",
            "/api/music/project/recover",
            "/api/music/project/segment",
            "/api/music/project/export",
            "/api/voice/singing/source",
            "/api/voice/singing/create",
            "/api/voice/singing/cancel",
        ):
            status, payload = _request(port, path, {})
            assert status == 404, path
            assert payload["ok"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_qq_song_catalog_reads_flat_music_directory(tmp_path, monkeypatch) -> None:
    from atri_qq_bot.music import song_catalog

    (tmp_path / "铁花飞.wav").write_bytes(b"prepared")
    monkeypatch.setattr(webui_server, "MUSIC_ROOT", tmp_path)
    monkeypatch.setattr(webui_server, "song_catalog", lambda: song_catalog(tmp_path))

    class Handler(webui_server.AtriWebUIHandler):
        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _request(server.server_port, "/api/music/songs")
        assert status == 200
        assert payload["root"] == str(tmp_path)
        assert payload["songs"] == [{"title": "铁花飞", "name": "铁花飞.wav", "size": 8}]
        assert not any(path.is_dir() for path in tmp_path.iterdir())
        for path, body in (
            ("/api/music/delivery-songs", None),
            ("/api/music/delivery-audio", None),
            ("/api/music/delivery-segment", {}),
        ):
            assert _request(server.server_port, path, body)[0] == 404
    finally:
        server.shutdown()
        server.server_close()
