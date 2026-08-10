from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import subprocess
import sys
import types
import wave
from importlib.machinery import ModuleSpec
from pathlib import Path

import httpx
import pytest

from atri_voice_service.config import ATRI_MODELS_ROOT, LOCAL_MODELS_ROOT, VoiceServiceConfig
from atri_voice_service.app import SpeechApplication
from atri_voice_service.asr_lexicon import AsrLexicon, save_lexicon
from atri_voice_service.audio_processing import (
    AudioPreprocessError,
    AudioValidationError,
    postprocess_synthesized_audio,
    prepare_speech_audio,
    validate_synthesized_speech_timing,
)
from atri_voice_service.model_registry import install_candidate_profiles, load_voice_candidates
from atri_voice_service.original_library import OriginalVoiceLibrary
from atri_voice_service.profiles import VoiceProfile, VoiceProfileStore, profile_from_dict
from atri_voice_service.providers import (
    GptSovitsProvider,
    ProviderError,
    SenseVoiceProvider,
    _auxiliary_reference_paths,
    _engine_weight_path,
    _reference_context,
    _tts_language,
    _tts_seed,
    _tts_style,
    parse_sensevoice_output,
)
from atri_voice_service.tts_text import (
    TtsPronunciationLexicon,
    normalize_tts_text,
    save_pronunciation_text,
)
from atri_voice_service.quality import evaluate_transcript_quality
from atri_voice_service.singing import OriginalSingingProvider
from atri_voice_service.resources import InferenceResourceManager
from atri_voice_service.singing_jobs import SingingJobManager
from atri_voice_service.singing_pipeline import (
    ExternalPipelineManifest,
    ExternalSingingProvider,
    SingingJobRequest,
    evaluate_audio_file,
)
from atri_voice_service.speech_pipeline import (
    ConversationSpeechPipeline,
    SpeechSynthesisOptions,
)
from atri_qq_bot.voice import SynthesisResult, TranscriptionResult, VoiceRequest
from tools.voice.separate_singing_stems import _resolve_output_paths


def test_parse_sensevoice_output_extracts_text_language_and_emotion() -> None:
    text, language, emotion = parse_sensevoice_output(
        "<|zh|><|SAD|><|Speech|><|withitn|>今天有一点累。"
    )

    assert text == "今天有一点累。"
    assert language == "zh"
    assert emotion == "sad"


def test_original_voice_library_indexes_labels_and_loose_named_clips(tmp_path: Path) -> None:
    root = tmp_path / "library"
    dataset = root / "dataset" / "ATRI"
    dataset.mkdir(parents=True)
    labelled = dataset / "line.wav"
    labelled.write_bytes(b"RIFFvoice")
    (root / ".speaker.list").write_text(
        "./dataset/ATRI/line.wav|ATRI|JP|おはようございます\n",
        encoding="utf-8",
    )
    loose = root / "早上好.mp3"
    loose.write_bytes(b"voice")
    library = OriginalVoiceLibrary(root, tmp_path / "cache", refresh_seconds=1)

    japanese = library.match("おはようございます。", "ja")
    chinese = library.match("早上好！", "zh")

    assert japanese is not None and japanese.path == labelled
    assert chinese is not None and chinese.path == loose
    materialized = library.materialize(chinese)
    assert materialized.is_file()
    assert materialized.parent.name == "original-clips"
    assert library.status()["clips"] == 2


def test_original_voice_library_handles_flattened_speaker_list_paths(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "ATR_b101_008.wav"
    source.write_bytes(b"RIFFvoice")
    (root / ".speaker.list").write_text(
        "./dataset/ATRI/ATR_b101_008.wav|ATRI|JP|ゴボゴボ\n",
        encoding="utf-8",
    )
    library = OriginalVoiceLibrary(root, tmp_path / "cache")

    match = library.match("ゴボゴボ", "ja")

    assert match is not None and match.path == source


def test_original_voice_library_keeps_single_cjk_interjection(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "疼.mp3"
    source.write_bytes(b"voice")
    library = OriginalVoiceLibrary(root, tmp_path / "cache")

    match = library.match("疼！", "zh")

    assert match is not None and match.path == source


def test_original_voice_library_prefers_handcrafted_contextual_reply(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    handcrafted = root / "手搓音频素材"
    duplicate = root / "other"
    handcrafted.mkdir(parents=True)
    duplicate.mkdir()
    preferred = handcrafted / "早上好.mp3"
    preferred.write_bytes(b"handcrafted")
    (duplicate / "早上好.mp3").write_bytes(b"duplicate")
    library = OriginalVoiceLibrary(root, tmp_path / "cache")

    match = library.match("早上好呀，主人！", "zh")

    assert match is not None and match.path == preferred
    assert match.source == "handcrafted"


def test_original_voice_library_maps_equivalent_morning_greeting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library" / "手搓音频素材"
    root.mkdir(parents=True)
    source = root / "早上好.mp3"
    source.write_bytes(b"handcrafted")
    library = OriginalVoiceLibrary(root.parent, tmp_path / "cache")

    match = library.match("早安", "zh")

    assert match is not None and match.path == source
    assert match.source == "handcrafted"
    assert match.score == 0.985


def test_original_voice_library_contextual_fallback_broadens_handcrafted_match(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library" / "手搓音频素材"
    root.mkdir(parents=True)
    source = root / "早上好.mp3"
    source.write_bytes(b"handcrafted")
    (root / "疼.mp3").write_bytes(b"pain")
    library = OriginalVoiceLibrary(root.parent, tmp_path / "cache")

    match = library.match_contextual("早上好呀，今天也要精神满满哦！", "zh")

    assert match is not None and match.path == source
    assert match.source == "handcrafted"
    assert library.match_contextual("Good morning, Master!", "en").path == source
    assert library.match_contextual("おはよう、マスター！", "ja").path == source
    assert library.match_contextual("比如夸夸今天的头像", "zh") is None
    assert library.match_contextual("有的事情需要慢慢处理", "zh") is None


def test_original_voice_library_only_uses_singing_folder_for_singing(tmp_path: Path) -> None:
    root = tmp_path / "library"
    singing = root / "歌唱"
    singing.mkdir(parents=True)
    (root / "早上好.mp3").write_bytes(b"speech")
    song = singing / "早上好.mp3"
    song.write_bytes(b"song")
    library = OriginalVoiceLibrary(root, tmp_path / "cache")

    match = library.match("早上好", "zh", singing_only=True)

    assert match is not None and match.path == song


def test_singing_provider_never_uses_ordinary_spoken_clip(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "早上好.mp3").write_bytes(b"speech")
    library = OriginalVoiceLibrary(root, tmp_path / "cache")
    provider = OriginalSingingProvider(library)

    with pytest.raises(Exception, match="歌声素材"):
        asyncio.run(
            provider.synthesize(
                VoiceRequest("早上好", language="zh", mode="singing")
            )
        )


def test_singing_provider_returns_matching_complete_song_clip(tmp_path: Path) -> None:
    root = tmp_path / "library" / "歌唱"
    root.mkdir(parents=True)
    source = root / "啦啦啦.mp3"
    source.write_bytes(b"song")
    library = OriginalVoiceLibrary(root.parent, tmp_path / "cache")
    provider = OriginalSingingProvider(library)

    result = asyncio.run(
        provider.synthesize(VoiceRequest("啦啦啦", language="zh", mode="singing"))
    )

    assert result.source == "original_clip"
    assert result.audio_path.read_bytes() == b"song"
    assert provider.status()["ready"] is True


def test_conversation_speech_pipeline_rejects_singing_requests(tmp_path: Path) -> None:
    pipeline = ConversationSpeechPipeline(
        VoiceServiceConfig(original_library_dir=tmp_path),
        tts=object(),
        asr=object(),
        originals=OriginalVoiceLibrary(tmp_path, tmp_path / "cache"),
        profiles=VoiceProfileStore(tmp_path / "profiles"),
        resources=InferenceResourceManager(),
    )

    with pytest.raises(ProviderError, match="日常语音"):
        asyncio.run(
            pipeline.synthesize(
                VoiceRequest("唱一首歌", mode="singing"),
                "atri",
                SpeechSynthesisOptions(
                    prefer_original=False,
                    quality_gate=False,
                    quality_retries=0,
                    quality_max_error_rate=0.12,
                ),
            )
        )


def test_conversation_speech_pipeline_exposes_rejected_quality_report(
    tmp_path: Path,
) -> None:
    output = tmp_path / "unclear.wav"
    output.write_bytes(b"RIFFvoice")
    profiles = VoiceProfileStore(tmp_path / "profiles")
    profiles.save(VoiceProfile(id="atri", display_name="ATRI"))

    class FakeTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            return SynthesisResult(output)

    class FakeAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            return TranscriptionResult("喂", language)

    pipeline = ConversationSpeechPipeline(
        VoiceServiceConfig(original_library_dir=tmp_path),
        tts=FakeTts(),
        asr=FakeAsr(),
        originals=OriginalVoiceLibrary(tmp_path, tmp_path / "cache"),
        profiles=profiles,
        resources=InferenceResourceManager(),
    )

    with pytest.raises(ProviderError, match="质量标准") as error:
        asyncio.run(
            pipeline.synthesize(
                VoiceRequest("晚安", language="zh"),
                "atri",
                SpeechSynthesisOptions(
                    prefer_original=False,
                    quality_gate=True,
                    quality_retries=0,
                    quality_max_error_rate=0.12,
                ),
            )
        )

    assert error.value.quality_report["rejected"] is True
    assert pipeline.last_quality == error.value.quality_report
    assert pipeline.status()["quality_gate"]["last_report"]["transcribed"] == "喂"


def test_conversation_speech_pipeline_uses_contextual_original_after_tts_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library" / "手搓音频素材"
    root.mkdir(parents=True)
    original = root / "早上好.mp3"
    original.write_bytes(b"official")
    profiles = VoiceProfileStore(tmp_path / "profiles")
    profiles.save(VoiceProfile(id="atri", display_name="ATRI"))

    class FailedTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            raise ProviderError("GPT-SoVITS 暂时失败", retryable=True)

    pipeline = ConversationSpeechPipeline(
        VoiceServiceConfig(original_library_dir=root.parent),
        tts=FailedTts(),
        asr=object(),
        originals=OriginalVoiceLibrary(root.parent, tmp_path / "cache"),
        profiles=profiles,
        resources=InferenceResourceManager(),
    )

    result = asyncio.run(
        pipeline.synthesize(
            VoiceRequest("早上好呀，今天也要精神满满哦", language="zh"),
            "atri",
            SpeechSynthesisOptions(
                prefer_original=True,
                quality_gate=True,
                quality_retries=1,
                quality_max_error_rate=0.12,
                allow_context_original_fallback=True,
            ),
        )
    )

    assert result.source == "original_context_fallback"
    assert result.audio_path.read_bytes() == b"official"
    assert result.quality["requested_text"] == "早上好呀，今天也要精神满满哦"


def test_conversation_speech_pipeline_accepts_safe_best_effort_rescue(
    tmp_path: Path,
) -> None:
    output = tmp_path / "near.wav"
    output.write_bytes(b"RIFFvoice")
    profiles = VoiceProfileStore(tmp_path / "profiles")
    profiles.save(VoiceProfile(id="atri", display_name="ATRI"))

    class NearTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            return SynthesisResult(output)

    class NearAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            return TranscriptionResult("你俩这是轮回点我我哪儿也不去", language)

    pipeline = ConversationSpeechPipeline(
        VoiceServiceConfig(original_library_dir=tmp_path / "library"),
        tts=NearTts(),
        asr=NearAsr(),
        originals=OriginalVoiceLibrary(tmp_path / "library", tmp_path / "cache"),
        profiles=profiles,
        resources=InferenceResourceManager(),
    )

    result = asyncio.run(
        pipeline.synthesize(
            VoiceRequest("你俩这是轮番点我我哪儿也不去", language="zh"),
            "atri",
            SpeechSynthesisOptions(
                prefer_original=True,
                quality_gate=True,
                quality_retries=0,
                quality_max_error_rate=0.05,
                allow_best_effort=True,
            ),
        )
    )

    assert result.source == "tts"
    assert result.quality["passed"] is True
    assert result.quality["strict_quality_passed"] is False
    assert result.quality["best_effort"] is True


def test_speech_application_routes_speech_and_singing_independently() -> None:
    calls: list[str] = []

    class FakeConversationSpeech:
        last_quality = {"passed": True}

        async def synthesize(
            self,
            request: VoiceRequest,
            profile_id: str,
            options: SpeechSynthesisOptions,
        ) -> SynthesisResult:
            calls.append(f"speech:{request.text}:{profile_id}")
            return SynthesisResult(Path("speech.wav"), source="tts")

    class FakeSingingService:
        async def synthesize_clip(self, request: VoiceRequest) -> SynthesisResult:
            calls.append(f"singing:{request.text}")
            return SynthesisResult(Path("song.wav"), source="original_clip")

    app = SpeechApplication.__new__(SpeechApplication)
    app.config = VoiceServiceConfig()
    app.conversation_speech = FakeConversationSpeech()
    app.singing_service = FakeSingingService()
    app._last_quality = None

    speech = asyncio.run(app.synthesize({"text": "早上好", "profile": "atri"}))
    song = asyncio.run(app.synthesize({"text": "唱一首歌", "mode": "singing"}))

    assert calls == ["speech:早上好:atri", "singing:唱一首歌"]
    assert speech["source"] == "tts"
    assert song["source"] == "original_clip"


def test_external_singing_pipeline_creates_preview_and_reuses_cache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    _write_test_tone(source, duration_seconds=1.0)
    converter = tmp_path / "converter.py"
    converter.write_text(
        "import shutil, sys\nshutil.copy2(sys.argv[1], sys.argv[2])\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "pipeline.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "test-svc",
                "converter": [
                    sys.executable,
                    str(converter),
                    "{vocal}",
                    "{converted}",
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = ExternalSingingProvider(
        manifest_path,
        tmp_path / "cache",
        InferenceResourceManager(),
    )
    request = SingingJobRequest(
        "测试歌曲",
        source,
        reference_audio_path=source,
        preview_seconds=5,
    )
    progress: list[tuple[int, str]] = []

    first = asyncio.run(provider.synthesize(request, lambda value, text: progress.append((value, text))))
    second = asyncio.run(provider.synthesize(request, lambda value, text: progress.append((value, text))))

    assert first.audio_path.is_file()
    assert first.source == "singing_svc:test-svc"
    assert first.quality and first.quality["passed"] is True
    assert second.audio_path == first.audio_path
    assert second.source == "singing_cache"
    assert progress[-1] == (100, "已使用缓存歌声")


def test_external_singing_pipeline_manifest_requires_argument_arrays(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "pipeline.json"
    manifest_path.write_text(
        '{"id":"unsafe","converter":"python converter.py"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="字符串数组"):
        ExternalPipelineManifest.load(manifest_path)


def test_singing_job_manager_reports_actionable_failure(tmp_path: Path) -> None:
    library = OriginalVoiceLibrary(tmp_path / "library", tmp_path / "cache")
    original = OriginalSingingProvider(library)
    manager = SingingJobManager(library, original, None)

    async def run_job() -> dict[str, object]:
        submitted = manager.submit({"text": "不存在的歌"})
        while manager.get(str(submitted["id"]))["state"] not in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            await asyncio.sleep(0)
        return manager.get(str(submitted["id"]))

    result = asyncio.run(run_job())

    assert result["state"] == "failed"
    assert "尚未配置" in str(result["error"])


def test_audio_quality_rejects_silence(tmp_path: Path) -> None:
    silent = tmp_path / "silent.wav"
    with wave.open(str(silent), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\0\0" * 44100)

    report = evaluate_audio_file(silent)

    assert report["passed"] is False
    assert "静音" in str(report["reason"])


def test_speech_quality_report_detects_omissions_and_accepts_punctuation() -> None:
    passed = evaluate_transcript_quality(
        "早上好，今天也要开心！",
        "早上好今天也要开心",
        maximum_error_rate=0.1,
    )
    failed = evaluate_transcript_quality(
        "早上好，今天也要开心！",
        "早上好",
        maximum_error_rate=0.1,
    )

    assert passed.passed is True
    assert passed.error_rate == 0
    assert failed.passed is False
    assert failed.error_rate > 0.4


def test_speech_quality_accepts_mandarin_homophones_but_not_cross_language() -> None:
    homophone = evaluate_transcript_quality(
        "依旧再议",
        "依旧在意",
        maximum_error_rate=0.12,
    )
    cross_language = evaluate_transcript_quality(
        "点别的",
        "でめだ",
        maximum_error_rate=0.12,
    )

    assert homophone.passed is True
    assert homophone.character_error_rate == 0.5
    assert homophone.phonetic_error_rate == 0.0
    assert cross_language.passed is False
    assert cross_language.phonetic_error_rate is None


def test_speech_quality_accepts_equivalent_spoken_particles() -> None:
    report = evaluate_transcript_quality(
        "唔，原来你一直在用口头禅说我呀！",
        "嗯，原来你一直在用口头禅说我啊！",
        maximum_error_rate=0.12,
    )

    assert report.passed is True
    assert report.error_rate == pytest.approx(0.0)


def test_speech_application_retries_tts_until_round_trip_text_passes(
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / "first.wav", tmp_path / "second.wav"]
    for output in outputs:
        output.write_bytes(b"RIFFvoice")
    attempts: list[int] = []
    transcripts = iter(("早上好", "早上好今天也要开心"))

    class FakeTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            attempts.append(variation)
            return SynthesisResult(outputs[variation])

    class FakeAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            return TranscriptionResult(next(transcripts), language)

    app = SpeechApplication.__new__(SpeechApplication)
    app.config = VoiceServiceConfig(
        tts_quality_max_error_rate=0.1,
        original_library_dir=tmp_path,
    )
    app.tts = FakeTts()
    app.asr = FakeAsr()
    app._last_quality = None
    result, report = asyncio.run(
        app._synthesize_with_quality(
            VoiceRequest("早上好，今天也要开心", language="zh"),
            VoiceProfile(id="atri", display_name="ATRI"),
            quality_gate=True,
            retries=1,
            maximum_error_rate=0.1,
        )
    )

    assert result.audio_path == outputs[1]
    assert report is not None and report.passed is True
    assert attempts == [0, 1]


def test_speech_pipeline_retries_rejected_audio_candidate_before_asr(
    tmp_path: Path,
) -> None:
    output = tmp_path / "second.wav"
    output.write_bytes(b"RIFFvoice")
    variations: list[int] = []

    class FakeTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            variations.append(variation)
            if variation == 0:
                raise ProviderError(
                    "合成音频包含异常长静音",
                    retryable=True,
                )
            return SynthesisResult(output)

    class FakeAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            return TranscriptionResult("今天辛苦了", language)

    app = SpeechApplication.__new__(SpeechApplication)
    app.config = VoiceServiceConfig(
        tts_quality_max_error_rate=0.12,
        original_library_dir=tmp_path,
    )
    app.tts = FakeTts()
    app.asr = FakeAsr()
    app._last_quality = None

    result, report = asyncio.run(
        app._synthesize_with_quality(
            VoiceRequest("今天辛苦了", language="zh"),
            VoiceProfile(id="atri", display_name="ATRI"),
            quality_gate=True,
            retries=1,
            maximum_error_rate=0.12,
        )
    )

    assert result.audio_path == output
    assert report is not None and report.passed is True
    assert variations == [0, 1]
    assert app._last_quality["generation_retries"] == 1
    assert "异常长静音" in app._last_quality["candidate_errors"][0]


def test_speech_application_rejects_all_attempts_above_configured_quality_limit(
    tmp_path: Path,
) -> None:
    outputs = [
        tmp_path / "first.wav",
        tmp_path / "second.wav",
        tmp_path / "neutral.wav",
    ]
    for output in outputs:
        output.write_bytes(b"RIFFvoice")
    transcripts = iter(("早上", "早上好今天也要开", "早上好今天也"))
    call_index = 0

    class FakeTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            nonlocal call_index
            output = outputs[call_index]
            call_index += 1
            return SynthesisResult(output)

    class FakeAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            return TranscriptionResult(next(transcripts), language)

    app = SpeechApplication.__new__(SpeechApplication)
    app.config = VoiceServiceConfig(
        tts_quality_max_error_rate=0.05,
        original_library_dir=tmp_path,
    )
    app.tts = FakeTts()
    app.asr = FakeAsr()
    app._last_quality = None

    with pytest.raises(ProviderError, match="质量标准"):
        asyncio.run(
            app._synthesize_with_quality(
                VoiceRequest("早上好今天也要开心", language="zh"),
                VoiceProfile(id="atri", display_name="ATRI"),
                quality_gate=True,
                retries=1,
                maximum_error_rate=0.05,
            )
        )

    assert app._last_quality["rejected"] is True
    assert app._last_quality["maximum_error_rate"] == 0.05


def test_speech_application_rejects_severely_inaccurate_voice(
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / "first.wav", tmp_path / "second.wav"]
    for output in outputs:
        output.write_bytes(b"RIFFvoice")
    class FakeTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            return SynthesisResult(outputs[variation])

    class FakeAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            raise ProviderError("SenseVoice 没有识别出文本")

    app = SpeechApplication.__new__(SpeechApplication)
    app.config = VoiceServiceConfig(
        tts_quality_max_error_rate=0.12,
        original_library_dir=tmp_path,
    )
    app.tts = FakeTts()
    app.asr = FakeAsr()
    app._last_quality = None

    with pytest.raises(ProviderError, match="回读"):
        asyncio.run(
            app._synthesize_with_quality(
                VoiceRequest("今晚早点休息，我会陪着你。", language="zh"),
                VoiceProfile(id="atri", display_name="ATRI"),
                quality_gate=True,
                retries=1,
                maximum_error_rate=0.12,
            )
        )

    assert app._last_quality["rejected"] is True


def test_speech_application_uses_neutral_rescue_after_emotional_attempts_fail(
    tmp_path: Path,
) -> None:
    outputs = [
        tmp_path / "first.wav",
        tmp_path / "second.wav",
        tmp_path / "neutral.wav",
    ]
    for output in outputs:
        output.write_bytes(b"RIFFvoice")
    transcripts = iter(("喂主人", "安主人", "晚安主人"))
    requests: list[VoiceRequest] = []

    class FakeTts:
        async def synthesize(
            self,
            request: VoiceRequest,
            profile: VoiceProfile,
            *,
            variation: int = 0,
        ) -> SynthesisResult:
            requests.append(request)
            return SynthesisResult(outputs[len(requests) - 1])

    class FakeAsr:
        async def transcribe(self, path: Path, language: str) -> TranscriptionResult:
            return TranscriptionResult(next(transcripts), language)

    app = SpeechApplication.__new__(SpeechApplication)
    app.config = VoiceServiceConfig(
        tts_quality_max_error_rate=0.1,
        original_library_dir=tmp_path,
    )
    app.tts = FakeTts()
    app.asr = FakeAsr()
    app._last_quality = None

    result, report = asyncio.run(
        app._synthesize_with_quality(
            VoiceRequest("晚安主人", emotion="sleepy", language="zh"),
            VoiceProfile(id="atri", display_name="ATRI"),
            quality_gate=True,
            retries=1,
            maximum_error_rate=0.1,
        )
    )

    assert result.audio_path == outputs[2]
    assert report is not None and report.passed is True
    assert [request.emotion for request in requests] == ["sleepy", "sleepy", "neutral"]
    assert app._last_quality["neutral_rescue"] is True


def test_asr_lexicon_corrects_only_configured_aliases(tmp_path: Path) -> None:
    path = tmp_path / "asr-hotwords.json"
    save_lexicon(
        path,
        [{"term": "亚托莉", "aliases": ["亚托利", "阿托莉"]}],
    )
    lexicon = AsrLexicon(path)

    assert lexicon.correct("亚托利今天很开心") == "亚托莉今天很开心"
    assert lexicon.correct("今天很开心") == "今天很开心"
    assert lexicon.terms() == ["亚托莉"]


def test_prepare_speech_audio_outputs_16k_mono_pcm(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        frames = []
        for index in range(1600):
            sample = int(5000 * math.sin(2 * math.pi * 440 * index / 8000))
            frames.append(struct.pack("<hh", sample, sample))
        audio.writeframes(b"".join(frames))

    prepared = prepare_speech_audio(source, tmp_path / "cache")
    try:
        with wave.open(str(prepared.path), "rb") as audio:
            assert audio.getnchannels() == 1
            assert audio.getframerate() == 16000
            assert audio.getsampwidth() == 2
            assert 0.19 <= audio.getnframes() / audio.getframerate() <= 0.21
    finally:
        prepared.cleanup()
    assert not prepared.path.exists()


def test_prepare_speech_audio_hides_ffmpeg_console_on_windows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    captured: dict[str, object] = {}

    monkeypatch.setattr("imageio_ffmpeg.get_ffmpeg_exe", lambda: "ffmpeg.exe")

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        output = Path(command[-1])
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 3200)
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    monkeypatch.setattr(
        "atri_voice_service.audio_processing.subprocess.run",
        fake_run,
    )

    prepared = prepare_speech_audio(source, tmp_path / "cache")
    prepared.cleanup()

    if os.name == "nt":
        assert int(captured["creationflags"]) & subprocess.CREATE_NO_WINDOW
        assert captured["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    else:
        assert "creationflags" not in captured
        assert "startupinfo" not in captured


def test_prepare_speech_audio_rejects_audio_above_duration_limit(tmp_path: Path) -> None:
    source = tmp_path / "long.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 19200)

    with pytest.raises(AudioValidationError, match="超过"):
        prepare_speech_audio(source, tmp_path / "cache", max_duration_seconds=1.0)


def test_tts_postprocess_trims_long_silence_and_applies_bounded_gain(tmp_path: Path) -> None:
    path = tmp_path / "quiet.wav"
    sample_rate = 16000
    silence_before = [0] * sample_rate
    speech = [
        int(2200 * math.sin(2 * math.pi * 220 * index / sample_rate))
        for index in range(sample_rate // 2)
    ]
    silence_after = [0] * int(sample_rate * 0.8)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(
            b"".join(struct.pack("<h", value) for value in silence_before + speech + silence_after)
        )

    result = postprocess_synthesized_audio(path)

    assert 0.85 <= result.duration_seconds <= 0.95
    assert 0 < result.gain_db <= 6
    assert result.trimmed_leading_seconds >= 0.75
    assert result.trimmed_trailing_seconds >= 0.5
    with wave.open(str(path), "rb") as audio:
        values = struct.unpack(f"<{audio.getnframes()}h", audio.readframes(audio.getnframes()))
    assert max(abs(value) for value in values) < 32767


def test_tts_pronunciation_lexicon_applies_selected_language(tmp_path: Path) -> None:
    path = tmp_path / "tts-pronunciations.json"
    save_pronunciation_text(path, "ATRI = 亚托莉 | Atri | アトリ")
    lexicon = TtsPronunciationLexicon(path)

    assert lexicon.apply("ATRI 在这里", "zh") == "亚托莉 在这里"
    assert lexicon.apply("Hello ATRI", "en") == "Hello Atri"
    assert lexicon.apply("ATRIです", "ja") == "アトリです"


def test_postprocess_rejects_pathological_long_silence(tmp_path: Path) -> None:
    path = tmp_path / "mostly-silence.wav"
    sample_rate = 16000
    samples = [0] * (sample_rate * 10)
    tone_start = sample_rate * 5
    for index in range(sample_rate // 3):
        samples[tone_start + index] = int(
            5000 * math.sin(2 * math.pi * 220 * index / sample_rate)
        )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    with pytest.raises(AudioPreprocessError, match="异常长静音"):
        postprocess_synthesized_audio(path)


def test_speech_timing_rejects_short_text_with_runaway_duration() -> None:
    with pytest.raises(AudioPreprocessError, match="异常拖长"):
        validate_synthesized_speech_timing("晚安。", "zh", 56.52)

    validate_synthesized_speech_timing("晚安。", "zh", 2.0)


def test_normalize_tts_text_removes_markup_and_symbols() -> None:
    assert normalize_tts_text("**主人** `你好` 😊", "zh") == "主人，你好。"


def test_normalize_tts_text_removes_voice_stage_directions() -> None:
    assert normalize_tts_text(
        "（轻声开口，带着一点睡前故事的柔软调子）从前呀，在很深的海底。",
        "zh",
    ) == "从前呀，在很深的海底。"


def test_normalize_tts_text_keeps_atri_wording_without_theatrical_pauses() -> None:
    assert normalize_tts_text(
        "嗯…好呀～（小声）因为我是高性能的呢～～",
        "zh",
    ) == "嗯，好呀，因为我是高性能的呢。"
    assert (
        normalize_tts_text("那就好早上心情不错的话，今天都会顺手一点", "zh")
        == "那就好，早上心情不错的话，今天都会顺手一点。"
    )


def test_sensevoice_warmup_passes_local_vad_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    fake_funasr = types.ModuleType("funasr")
    fake_funasr.__spec__ = ModuleSpec("funasr", loader=None)

    def fake_auto_model(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    fake_funasr.AutoModel = fake_auto_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "funasr", fake_funasr)
    provider = SenseVoiceProvider(
        str(tmp_path),
        "cpu",
        tmp_path / "cache",
        vad_model=str(tmp_path / "vad"),
        vad_max_segment_ms=25_000,
    )

    asyncio.run(provider.warmup())

    assert captured["vad_model"] == str(tmp_path / "vad")
    assert captured["vad_kwargs"] == {"max_single_segment_time": 25_000}


def test_sensevoice_warmup_exposes_loaded_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_funasr = types.ModuleType("funasr")
    fake_funasr.__spec__ = ModuleSpec("funasr", loader=None)
    fake_funasr.AutoModel = lambda **kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "funasr", fake_funasr)
    provider = SenseVoiceProvider(str(tmp_path), "cpu", tmp_path / "cache")

    asyncio.run(provider.warmup())

    status = provider.status()
    assert status["loaded"] is True
    assert status["loading"] is False
    assert status["load_error"] == ""


def test_voice_models_use_project_specific_local_model_directory() -> None:
    assert LOCAL_MODELS_ROOT == Path(r"D:\本地大模型\models")
    assert ATRI_MODELS_ROOT == LOCAL_MODELS_ROOT / "AI_ATRI"


def test_modelscope_cache_preserves_ascii_junction_path(monkeypatch) -> None:
    monkeypatch.setenv("MODELSCOPE_CACHE", r"D:\AtriModels\voice\modelscope")
    monkeypatch.delenv("ATRI_ASR_MODEL", raising=False)

    config = VoiceServiceConfig.from_env()

    assert str(config.modelscope_cache) == r"D:\AtriModels\voice\modelscope"
    assert str(config.asr_model).startswith(r"D:\AtriModels\voice\modelscope")


def test_profile_store_round_trips_and_reports_readiness(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFFvoice")
    store = VoiceProfileStore(tmp_path / "profiles")
    profile = VoiceProfile(
        id="atri",
        display_name="亚托莉",
        reference_audio=str(reference),
        prompt_text="今日はいい天気ですね。",
    )

    store.save(profile)
    loaded = store.load("atri")

    assert loaded == profile
    assert loaded.ready is True


def test_profile_rejects_directory_traversal(tmp_path: Path) -> None:
    store = VoiceProfileStore(tmp_path)

    with pytest.raises(ValueError):
        store.load("../outside")
    with pytest.raises(ValueError):
        profile_from_dict({"id": "../outside"})


def test_candidate_manifest_creates_separate_ready_profile(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidates" / "atri-model"
    candidate_dir.mkdir(parents=True)
    for name in ("gpt.ckpt", "sovits.pth", "reference.wav", "sad.wav"):
        (candidate_dir / name).write_bytes(b"model")
    (candidate_dir / "candidate.json").write_text(
        """{
          "id": "atri-model",
          "display_name": "ATRI Candidate",
          "declared_version": "v1",
          "declared_languages": ["zh", "en", "ja"],
          "gpt_weights": "gpt.ckpt",
          "sovits_weights": "sovits.pth",
          "reference_audio": "reference.wav",
          "prompt_text": "こんにちは",
          "prompt_language": "ja",
          "emotion_references": {"sad": "sad.wav"},
          "verified": true
        }""",
        encoding="utf-8",
    )
    candidates = load_voice_candidates(candidate_dir.parent)
    store = VoiceProfileStore(tmp_path / "profiles")

    assert candidates[0].ready is True
    assert candidates[0].emotion_references["sad"] == (candidate_dir / "sad.wav").resolve()
    # Install through a temporary registry-shaped root without changing user profiles.
    profile = VoiceProfile(
        id=candidates[0].profile_id,
        display_name=candidates[0].display_name,
        reference_audio=str(candidates[0].reference_audio),
        gpt_weights=str(candidates[0].gpt_weights),
        sovits_weights=str(candidates[0].sovits_weights),
    )
    store.save(profile)
    assert store.load("atri-model").ready is True


def test_gpt_sovits_switches_profile_weights_before_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = tmp_path / "reference.wav"
    gpt = tmp_path / "atri.ckpt"
    sovits = tmp_path / "atri.pth"
    for path in (reference, gpt, sovits):
        path.write_bytes(b"model")
    response_wav = tmp_path / "response.wav"
    _write_test_tone(response_wav, duration_seconds=0.5)
    calls: list[str] = []
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/tts":
            payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                content=response_wav.read_bytes(),
                headers={"content-type": "audio/wav"},
            )
        return httpx.Response(200, json={"message": "success"})

    real_client = httpx.AsyncClient

    def fake_client(*, timeout: float) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    profile = VoiceProfile(
        id="atri-test",
        display_name="ATRI",
        reference_audio=str(reference),
        gpt_weights=str(gpt),
        sovits_weights=str(sovits),
        auxiliary_references=[str(reference)],
    )
    provider = GptSovitsProvider(tmp_path / "cache")

    result = asyncio.run(provider.synthesize(VoiceRequest("你好", language="zh"), profile))

    assert result.audio_path.is_file()
    assert calls == ["/set_sovits_weights", "/set_gpt_weights", "/tts"]
    assert payloads[0]["text_lang"] == "zh"
    assert payloads[0]["speed_factor"] == 1.0
    assert payloads[0]["top_k"] == 5
    assert payloads[0]["top_p"] == pytest.approx(0.76)
    assert payloads[0]["temperature"] == pytest.approx(0.58)
    assert payloads[0]["repetition_penalty"] == pytest.approx(1.3)
    assert payloads[0]["text_split_method"] == "cut0"
    assert payloads[0]["parallel_infer"] is False
    assert payloads[0]["split_bucket"] is False
    assert payloads[0]["seed"] == 19
    assert payloads[0]["aux_ref_audio_paths"] == []


def test_gpt_sovits_provider_marks_gateway_failure_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = tmp_path / "reference.wav"
    gpt = tmp_path / "gpt.ckpt"
    sovits = tmp_path / "sovits.pth"
    for path in (reference, gpt, sovits):
        path.write_bytes(b"model")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tts":
            return httpx.Response(502, text="engine restarting", request=request)
        return httpx.Response(200, json={"message": "success"}, request=request)

    real_client = httpx.AsyncClient

    def fake_client(*, timeout: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    provider = GptSovitsProvider(tmp_path / "cache")
    profile = VoiceProfile(
        id="atri-test",
        display_name="ATRI",
        reference_audio=str(reference),
        gpt_weights=str(gpt),
        sovits_weights=str(sovits),
    )

    with pytest.raises(ProviderError) as captured:
        asyncio.run(
            provider.synthesize(
                VoiceRequest("测试语音", language="zh"),
                profile,
            )
        )

    assert captured.value.retryable is True
    assert "502" in str(captured.value)


def test_engine_weight_path_uses_ascii_model_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_root = tmp_path / "本地模型" / "AI_ATRI"
    ascii_root = tmp_path / "AtriModels"
    relative = Path("voice") / "candidate.pth"
    alias = ascii_root / relative
    alias.parent.mkdir(parents=True)
    alias.write_bytes(b"model")
    monkeypatch.setattr("atri_voice_service.providers.ATRI_MODELS_ROOT", model_root)
    monkeypatch.setattr("atri_voice_service.providers.ASCII_ATRI_MODELS_ROOT", ascii_root)

    assert _engine_weight_path(str(model_root / relative)) == str(alias)
    assert _engine_weight_path(str(tmp_path / "other.pth")) == str(tmp_path / "other.pth")


def test_tts_auto_language_detects_chinese_english_and_japanese() -> None:
    assert _tts_language("auto", "auto", "今天一起散步吧") == "zh"
    assert _tts_language("auto", "auto", "Let's stay together.") == "en"
    assert _tts_language("auto", "auto", "今日もそばにいます") == "ja"
    assert _tts_language("auto", "auto", "今天用 GPT 聊天") == "zh"
    assert _tts_language("en", "auto", "中文") == "en"


def test_tts_emotion_reference_uses_filename_as_matching_prompt(tmp_path: Path) -> None:
    neutral = tmp_path / "neutral.wav"
    sad = tmp_path / "悲しまないでください.wav"
    profile = VoiceProfile(
        id="atri",
        display_name="ATRI",
        reference_audio=str(neutral),
        prompt_text="普通です",
        prompt_language="ja",
        emotion_references={"sad": str(sad)},
    )

    assert _reference_context(profile, "sad") == (
        str(sad),
        "悲しまないでください",
        "ja",
    )
    assert _reference_context(profile, "happy") == (str(neutral), "普通です", "ja")


def test_tts_emotion_reference_prefers_configured_prompt_and_language(
    tmp_path: Path,
) -> None:
    neutral = tmp_path / "neutral.wav"
    happy = tmp_path / "happy.wav"
    profile = VoiceProfile(
        id="atri",
        display_name="ATRI",
        reference_audio=str(neutral),
        prompt_text="普通です",
        prompt_language="ja",
        emotion_references={"happy": str(happy)},
        emotion_prompt_texts={"happy": "えへへ、役に立つでしょう？"},
        emotion_prompt_languages={"happy": "ja"},
    )

    assert _reference_context(profile, "happy", "zh") == (
        str(happy),
        "えへへ、役に立つでしょう？",
        "ja",
    )


def test_tts_emotion_reference_uses_language_reference_as_auxiliary(
    tmp_path: Path,
) -> None:
    neutral = tmp_path / "neutral.wav"
    happy = tmp_path / "happy.wav"
    chinese = tmp_path / "chinese.wav"
    auxiliary = tmp_path / "auxiliary.wav"
    for path in (neutral, happy, chinese, auxiliary):
        path.write_bytes(b"audio")
    profile = VoiceProfile(
        id="atri",
        display_name="ATRI",
        reference_audio=str(neutral),
        emotion_references={"happy": str(happy)},
        language_references={"zh": str(chinese)},
        auxiliary_references=[str(auxiliary), str(chinese)],
    )

    assert _auxiliary_reference_paths(profile, str(happy), "happy", "zh") == [
        str(chinese),
        str(auxiliary),
    ]
    assert _auxiliary_reference_paths(profile, str(neutral), "neutral", "zh") == [
        str(auxiliary),
        str(chinese),
    ]


def test_tts_language_reference_selects_matching_prompt(tmp_path: Path) -> None:
    neutral = tmp_path / "neutral.wav"
    japanese = tmp_path / "japanese.wav"
    profile = VoiceProfile(
        id="atri",
        display_name="ATRI",
        reference_audio=str(neutral),
        prompt_text="default",
        prompt_language="ja",
        language_references={"ja": str(japanese)},
        language_prompt_texts={"ja": "おはようございます。"},
        language_prompt_languages={"ja": "ja"},
    )

    assert _reference_context(profile, "happy", "ja") == (
        str(japanese),
        "おはようございます。",
        "ja",
    )
    assert _reference_context(profile, "happy", "zh") == (str(neutral), "default", "ja")


def test_tts_style_uses_intensity_without_extreme_speed_changes() -> None:
    neutral = _tts_style("sad", 0.0)
    strong = _tts_style("sad", 1.0)
    expressive = _tts_style("happy", 1.0)

    assert neutral["speed_factor"] == 1.0
    assert neutral["temperature"] == pytest.approx(0.58)
    assert strong["speed_factor"] == 0.985
    assert strong["fragment_interval"] == 0.225
    assert strong["temperature"] == pytest.approx(0.54)
    assert expressive["top_k"] == 8
    assert expressive["top_p"] == pytest.approx(0.82)
    assert expressive["temperature"] == pytest.approx(0.64)


def test_tts_seed_is_stable_per_language() -> None:
    assert _tts_seed("zh") == 19
    assert _tts_seed("en") == 42
    assert _tts_seed("ja") == 42


def test_separator_resolves_relative_outputs_against_output_directory(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "stems"

    resolved = _resolve_output_paths(
        ["separated-vocal.wav", str((tmp_path / "absolute.wav").resolve())],
        output_dir,
    )

    assert resolved == [
        (output_dir / "separated-vocal.wav").resolve(),
        (tmp_path / "absolute.wav").resolve(),
    ]


def _write_test_tone(path: Path, *, duration_seconds: float) -> None:
    sample_rate = 44100
    frames = int(sample_rate * duration_seconds)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(5000 * math.sin(2 * math.pi * 220 * index / sample_rate)),
                )
                for index in range(frames)
            )
        )
