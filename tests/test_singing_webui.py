from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from atri_qq_bot.voice.client import SpeechServiceClient
from atri_webui import server as webui_server
from atri_webui import voice_admin
from atri_webui.page import render_index
from atri_webui.server import _singing_audio_path, _valid_singing_job_id


def test_save_singing_source_audio_uses_voice_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(voice_admin, "VOICE_CACHE_DIR", tmp_path)

    saved = voice_admin.save_singing_source_audio("../../guide.WAV", b"guide")

    assert saved.parent == (tmp_path / "singing-sources").resolve()
    assert saved.name.startswith("source-")
    assert saved.suffix == ".wav"
    assert saved.read_bytes() == b"guide"


def test_speech_client_sends_explicit_singing_reference(tmp_path: Path) -> None:
    client = SpeechServiceClient("http://127.0.0.1:8790")
    requests: list[tuple[str, dict[str, object]]] = []

    async def fake_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        requests.append((path, payload))
        return {"ok": True, "id": "a" * 32}

    client._post_json = fake_post  # type: ignore[method-assign]
    source = tmp_path / "source.wav"
    reference = tmp_path / "reference.wav"

    result = asyncio.run(
        client.create_singing_job(
            text="test song",
            source_audio_path=source,
            reference_audio_path=reference,
            profile="atri",
            preview_seconds=20,
            pitch_shift=1.5,
            prefer_original=False,
        )
    )

    assert result["id"] == "a" * 32
    assert requests == [
        (
            "/v1/singing/jobs",
            {
                "text": "test song",
                "source_audio_path": str(source.resolve()),
                "profile": "atri",
                "language": "auto",
                "preview_seconds": 20,
                "pitch_shift": 1.5,
                "prefer_original": False,
                "reference_audio_path": str(reference.resolve()),
            },
        )
    ]


def test_speech_client_lists_singing_jobs() -> None:
    client = SpeechServiceClient("http://127.0.0.1:8790")

    async def fake_get(path: str) -> dict[str, object]:
        assert path == "/v1/singing/jobs"
        return {"ok": True, "jobs": [{"id": "b" * 32}]}

    client._get_json = fake_get  # type: ignore[method-assign]

    assert asyncio.run(client.singing_jobs())["jobs"] == [{"id": "b" * 32}]


def test_webui_contains_three_stage_music_project_controls() -> None:
    page = render_index()

    for value in (
        "歌曲合成",
        "AI_music",
        'id="voiceMusicPanel" class="voice-module-panel"',
        "showVoiceModule('music')",
        'id="singingSourceFile"',
        'id="singingReferencePath"',
        'id="musicStageSeparation"',
        'id="musicStageInference"',
        'id="musicStageMix"',
        'id="musicVocalWave"',
        'id="musicConvertedWave"',
        'id="musicMixWave"',
        "createMusicProject()",
        "runMusicStage('separation')",
        "runMusicStage('inference')",
        "runMusicStage('mix')",
        "/api/music/project/create",
        "/api/music/project/stage",
    ):
        assert value in page


def test_music_panel_is_lazy_streaming_and_explains_parameters() -> None:
    page = render_index()

    for value in (
        'preload="none"',
        "loadMusicPreview(",
        "/api/music/project/audio",
        "/api/music/project/waveform",
        'id="musicSectionList"',
        'id="musicTerminal"',
        "简洁进度",
        "推荐值",
        "自动乐理分段",
        'id="musicSeparationModel"',
        'id="musicSelectionStart"',
        'id="musicRerunSegment"',
        'id="musicRevisionSelect"',
        "/api/music/project/segment",
        "/api/music/project/rollback",
        "/api/music/project/export",
        "QQmusic-MP3",
        "Pedalboard",
    ):
        assert value in page
    assert "http://127.0.0.1:8793' + path" not in page
    assert "await loadMusicProjects();\n}" not in page


def test_voice_panel_separates_speech_and_music_workspaces() -> None:
    page = render_index()

    assert 'id="voiceSpeechPanel" class="voice-module-panel active"' in page
    assert 'id="voiceMusicPanel" class="voice-module-panel"' in page
    assert "atri_voice_service · 127.0.0.1:8790" in page
    assert 'id="voicePreviewButton"' in page
    assert 'id="voicePreviewAudio" controls preload="metadata"' in page
    assert "button.disabled = true" in page
    assert "http://127.0.0.1:8793" in page


def test_music_bridge_request_uses_ai_music_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true, "jobs": []}'

    def fake_urlopen(request: object, timeout: float) -> Response:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["method"] = request.method  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(webui_server, "urlopen", fake_urlopen)

    assert webui_server._music_bridge_request("/api/jobs") == {
        "ok": True,
        "jobs": [],
    }
    assert captured == {
        "url": "http://127.0.0.1:8793/api/jobs",
        "method": "GET",
        "timeout": 8.0,
    }


def test_singing_request_validation(tmp_path: Path) -> None:
    audio = tmp_path / "guide.wav"
    audio.write_bytes(b"audio")

    assert _valid_singing_job_id("A" * 32) == "a" * 32
    assert _singing_audio_path(str(audio), "导唱") == audio.resolve()
    with pytest.raises(ValueError):
        _valid_singing_job_id("../not-a-job")
    with pytest.raises(ValueError):
        _singing_audio_path(str(tmp_path / "missing.wav"), "导唱")
    unsupported = tmp_path / "guide.txt"
    unsupported.write_text("no", encoding="utf-8")
    with pytest.raises(ValueError):
        _singing_audio_path(str(unsupported), "导唱")
