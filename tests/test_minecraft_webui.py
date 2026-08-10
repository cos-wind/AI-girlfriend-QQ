from pathlib import Path

import pytest

from atri_webui import minecraft_admin
from atri_webui.minecraft_admin import (
    load_minecraft_bridge_config,
    minecraft_dashboard,
    save_minecraft_bridge_config,
    send_minecraft_command,
)
from atri_webui.page import render_index


def test_minecraft_config_is_saved_separately(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "minecraft_bridge.json"
    monkeypatch.setattr(
        minecraft_admin,
        "MINECRAFT_BRIDGE_CONFIG_PATH",
        config_path,
    )

    saved = save_minecraft_bridge_config(
        {"enabled": True, "bridge_url": "http://localhost:8792/"}
    )

    assert saved == {
        "enabled": True,
        "bridge_url": "http://localhost:8792",
    }
    assert load_minecraft_bridge_config() == saved
    assert config_path.is_file()


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8792",
        "http://example.com:8792",
        "http://127.0.0.1:8792/other",
        "http://127.0.0.1",
    ],
)
def test_minecraft_config_rejects_non_local_bridge_urls(
    tmp_path: Path, monkeypatch, url: str
) -> None:
    monkeypatch.setattr(
        minecraft_admin,
        "MINECRAFT_BRIDGE_CONFIG_PATH",
        tmp_path / "minecraft_bridge.json",
    )

    with pytest.raises(ValueError):
        save_minecraft_bridge_config({"enabled": True, "bridge_url": url})


def test_minecraft_dashboard_combines_health_and_telemetry(monkeypatch) -> None:
    monkeypatch.setattr(
        minecraft_admin,
        "load_minecraft_bridge_config",
        lambda: {"enabled": True, "bridge_url": "http://127.0.0.1:8792"},
    )

    def fake_request(base_url, method, path, payload=None):
        assert base_url == "http://127.0.0.1:8792"
        assert method == "GET"
        if path == "/v1/health":
            return {"ok": True, "minecraftConnected": True}
        return {
            "minecraftConnected": True,
            "telemetry": {"maids": [{"uuid": "maid-1", "mode": "FOLLOW"}]},
        }

    monkeypatch.setattr(minecraft_admin, "_request", fake_request)

    dashboard = minecraft_dashboard()

    assert dashboard["bridge"]["reachable"] is True
    assert dashboard["bridge"]["health"]["minecraftConnected"] is True
    assert dashboard["bridge"]["state"]["telemetry"]["maids"][0]["uuid"] == "maid-1"


def test_minecraft_commands_are_whitelisted_and_forwarded(monkeypatch) -> None:
    monkeypatch.setattr(
        minecraft_admin,
        "load_minecraft_bridge_config",
        lambda: {"enabled": True, "bridge_url": "http://127.0.0.1:8792"},
    )
    forwarded = {}

    def fake_request(base_url, method, path, payload=None):
        forwarded.update(
            base_url=base_url,
            method=method,
            path=path,
            payload=payload,
        )
        return {"accepted": True, "requestId": "request-1"}

    monkeypatch.setattr(minecraft_admin, "_request", fake_request)

    result = send_minecraft_command(
        {"command": "follow", "maidUuid": "maid-1"}
    )

    assert result["ok"] is True
    assert forwarded["path"] == "/v1/command"
    assert forwarded["payload"] == {
        "command": "follow",
        "maidUuid": "maid-1",
    }
    with pytest.raises(ValueError):
        send_minecraft_command({"command": "/op player"})


def test_minecraft_page_has_separate_config_and_test_controls() -> None:
    html = render_index()

    assert "onclick=\"showTab(event,'minecraft')\"" in html
    assert 'id="minecraft" class="panel"' in html
    assert 'id="minecraftEnabled"' in html
    assert 'id="minecraftBridgeUrl"' in html
    assert 'id="minecraftMaidSelect"' in html
    assert "sendMinecraftCommand('follow')" in html
    assert "sendMinecraftCommand('wait')" in html
    assert "sendMinecraftCommand('free')" in html
    assert "sendMinecraftCommand('stop')" in html
    assert "/api/minecraft/config" in html
    assert "/api/minecraft/command" in html


def test_webui_panels_are_not_nested_inside_voice_panel() -> None:
    html = render_index()
    voice_start = html.index('<div id="voice" class="panel">')
    stickers_start = html.index('<div id="stickers" class="panel">')
    voice_segment = html[voice_start:stickers_start]

    assert voice_segment.count('<div id="voice"') == 1
    assert voice_segment.count('<div id="voiceSpeechPanel"') == 1
    assert voice_segment.count('<div id="voiceMusicPanel"') == 1
    assert voice_segment.rstrip().endswith('</div>\n      </div>')
