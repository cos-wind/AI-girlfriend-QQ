from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from atri_voice_service.app import SpeechApplication
from atri_voice_service.config import VoiceServiceConfig
from atri_voice_service.providers import IsolatedSenseVoiceProvider, ProviderError
from atri_voice_service.resources import InferenceResourceManager
from atri_voice_service.asr_lexicon import AsrLexicon, save_lexicon
from atri_voice_service.providers import SenseVoiceProvider
from atri_voice_service.audio_processing import PreparedAudio
from atri_voice_service.server import VoiceHttpServer
from atri_voice_service.speech_pipeline import (
    ConversationSpeechPipeline, QualityCheckedSynthesis, SpeechSynthesisOptions,
)
from atri_qq_bot.voice import SynthesisResult, VoiceRequest


@pytest.fixture
def worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exercise the actual child-process protocol without loading a second model."""
    script = tmp_path / "worker.py"
    script.write_text(
        "import json,sys,os,time\n"
        "from pathlib import Path\n"
        "for line in sys.stdin:\n"
        "    request_path, result_path = json.loads(line)\n"
        "    request = json.loads(Path(request_path).read_text(encoding='utf-8'))\n"
        "    if request['language'] == 'crash': sys.exit(3)\n"
        "    if request['language'] == 'wait':\n"
        "        Path(__file__).with_suffix('.pid').write_text(str(os.getpid()))\n"
        "        time.sleep(30)\n"
        "    result = {'ok': True, 'text': str(os.getpid()), 'language': 'zh', "
        "'timings': {'load_seconds': 0.0, 'preprocess_seconds': 0.01, 'inference_seconds': 0.02}}\n"
        "    temp = Path(result_path + '.tmp')\n"
        "    temp.write_text(json.dumps(result), encoding='utf-8')\n"
        "    temp.replace(result_path)\n",
        encoding="utf-8",
    )
    children = []

    def start(self):
        child = subprocess.Popen(
            [sys.executable, str(script)], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8",
        )
        children.append(child)
        return child

    monkeypatch.setattr(IsolatedSenseVoiceProvider, "_start_worker", start, raising=False)
    yield tmp_path, children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def make_app(tmp_path: Path):
    config = VoiceServiceConfig(
        asr_device="cpu", cache_dir=tmp_path / "cache",
        asr_lexicon_path=tmp_path / "hotwords.json",
    )
    app = SpeechApplication.__new__(SpeechApplication)
    app.config = config
    app.asr = IsolatedSenseVoiceProvider(config)
    app.resources = InferenceResourceManager()
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"fixture")
    return app, audio


def test_manual_residency_survives_idle_and_releases_only_asr(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)
    app.asr.config = replace(app.config, asr_worker_idle_seconds=0.03)
    tts = object()
    app.tts = tts

    async def scenario():
        loaded = await app.control_asr("start")
        assert loaded["asr"]["loaded"] is True
        assert loaded["asr"]["keep_loaded"] is True
        await asyncio.sleep(0.12)
        result = await app.transcribe({"audio_path": str(audio)})
        repeated = await app.transcribe({"audio_path": str(audio)})
        assert result["text"] == repeated["text"]
        assert len(children) == 1
        await asyncio.sleep(0.12)
        assert children[0].poll() is None
        stopped = await app.control_asr("stop")
        assert stopped["asr"]["loaded"] is False
        assert stopped["asr"]["keep_loaded"] is False
        assert children[0].poll() is not None
        assert app.tts is tts
        # Closing releases memory; existing microphone requests still work.
        await app.transcribe({"audio_path": str(audio)})
        assert len(children) == 2
        await app.asr.unload()

    asyncio.run(scenario())


def test_manual_residency_rejects_gpu_without_starting_worker(worker):
    tmp_path, children = worker
    app, _ = make_app(tmp_path)
    app.asr.config = replace(app.config, asr_device="cuda:0")

    async def scenario():
        with pytest.raises(ProviderError, match="CPU"):
            await app.control_asr("start")
        assert children == []
        assert app.asr.status()["keep_loaded"] is False

    asyncio.run(scenario())


def test_worker_load_command_warms_model_without_transcribing(tmp_path):
    from atri_voice_service.asr_worker import _job
    calls = []
    class Provider:
        async def warmup(self):
            calls.append("load")
        async def transcribe(self, *args):
            pytest.fail("Model loading must not require a recording")
    request = tmp_path / "load.json"
    result = tmp_path / "result.json"
    request.write_text('{"action":"load"}', encoding="utf-8")
    assert asyncio.run(_job(Provider(), request, result))
    assert calls == ["load"]
    assert json.loads(result.read_text(encoding="utf-8"))["ok"]


def test_http_model_control_and_health_use_same_worker(worker, monkeypatch):
    import threading
    from urllib.request import Request, urlopen
    from atri_voice_service import server as server_module

    tmp_path, children = worker
    app, _ = make_app(tmp_path)
    app.health = lambda: {"ok": True, "service": "atri-voice", "asr": app.asr.status()}
    monkeypatch.setattr(server_module, "SpeechApplication", lambda config: app)
    server = server_module.create_server(replace(app.config, host="127.0.0.1", port=0, tts_prewarm_enabled=False))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    def post(action):
        request = Request(url + "/v1/asr/model", data=json.dumps({"action": action}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    try:
        assert post("start")["asr"]["keep_loaded"]
        with urlopen(url + "/health", timeout=5) as response:
            assert json.load(response)["asr"]["loaded"]
        assert len(children) == 1
        assert not post("stop")["asr"]["loaded"]
        # Stopping the model leaves the HTTP service responding.
        with urlopen(url + "/health", timeout=5) as response:
            assert json.load(response)["ok"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_failed_resident_load_does_not_keep_worker(worker, monkeypatch):
    tmp_path, children = worker
    app, _ = make_app(tmp_path)
    def failed():
        raise OSError("模型不可用")
    monkeypatch.setattr(app.asr, "_start_worker", failed)
    async def scenario():
        with pytest.raises(ProviderError, match="模型不可用"):
            await app.control_asr("start")
        assert not app.asr.status()["keep_loaded"]
        assert not app.asr.status()["loaded"]
        assert app.asr.status()["load_error"]
        assert not app.resources.status()["busy"]
    asyncio.run(scenario())


def test_http_application_reuses_one_worker_and_cleans_requests(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)

    async def scenario():
        first = await app.transcribe({"audio_path": str(audio), "language": "zh"})
        second = await app.transcribe({"audio_path": str(audio), "language": "zh"})
        assert first["text"] == second["text"]
        assert len(children) == 1
        assert app.asr.status()["loaded"] is True
        assert app._last_asr_timings["queue_seconds"] >= 0
        assert list((app.config.cache_dir / "asr-jobs").iterdir()) == []
        await app.asr.unload()
        assert children[0].poll() is not None
        assert app.asr.status()["loaded"] is False

    asyncio.run(scenario())


def test_idle_timeout_exits_owned_worker(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)
    app.asr.config = replace(app.config, asr_worker_idle_seconds=0.05)

    async def scenario():
        await app.transcribe({"audio_path": str(audio)})
        await asyncio.sleep(0.2)
        assert children[0].poll() is not None
        assert not app.asr.status()["loaded"]

    asyncio.run(scenario())


def test_worker_crash_recovers_without_stale_results(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)

    async def scenario():
        with pytest.raises(ProviderError):
            await app.transcribe({"audio_path": str(audio), "language": "crash"})
        assert not app.resources.status()["busy"]
        result = await app.transcribe({"audio_path": str(audio), "language": "zh"})
        assert result["ok"]
        assert len(children) == 2
        await app.asr.unload()
        assert list((app.config.cache_dir / "asr-jobs").iterdir()) == []

    asyncio.run(scenario())


def test_zero_idle_releases_process_after_every_request(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)
    app.asr.config = replace(app.config, asr_worker_idle_seconds=0)

    async def scenario():
        await app.transcribe({"audio_path": str(audio)})
        assert children[0].poll() is not None
        await app.transcribe({"audio_path": str(audio)})
        assert len(children) == 2 and children[1].poll() is not None
        assert not app.asr.status()["loaded"]

    asyncio.run(scenario())


def test_gpu_worker_never_retains_vram_by_idle_policy(tmp_path):
    config = VoiceServiceConfig(asr_device="cuda:0", asr_worker_idle_seconds=60)
    assert IsolatedSenseVoiceProvider(config).idle_seconds == 0


@pytest.mark.parametrize("text", [
    "今天我们去散步。", "这件事不要图利他人。", "不要脱衣，外面很冷。",
    "脱离危险后再回来。", "今天需要多少涂料？", "你好，亚托莉。",
])
def test_name_lexicon_does_not_rewrite_ordinary_near_sounds(tmp_path, text):
    path = tmp_path / "hotwords.json"
    save_lexicon(path, [{"term": "亚托莉", "aliases": ["亚托利", "亚托丽", "阿托莉"]}])
    assert AsrLexicon(path).correct(text) == text


def test_concurrent_requests_use_one_worker_without_crossed_results(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)

    async def scenario():
        results = await asyncio.gather(*(
            app.transcribe({"audio_path": str(audio), "language": "zh"}) for _ in range(3)
        ))
        assert len(children) == 1
        assert len({result["text"] for result in results}) == 1
        assert not app.resources.status()["busy"]
        await app.asr.unload()

    asyncio.run(scenario())


def test_cancellation_exits_child_before_releasing_resource_lease(worker):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)

    async def scenario():
        task = asyncio.create_task(app.transcribe({"audio_path": str(audio), "language": "wait"}))
        while not children:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].poll() is not None
        assert not app.resources.status()["busy"]
        assert list((app.config.cache_dir / "asr-jobs").iterdir()) == []

    asyncio.run(scenario())


def test_worker_inherits_resolved_config_instead_of_parent_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ATRI_ASR_DEVICE", "cuda:0")
    captured = {}

    def popen(*args, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(subprocess, "Popen", popen)
    config = VoiceServiceConfig(asr_device="cpu", asr_model="local-model", cache_dir=tmp_path)
    IsolatedSenseVoiceProvider(config)._start_worker()
    env = captured["env"]
    assert env["ATRI_ASR_DEVICE"] == "cpu"
    assert env["ATRI_ASR_MODEL"] == "local-model"
    assert env["ATRI_VOICE_CACHE_DIR"] == str(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows venv launcher creates an interpreter child")
@pytest.mark.parametrize("use_voice_runtime", [False, True], ids=["test-python", "voice-runtime"])
def test_cancellation_reaps_windows_venv_interpreter_descendant(worker, monkeypatch, use_voice_runtime):
    import ctypes
    from ctypes import wintypes

    tmp_path, _ = worker
    if use_voice_runtime:
        executable = Path(__file__).resolve().parents[1] / "data/runtime/voice-runtime/.venv/Scripts/python.exe"
        if not executable.is_file():
            pytest.skip("Local voice runtime is not installed")
        monkeypatch.setattr(sys, "executable", str(executable))
    app, audio = make_app(tmp_path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    async def scenario():
        task = asyncio.create_task(app.transcribe({"audio_path": str(audio), "language": "wait"}))
        pid_file = tmp_path / "worker.pid"
        for _ in range(500):
            if pid_file.is_file():
                break
            await asyncio.sleep(0.01)
        assert pid_file.is_file()
        handle = kernel.OpenProcess(0x100000 | 0x0001, False, int(pid_file.read_text()))
        assert handle
        try:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert kernel.WaitForSingleObject(handle, 1000) == 0
        finally:
            if kernel.WaitForSingleObject(handle, 0) != 0:
                kernel.TerminateProcess(handle, 1)
                kernel.WaitForSingleObject(handle, 5000)
            kernel.CloseHandle(handle)

    asyncio.run(scenario())


def test_server_close_reaps_its_owned_worker(worker):
    from http.server import BaseHTTPRequestHandler

    tmp_path, children = worker
    app, audio = make_app(tmp_path)
    server = VoiceHttpServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    server.asr_provider = app.asr
    try:
        assert server.run_async(app.transcribe({"audio_path": str(audio)}))["ok"]
        assert children[0].poll() is None
    finally:
        server.server_close()
    assert children[0].poll() is not None
    assert server.event_loop.is_closed()


def test_tts_session_keeps_cpu_asr_warm_without_loading_real_tts(worker, monkeypatch):
    tmp_path, children = worker
    app, audio = make_app(tmp_path)

    async def fake_synthesize(*args, **kwargs):
        return QualityCheckedSynthesis(SynthesisResult(audio), None, None)

    monkeypatch.setattr("atri_voice_service.speech_pipeline.synthesize_with_quality", fake_synthesize)
    pipeline = ConversationSpeechPipeline(
        app.config, tts=object(), asr=app.asr,
        originals=SimpleNamespace(match=lambda *args: None),
        profiles=SimpleNamespace(load=lambda _: SimpleNamespace(id="atri", tts_provider="gpt_sovits")),
        resources=app.resources,
    )

    async def scenario():
        first = await app.transcribe({"audio_path": str(audio), "language": "zh"})
        result = await pipeline.synthesize(
            VoiceRequest("你好", language="zh"), "atri",
            SpeechSynthesisOptions(False, False, 0, 0.12),
        )
        assert result.audio_path == audio
        assert app.asr.status()["loaded"]
        second = await app.transcribe({"audio_path": str(audio), "language": "zh"})
        assert first["text"] == second["text"] and len(children) == 1
        assert not app.resources.status()["busy"]
        await app.asr.unload()

    asyncio.run(scenario())


def test_explicit_chinese_language_reaches_sensevoice_decoder(tmp_path, monkeypatch):
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return [{"text": "<|zh|><|NEUTRAL|>今天我们去散步。"}]

    provider = SenseVoiceProvider(str(tmp_path), "cpu", tmp_path)
    provider._model = SimpleNamespace(generate=generate)
    monkeypatch.setattr(
        "atri_voice_service.providers.prepare_speech_audio",
        lambda *args, **kwargs: PreparedAudio(tmp_path / "input.wav"),
    )
    result = asyncio.run(provider.transcribe(tmp_path / "input.wav", "zh"))
    assert captured["language"] == "zh"
    assert result.text == "今天我们去散步。"
