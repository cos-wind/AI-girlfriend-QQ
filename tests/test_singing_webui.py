"""歌曲工作流迁出后，只保留本地成品歌曲管理。"""

from __future__ import annotations

from pathlib import Path

from atri_webui import server as webui_server
from atri_webui.page import render_index


def test_page_no_longer_contains_the_song_workflow() -> None:
    """工作台迁出后，本页面不得再出现歌曲工程的界面或转发接口。"""

    page = render_index()

    for gone in (
        "voiceMusicPanel",
        "musicStageSeparation",
        "musicStageInference",
        "musicStageMix",
        "showVoiceModule",
        "singingSourceFile",
        "musicProjectSelect",
        "/api/music/project",
        "/api/voice/singing",
        "127.0.0.1:8793",
    ):
        assert gone not in page, gone


def test_page_exposes_one_service_card_with_manual_switches() -> None:
    """语音服务、歌曲工作台与 QQ 空间 Bridge 共用一张卡片，只放开关。"""

    page = render_index()

    for value in (
        "本地服务（手动启动）",
        'id="voiceServiceStartButton"',
        "toggleVoiceService(this)",
        'id="musicWorkbenchStartButton"',
        "startMusicWorkbench(this)",
        "openMusicWorkbench()",
        'id="qzoneBridgeStartButton"',
        "startQZoneBridge(this)",
        'id="qzoneBridgeStopButton"',
        "stopQZoneBridge(this)",
        "/api/music/entry-status",
        "/api/music/entry-start",
        "/api/voice/service",
    ):
        assert value in page, value

    # 卡片里不再显示状态：状态统一在顶部「运行状态」。
    assert 'id="qzoneBridgeState"' not in page
    assert 'id="musicWorkbenchStatus"' not in page
    assert 'id="voiceServiceSwitchState"' not in page


def test_service_card_is_switches_only() -> None:
    """卡片只放开关：语音详细配置已撤下，改由 .env / data/webui 下的 JSON 维护。"""

    page = render_index()

    for gone in (
        '<details class="service-details">',
        'id="voiceAsrEnabled"',
        'id="voiceTtsEnabled"',
        'id="voiceProfileId"',
        'id="voiceAsrLexicon"',
        'id="voiceTtsPronunciations"',
        'id="voicePrivateAutoEnabled"',
        "saveVoice()",
        "previewVoice()",
        "voiceServiceStatus",
    ):
        assert gone not in page, gone


def test_qq_song_library_is_still_managed_here() -> None:
    """QQ 点歌素材库属于机器人自己的点歌能力，继续留在本面板。"""

    page = render_index()

    for value in (
        "QQ 点歌素材库",
        'id="qqMusicList"',
        "uploadQQSong()",
        "/api/music/songs",
    ):
        assert value in page, value
    for removed in ("segmentDeliveryMusic", "/api/music/delivery-", "deliveryMusicSource"):
        assert removed not in page


def test_service_and_entry_routes_are_registered() -> None:
    source = (
        Path(webui_server.__file__).resolve().parent
        / "server_parts"
        / "handler_core.py"
    ).read_text(encoding="utf-8")

    # 状态 + 启动各出现一次；旧的转发路由一个都不该留下。
    assert source.count('"/api/music/entry-status"') == 1
    assert source.count('"/api/music/entry-start"') == 1
    assert source.count('"/api/voice/service"') == 2
    assert '"/api/music/project' not in source
    assert '"/api/voice/singing' not in source
    assert '"/api/music/bridge"' not in source
