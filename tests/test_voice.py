from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from atri_qq_bot.config import load_config
from atri_qq_bot.config import BotConfig
from atri_qq_bot.message_plan import OutgoingMessage
from atri_qq_bot.onebot.server import OneBotServer
from atri_qq_bot.voice import (
    SpeechServiceClient,
    SpeechServiceError,
    SynthesisResult,
    TranscriptionResult,
    VoiceManager,
    VoiceCallStore,
    VoicePromptContext,
    VoiceRequest,
    build_autonomous_voice_fallback,
    build_explicit_voice_fallback,
    detect_explicit_delivery_intent,
    evaluate_call_request,
    evaluate_reply_voice_choice,
    evaluate_voice_request,
    stabilize_explicit_voice_request,
    find_record_segments,
    load_voice_behavior,
    save_voice_behavior,
    split_spoken_text,
)


def test_explicit_delivery_guard_detects_speech_singing_and_negation() -> None:
    assert detect_explicit_delivery_intent("鐢ㄨ闊冲洖澶嶆垜").mode == "speech"
    assert detect_explicit_delivery_intent("缁欐垜鍞变袱鍙ュ惂").mode == "singing"
    assert detect_explicit_delivery_intent("涓嶈鍙戣闊筹紝鎵撳瓧灏卞ソ") is None


def test_explicit_delivery_guard_builds_voice_request_from_model_reply() -> None:
    request = build_explicit_voice_fallback(
        "鍒墦瀛楋紝鍞变袱鍙ョ粰鎴戝惉",
        "**鏃╀笂濂?*锛屼粖澶╀篃瑕佸紑蹇冦€?,
        max_chars=160,
    )

    assert request is not None
    assert request.text == "鏃╀笂濂斤紝浠婂ぉ涔熻寮€蹇冦€?
    assert request.reason == "explicit_request"
    assert request.mode == "singing"
    assert request.emotion == "happy"


def test_explicit_delivery_guard_preserves_exact_requested_speech() -> None:
    request = build_explicit_voice_fallback(
        "@缇ゅ弸 鐢ㄨ闊宠鍜曞挄鍢庡槑",
        "鎴戝垏鍥炴甯镐腑鏂囷細鍒氭墠閭ｅ彞涓嶈涔遍銆?,
        max_chars=160,
    )

    assert request is not None
    assert request.text == "鍜曞挄鍢庡槑"
    assert request.mode == "speech"


def test_explicit_delivery_guard_overrides_unrelated_model_tool_text() -> None:
    request = stabilize_explicit_voice_request(
        "璇风敤璇煶璇存棭涓婂ソ",
        VoiceRequest("鎴戝凡缁忓噯澶囧ソ璇煶浜嗐€?, reason="explicit_request"),
        max_chars=160,
    )

    assert request.text == "鏃╀笂濂?
    assert request.reason == "explicit_request"
    assert request.mode == "speech"


def test_explicit_story_request_preserves_model_generated_story() -> None:
    request = stabilize_explicit_voice_request(
        "鐢ㄨ闊宠涓晠浜嬪惉鍚?,
        VoiceRequest(
            "浠庡墠鏈変釜灏忔満鍣ㄤ汉锛屽ス姣忓ぉ閮藉湪绛変富浜哄洖瀹躲€?,
            reason="explicit_request",
        ),
        max_chars=160,
    )

    assert request.text == "浠庡墠鏈変釜灏忔満鍣ㄤ汉锛屽ス姣忓ぉ閮藉湪绛変富浜哄洖瀹躲€?


def test_spoken_text_segmentation_prefers_sentences_and_clauses() -> None:
    text = (
        "鍡紝鐪嬫潵涓讳汉纭疄寰堢弽鎯滈偅浜涚焊鏉″憿銆?
        "灏忔満鍣ㄤ汉鍚庢潵鍙戠幇锛屼富浜烘妸姣忎竴寮犵焊鏉￠兘鎸夋棩鏈熸帓濂戒簡搴忥紝"
        "澶瑰湪閭ｆ湰鏈€鍠滄鐨勪功閲屸€斺€斿氨鏄皝闈笂鐢荤潃婕備寒浜哄奖鐨勯偅鏈€?
    )

    segments = split_spoken_text(text, maximum_units=26)

    assert segments == [
        "鍡€?,
        "鐪嬫潵涓讳汉纭疄寰堢弽鎯滈偅浜涚焊鏉″憿銆?,
        "灏忔満鍣ㄤ汉鍚庢潵鍙戠幇锛屼富浜烘妸姣忎竴寮犵焊鏉￠兘鎸夋棩鏈熸帓濂戒簡搴忥紝",
        "澶瑰湪閭ｆ湰鏈€鍠滄鐨勪功閲屸€斺€斿氨鏄皝闈笂鐢荤潃婕備寒浜哄奖鐨勯偅鏈€?,
    ]
    assert "".join(segments).replace("鍡€?, "鍡紝") == text


def test_spoken_text_segmentation_removes_bracket_fragments_across_segments() -> None:
    segments = split_spoken_text(
        "锛堝浘鐗囬噷鏄竴鍙櫧鑹茬殑灏忕尗锛屽渾婧滄簻鐨勭溂鐫涚洴鐫€鑽夎帗鐪嬨€傦級"
        "鍢垮樋锛岃繖鍙皬鐚儚涓嶅儚鎴戣鐪熻捣鏉ョ殑鏍峰瓙锛?,
        maximum_units=20,
    )

    assert segments
    assert all(not any(char in segment for char in "锛堬級()銆愩€慬]") for segment in segments)
    assert segments[-1].startswith("鍢垮樋")


def test_explicit_story_fallback_uses_generated_reply_not_request_fragment() -> None:
    request = build_explicit_voice_fallback(
        "鐢ㄨ闊宠涓晠浜嬪惉鍚?,
        "锛堣交澹拌鏁呬簨锛変粠鍓嶆湁涓皬鏈哄櫒浜猴紝濂逛綇鍦ㄦ捣杈广€?,
        max_chars=160,
    )

    assert request is not None
    assert request.text == "浠庡墠鏈変釜灏忔満鍣ㄤ汉锛屽ス浣忓湪娴疯竟銆?


@pytest.mark.parametrize(
    ("user_text", "reply_text", "expected"),
    [
        ("浠婂ぉ鎬庝箞鏍?, "鎵嶃€佹墠涓嶆槸鐗规剰涓轰綘鍑嗗鐨勫憿銆?, "shy"),
        ("鎴戝垰鎵嶈涓簡", "璇讹紵浣犲眳鐒剁湡鐨勭寽鍒颁簡锛?, "surprised"),
        ("鎴戝ソ闅惧彈", "鍏堟姳鎶变綘锛屾垜浠參鎱㈣銆?, "gentle"),
        ("妫€鏌ュ畬鎴愪簡鍚?, "濂借€讹紝宸茬粡鎴愬姛瀹屾垚鍟︼紒", "happy"),
        ("鐢ㄨ闊虫彁閱掓垜", "涓嶅彲浠ュ繕璁帮紝鍏堝惉鎴戣銆?, "serious"),
    ],
)
def test_autonomous_voice_fallback_matches_reply_emotion(
    user_text: str,
    reply_text: str,
    expected: str,
) -> None:
    request = build_autonomous_voice_fallback(
        user_text,
        reply_text,
        max_chars=160,
    )

    assert request is not None
    assert request.emotion == expected


def test_find_record_segments_keeps_only_usable_records() -> None:
    message = [
        {"type": "text", "data": {"text": "鍚竴涓?}},
        {"type": "record", "data": {"file": "voice.amr", "url": "https://example.test/a"}},
        {"type": "record", "data": {}},
    ]

    records = find_record_segments(message)

    assert len(records) == 1
    assert records[0].file == "voice.amr"
    assert records[0].url == "https://example.test/a"


def test_voice_request_normalizes_tool_arguments() -> None:
    request = VoiceRequest.from_tool_arguments(
        {
            "text": "  鏅氬畨锛屽仛涓ソ姊︺€? ",
            "emotion": "GENTLE",
            "intensity": 2,
            "language": "auto",
        },
        max_chars=80,
    )

    assert request.text == "鏅氬畨锛屽仛涓ソ姊︺€?
    assert request.emotion == "gentle"
    assert request.intensity == 1.0
    assert request.language == "auto"


def test_voice_request_rejects_empty_or_overlong_text() -> None:
    with pytest.raises(ValueError):
        VoiceRequest.from_tool_arguments({"text": "   "}, max_chars=20)
    with pytest.raises(ValueError):
        VoiceRequest.from_tool_arguments({"text": "澶? * 21}, max_chars=20)


def test_voice_behavior_round_trip_and_policy_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "voice_behavior.json"
    policy = save_voice_behavior(
        {
            "explicit_requests_enabled": True,
            "private_autonomous_enabled": True,
            "private_min_affection": 80,
            "private_min_messages": 10,
            "quiet_start": "00:30",
            "quiet_end": "07:00",
        },
        path,
    )

    assert load_voice_behavior(path) == policy
    profile = {"affection_score": 50, "message_count": 30}
    assert evaluate_voice_request(
        "private:1", profile, "explicit_request", policy
    ).allowed
    assert not evaluate_voice_request(
        "private:1", profile, "autonomous", policy
    ).allowed
    assert evaluate_voice_request(
        "group:7",
        {"group_activity_score": 0, "message_count": 0},
        "explicit_request",
        policy,
    ).allowed

    eligible = {"affection_score": 90, "message_count": 30}
    shanghai = timezone(timedelta(hours=8))
    daytime = datetime(2026, 7, 24, 12, 0, tzinfo=shanghai)
    quiet = datetime(2026, 7, 24, 1, 0, tzinfo=shanghai)
    assert evaluate_voice_request(
        "private:1", eligible, "autonomous", policy, daytime
    ).allowed
    assert not evaluate_voice_request(
        "private:1", eligible, "autonomous", policy, quiet
    ).allowed


def test_reply_voice_probability_controls_model_choice_without_blocking_requests() -> None:
    policy = load_voice_behavior(Path("missing-voice-behavior.json"))
    policy.update(
        {
            "reply_voice_probability": 35,
            "private_autonomous_enabled": True,
            "private_min_affection": 40,
            "private_min_messages": 5,
        }
    )
    profile = {"affection_score": 90, "message_count": 30}
    daytime = datetime(2026, 7, 24, 12, 0, tzinfo=timezone(timedelta(hours=8)))

    assert evaluate_reply_voice_choice(
        "private:1", profile, policy, random_value=0.2, now=daytime
    ).allowed
    assert not evaluate_reply_voice_choice(
        "private:1", profile, policy, random_value=0.5, now=daytime
    ).allowed

    policy["reply_voice_probability"] = 0
    assert evaluate_reply_voice_choice(
        "private:1",
        profile,
        policy,
        explicit_request=True,
        random_value=0.9,
        now=daytime,
    ).allowed

    policy["reply_voice_probability"] = 35
    assert not evaluate_reply_voice_choice(
        "private:1",
        profile,
        policy,
        random_value=0.6,
        now=daytime,
    ).allowed
    assert evaluate_reply_voice_choice(
        "private:1",
        profile,
        policy,
        emotional_context=True,
        random_value=0.6,
        now=daytime,
    ).allowed
    assert evaluate_reply_voice_choice(
        "private:1",
        profile,
        policy,
        replying_to_voice=True,
        random_value=0.9,
        now=daytime,
    ).allowed


def test_voice_call_policy_and_session_expiry() -> None:
    policy = load_voice_behavior(Path("missing-voice-behavior.json"))
    policy.update(
        {
            "calls_enabled": True,
            "call_min_affection": 80,
            "call_min_messages": 10,
            "call_base_url": "http://127.0.0.1:8787",
        }
    )
    assert evaluate_call_request(
        "private:42",
        {"affection_score": 90, "message_count": 20},
        policy,
    ).allowed
    assert not evaluate_call_request(
        "group:7",
        {"group_activity_score": 100, "message_count": 100},
        policy,
    ).allowed

    store = VoiceCallStore()
    session = store.create("private:42", "娴嬭瘯", 1, 30, now=1000)
    assert store.get(session.token, now=1059) is session
    assert store.get(session.token, now=1061) is None


def test_speech_client_parses_transcription_and_synthesis(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFFfake")
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    client = SpeechServiceClient("http://127.0.0.1:8790", timeout_seconds=5)
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((path, payload))
        if path.endswith("transcribe"):
            return {
                "ok": True,
                "text": "浠婂ぉ鏈夌偣绱?,
                "language": "zh",
                "emotion": "sad",
                "confidence": 0.91,
            }
        return {"ok": True, "audio_path": str(output), "duration_seconds": 2.4}

    monkeypatch.setattr(client, "_post_json", fake_post)

    transcript = asyncio.run(client.transcribe(audio))
    synthesis = asyncio.run(
        client.synthesize(VoiceRequest("鏃╃偣浼戞伅鍚с€?, "gentle", 0.7, "zh"), "atri")
    )

    assert transcript.text == "浠婂ぉ鏈夌偣绱?
    assert transcript.emotion == "sad"
    assert synthesis.audio_path == output
    assert synthesis.duration_seconds == 2.4
    assert [item[0] for item in calls] == ["/v1/transcribe", "/v1/synthesize"]


def test_speech_client_preserves_service_error_detail(monkeypatch) -> None:
    async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error": "瑙掕壊璇煶妗ｆ缂哄皯鍙傝€冮煶棰?,
                "quality": {"rejected": True, "error_rate": 0.5},
            },
            request=request,
        )

    def fake_client(*, timeout: float) -> httpx.AsyncClient:
        return async_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    client = SpeechServiceClient("http://127.0.0.1:8790", timeout_seconds=5)

    with pytest.raises(Exception, match="瑙掕壊璇煶妗ｆ缂哄皯鍙傝€冮煶棰?) as captured:
        asyncio.run(client.synthesize(VoiceRequest("娴嬭瘯璇煶"), "atri"))

    assert captured.value.quality == {"rejected": True, "error_rate": 0.5}


def test_speech_client_retries_transient_gateway_failure(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    async_client = httpx.AsyncClient
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(502, request=request)
        return httpx.Response(
            200,
            json={"ok": True, "audio_path": str(output)},
            request=request,
        )

    def fake_client(*, timeout: object) -> httpx.AsyncClient:
        return async_client(transport=httpx.MockTransport(handler), timeout=timeout)

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    client = SpeechServiceClient("http://127.0.0.1:8790", timeout_seconds=5)

    result = asyncio.run(client.synthesize(VoiceRequest("娴嬭瘯璇煶"), "atri"))

    assert attempts == 2
    assert result.audio_path == output


def test_voice_manager_resolves_napcat_record_and_transcribes(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFvoice")
    config = type(
        "Config",
        (),
        {
            "voice_asr_enabled": True,
            "voice_group_enabled": False,
            "voice_service_url": "http://127.0.0.1:8790",
            "voice_service_timeout_seconds": 5,
            "voice_input_max_bytes": 1_000_000,
        },
    )()
    manager = VoiceManager(config)
    calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(action: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((action, params))
        return {"status": "ok", "data": {"file": str(audio)}}

    async def transcribe(path: Path, language: str = "auto") -> TranscriptionResult:
        assert path == audio.resolve()
        return TranscriptionResult("浣犲ソ", "zh")

    manager.client.transcribe = transcribe  # type: ignore[method-assign]
    result = asyncio.run(
        manager.transcribe_event(
            {
                "message_type": "private",
                "message": [{"type": "record", "data": {"file": "abc.amr"}}],
            },
            call_action,
        )
    )

    assert result is not None and result.text == "浣犲ソ"
    assert calls == [("get_record", {"file": "abc.amr", "out_format": "wav"})]


def test_voice_manager_only_starts_cooldown_after_success(tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    output.write_bytes(b"RIFFvoice")
    config = type(
        "Config",
        (),
        {
            "voice_service_url": "http://127.0.0.1:8790",
            "voice_service_timeout_seconds": 5,
            "voice_profile": "atri",
            "voice_cooldown_seconds": 30,
        },
    )()
    manager = VoiceManager(config)
    request = VoiceRequest("浣犲ソ")

    async def synthesize(
        value: VoiceRequest,
        profile: str,
        **kwargs: object,
    ) -> SynthesisResult:
        assert value == request and profile == "atri"
        return SynthesisResult(output)

    manager.client.synthesize = synthesize  # type: ignore[method-assign]
    result = asyncio.run(manager.synthesize("private:1", request))

    assert result.audio_path == output
    with pytest.raises(Exception, match="鍐峰嵈"):
        asyncio.run(manager.synthesize("private:1", request))


def test_voice_manager_uses_chinese_rescue_profile_after_quality_rejection(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rescue.wav"
    output.write_bytes(b"RIFFvoice")
    config = type(
        "Config",
        (),
        {
            "voice_service_url": "http://127.0.0.1:8790",
            "voice_service_timeout_seconds": 5,
            "voice_profile": "atri-main",
            "voice_zh_rescue_profile": "atri-zh-rescue",
            "voice_cooldown_seconds": 30,
        },
    )()
    manager = VoiceManager(config)
    profiles: list[str] = []
    retry_counts: list[int] = []
    contextual_fallbacks: list[bool] = []
    best_effort_flags: list[bool] = []

    async def synthesize(
        request: VoiceRequest,
        profile: str,
        **kwargs: object,
    ) -> SynthesisResult:
        profiles.append(profile)
        retry_counts.append(int(kwargs["quality_retries"]))
        contextual_fallbacks.append(bool(kwargs["allow_context_original_fallback"]))
        best_effort_flags.append(bool(kwargs["allow_best_effort"]))
        if profile == "atri-main":
            raise SpeechServiceError(
                "璇煶鍥炶鏈揪鍒拌川閲忔爣鍑?,
                quality={"rejected": True, "error_rate": 1.0},
                status_code=400,
            )
        return SynthesisResult(
            output,
            quality={"passed": True, "error_rate": 0.0},
        )

    manager.client.synthesize = synthesize  # type: ignore[method-assign]
    result = asyncio.run(
        manager.synthesize(
            "private:1",
            VoiceRequest("鐐瑰埆鐨?, language="zh", reason="explicit_request"),
        )
    )

    assert profiles == ["atri-main", "atri-zh-rescue"]
    assert retry_counts == [3, 3]
    assert contextual_fallbacks == [True, True]
    assert best_effort_flags == [True, True]
    assert result.quality == {
        "passed": True,
        "error_rate": 0.0,
        "rescue_profile": "atri-zh-rescue",
    }


def test_voice_manager_does_not_substitute_a_system_voice_when_profiles_fail() -> None:
    config = type(
        "Config",
        (),
        {
            "voice_service_url": "http://127.0.0.1:8790",
            "voice_service_timeout_seconds": 5,
            "voice_profile": "atri-main",
            "voice_zh_rescue_profile": "atri-zh-rescue",
            "voice_cooldown_seconds": 30,
        },
    )()
    manager = VoiceManager(config)
    profiles: list[str] = []

    async def failed_synthesis(
        request: VoiceRequest,
        profile: str,
        **kwargs: object,
    ) -> SynthesisResult:
        profiles.append(profile)
        raise SpeechServiceError(
            f"{profile} failed",
            quality={"rejected": True, "error_rate": 1.0},
            status_code=400,
        )

    manager.client.synthesize = failed_synthesis  # type: ignore[method-assign]

    with pytest.raises(SpeechServiceError, match="涓枃鏁戞彺妗ｆ涔熸湭閫氳繃"):
        asyncio.run(
            manager.synthesize(
                "private:1",
                VoiceRequest("鏃╁畨", language="zh", reason="explicit_request"),
            )
        )

    assert profiles == ["atri-main", "atri-zh-rescue"]
    assert not hasattr(manager, "system_fallback")


def test_voice_prompt_context_preserves_material_and_voice_preference() -> None:
    class Material:
        def prompt_context(self) -> str:
            return "澶栭儴鏉愭枡鍐呭"

    context = VoicePromptContext(
        TranscriptionResult("浠婂ぉ鏈夌偣绱?, "zh", "sad"),
        material_context=Material(),
        prefer_voice_reply=True,
    )

    prompt = context.prompt_context()
    assert "澶栭儴鏉愭枡鍐呭" in prompt
    assert "浠婂ぉ鏈夌偣绱? in prompt
    assert "speak_as_atri" in prompt


def test_onebot_server_sends_synthesized_voice_record(tmp_path: Path) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        sticker_capture_enabled=False,
    )

    class FakeEngine:
        memory = SimpleNamespace()

        def remember_target(self, *args: object) -> None:
            return None

        def observe_incoming(self, *args: object, **kwargs: object) -> None:
            return None

        async def reply(self, *args: object, **kwargs: object) -> str:
            return "璇煶宸插噯澶囥€?

        def consume_voice_request(self, conversation_id: str) -> VoiceRequest:
            assert conversation_id == "private:10001"
            return VoiceRequest("鎴戝凡缁忔妸璇煶鍑嗗濂戒簡銆?, "gentle")

        def record_bot_reply(self, *args: object, **kwargs: object) -> None:
            return None

        def profile_for(self, conversation_id: str) -> dict[str, object]:
            return {}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    server = OneBotServer(config, FakeEngine())  # type: ignore[arg-type]

    async def analyze(*args: object, **kwargs: object) -> None:
        return None

    async def synthesize(conversation_id: str, request: VoiceRequest) -> SynthesisResult:
        assert conversation_id == "private:10001"
        assert request.text == "鏅氬畨"
        return SynthesisResult(output)

    server.tools.analyze = analyze  # type: ignore[method-assign]
    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    websocket = FakeWebSocket()

    async def confirmed_action(
        socket: object,
        action: str,
        params: dict[str, object],
        timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        await socket.send(
            json.dumps({"action": action, "params": params}, ensure_ascii=False)  # type: ignore[attr-defined]
        )
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    server.call_action_and_wait = confirmed_action  # type: ignore[method-assign]
    asyncio.run(
        server._handle_event(
            websocket,
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": config.bot_qq,
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "鐢ㄨ闊宠鏅氬畨"}}],
                "sender": {"nickname": "涓讳汉"},
            },
        )
    )

    payload = json.loads(websocket.sent[-1])
    assert payload["action"] == "send_private_msg"
    assert payload["params"]["message"] == [
        {"type": "record", "data": {"file": str(output), "cache": 0}}
    ]


def test_onebot_explicit_voice_guard_recovers_when_model_omits_tool(tmp_path: Path) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        sticker_capture_enabled=False,
    )

    class FakeEngine:
        memory = SimpleNamespace()

        def remember_target(self, *args: object) -> None:
            return None

        def observe_incoming(self, *args: object, **kwargs: object) -> None:
            return None

        async def reply(self, *args: object, **kwargs: object) -> str:
            return "鏅氬畨锛屽仛涓ソ姊︺€?

        def consume_voice_request(self, conversation_id: str) -> None:
            return None

        def record_bot_reply(self, *args: object, **kwargs: object) -> None:
            return None

        def profile_for(self, conversation_id: str) -> dict[str, object]:
            return {"affection_score": 0, "message_count": 0}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    server = OneBotServer(config, FakeEngine())  # type: ignore[arg-type]

    async def analyze(*args: object, **kwargs: object) -> None:
        return None

    async def synthesize(conversation_id: str, request: VoiceRequest) -> SynthesisResult:
        assert conversation_id == "private:10001"
        assert request.text == "鏅氬畨锛屽仛涓ソ姊︺€?
        assert request.reason == "explicit_request"
        return SynthesisResult(output)

    server.tools.analyze = analyze  # type: ignore[method-assign]
    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    websocket = FakeWebSocket()

    async def confirmed_action(
        socket: object,
        action: str,
        params: dict[str, object],
        timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        await socket.send(
            json.dumps({"action": action, "params": params}, ensure_ascii=False)  # type: ignore[attr-defined]
        )
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    server.call_action_and_wait = confirmed_action  # type: ignore[method-assign]
    asyncio.run(
        server._handle_event(
            websocket,
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": config.bot_qq,
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "鐢ㄨ闊冲洖澶嶆垜"}}],
                "sender": {"nickname": "涓讳汉"},
            },
        )
    )

    payload = json.loads(websocket.sent[-1])
    assert payload["params"]["message"][0]["type"] == "record"


def test_onebot_streams_long_voice_as_each_segment_is_synthesized(
    tmp_path: Path,
) -> None:
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        voice_segment_max_chars=24,
    )
    server = OneBotServer(config, SimpleNamespace(memory=SimpleNamespace()))  # type: ignore[arg-type]
    events: list[str] = []
    cooldown_flags: list[bool] = []

    async def synthesize(
        conversation_id: str,
        request: VoiceRequest,
        enforce_cooldown: bool = True,
    ) -> SynthesisResult:
        cooldown_flags.append(enforce_cooldown)
        events.append(f"synthesize:{request.text}")
        output = tmp_path / f"segment-{len(cooldown_flags)}.wav"
        output.write_bytes(b"RIFFvoice")
        return SynthesisResult(output)

    async def send_one(
        websocket: object,
        event: dict[str, object],
        message: OutgoingMessage,
    ) -> None:
        events.append(f"send:{message.kind}:{Path(message.content).name}")

    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    server._send_one_reply = send_one  # type: ignore[method-assign]
    text = (
        "鍏堣绗竴浠朵簨锛屾垜浠妸浠婂ぉ鐨勪换鍔℃暣鐞嗗ソ銆?
        "鐒跺悗鍐嶆參鎱紤鎭紝涓嶉渶瑕佷竴涓嬪瓙鍏ㄩ儴鍋氬畬銆?
    )

    delivered = asyncio.run(
        server._send_streamed_speech_reply(
            object(),
            {"message_type": "private", "user_id": 10001},
            "private:10001",
            VoiceRequest(text, language="zh"),
        )
    )

    assert delivered == text
    assert cooldown_flags == [True, False]
    assert [item.split(":", 1)[0] for item in events] == [
        "synthesize",
        "send",
        "synthesize",
        "send",
    ]


def test_onebot_streams_expressive_text_and_only_falls_back_failed_segments(
    tmp_path: Path,
) -> None:
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        voice_group_enabled=True,
        message_send_delay_min=0,
        message_send_delay_max=0,
    )
    server = OneBotServer(config, SimpleNamespace(memory=SimpleNamespace()))  # type: ignore[arg-type]
    sent: list[OutgoingMessage] = []
    synthesized: list[str] = []

    async def synthesize(
        conversation_id: str,
        request: VoiceRequest,
        enforce_cooldown: bool = True,
    ) -> SynthesisResult:
        synthesized.append(request.text)
        if request.text in {"鍝掑搾鍝掑搾", "鍛滃憸鍛?}:
            raise SpeechServiceError(
                "璇煶鍥炶鏈揪鍒拌川閲忔爣鍑嗭紝宸叉嫆缁濆彂閫侊紙閿欒鐜?80%锛?,
                quality={"rejected": True, "error_rate": 0.8},
                status_code=400,
            )
        output = tmp_path / f"segment-{len(synthesized)}.wav"
        output.write_bytes(b"RIFFvoice")
        return SynthesisResult(output)

    async def send_one(
        websocket: object,
        event: dict[str, object],
        message: OutgoingMessage,
    ) -> None:
        sent.append(message)

    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    server._send_one_reply = send_one  # type: ignore[method-assign]
    text = "鍝掑搾鍝掑搾锛屽ソ鎯崇帺鍘熺鍛滃憸鍛滐紝鐪嬩簯褰╃激绾?

    delivered = asyncio.run(
        server._send_streamed_speech_reply(
            object(),
            {
                "message_type": "group",
                "group_id": 1076073703,
                "user_id": 3187537485,
            },
            "group:1076073703",
            VoiceRequest(text, language="zh"),
        )
    )

    assert delivered == text
    assert synthesized == ["鍝掑搾鍝掑搾", "濂芥兂鐜╁師绁?, "鍛滃憸鍛?, "鐪嬩簯褰╃激绾?]
    assert [message.kind for message in sent] == [
        "text",
        "text",
        "record",
        "text",
        "record",
    ]
    assert sent[0].content == "鏈変竴灏忔璇煶娌″悎鎴愬ソ锛屾敼鐢ㄦ枃瀛椼€?
    assert sent[1].content == "鍝掑搾鍝掑搾"
    assert sent[3].content == "鍛滃憸鍛?
    assert all("閿欒鐜? not in message.content for message in sent)


def test_onebot_service_failure_sends_readable_remaining_text(
    tmp_path: Path,
) -> None:
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        voice_group_enabled=True,
        message_send_delay_min=0,
        message_send_delay_max=0,
    )
    server = OneBotServer(config, SimpleNamespace(memory=SimpleNamespace()))  # type: ignore[arg-type]
    sent: list[OutgoingMessage] = []

    async def synthesize(
        conversation_id: str,
        request: VoiceRequest,
        enforce_cooldown: bool = True,
    ) -> SynthesisResult:
        if request.text == "鍝掑搾鍝掑搾":
            output = tmp_path / "first.wav"
            output.write_bytes(b"RIFFvoice")
            return SynthesisResult(output)
        raise SpeechServiceError("璇煶鏈嶅姟杩炴帴澶辫触")

    async def send_one(
        websocket: object,
        event: dict[str, object],
        message: OutgoingMessage,
    ) -> None:
        sent.append(message)

    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    server._send_one_reply = send_one  # type: ignore[method-assign]

    asyncio.run(
        server._send_streamed_speech_reply(
            object(),
            {
                "message_type": "group",
                "group_id": 1076073703,
                "user_id": 3187537485,
            },
            "group:1076073703",
            VoiceRequest(
                "鍝掑搾鍝掑搾锛屽ソ鎯崇帺鍘熺鍛滃憸鍛滐紝鐪嬩簯褰╃激绾?,
                language="zh",
            ),
        )
    )

    assert [message.kind for message in sent] == ["record", "text", "text"]
    assert sent[1].content == "鏈変竴灏忔璇煶娌″悎鎴愬ソ锛屾敼鐢ㄦ枃瀛椼€?
    assert sent[2].content == "濂芥兂鐜╁師绁烇紝鍛滃憸鍛滐紝鐪嬩簯褰╃激绾?


def test_onebot_probability_choice_converts_natural_reply_to_voice(
    tmp_path: Path,
) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        sticker_capture_enabled=False,
    )

    class FakeEngine:
        memory = SimpleNamespace()

        def remember_target(self, *args: object) -> None:
            return None

        def observe_incoming(self, *args: object, **kwargs: object) -> None:
            return None

        async def reply(self, *args: object, **kwargs: object) -> str:
            return "锛堣交澹帮級鏅氬畨锛屼粖澶╄緵鑻︿簡銆?

        def consume_voice_request(self, conversation_id: str) -> None:
            return None

        def consume_reply_voice_choice(self, conversation_id: str) -> bool:
            assert conversation_id == "private:10001"
            return True

        def record_bot_reply(self, *args: object, **kwargs: object) -> None:
            return None

        def profile_for(self, conversation_id: str) -> dict[str, object]:
            return {"affection_score": 90, "message_count": 30}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    server = OneBotServer(config, FakeEngine())  # type: ignore[arg-type]

    async def analyze(*args: object, **kwargs: object) -> None:
        return None

    async def synthesize(conversation_id: str, request: VoiceRequest) -> SynthesisResult:
        assert request.text == "鏅氬畨锛屼粖澶╄緵鑻︿簡銆?
        assert request.reason == "autonomous"
        assert request.emotion == "sleepy"
        return SynthesisResult(output)

    server.tools.analyze = analyze  # type: ignore[method-assign]
    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    websocket = FakeWebSocket()

    async def confirmed_action(
        socket: object,
        action: str,
        params: dict[str, object],
        timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        await socket.send(
            json.dumps({"action": action, "params": params}, ensure_ascii=False)  # type: ignore[attr-defined]
        )
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    server.call_action_and_wait = confirmed_action  # type: ignore[method-assign]
    asyncio.run(
        server._handle_event(
            websocket,
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": config.bot_qq,
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "鎴戝噯澶囩潯浜?}}],
                "sender": {"nickname": "涓讳汉"},
            },
        )
    )

    payload = json.loads(websocket.sent[-1])
    assert payload["params"]["message"] == [
        {"type": "record", "data": {"file": str(output), "cache": 0}}
    ]


def test_onebot_record_send_requires_successful_napcat_receipt(tmp_path: Path) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
    )
    server = OneBotServer(config, SimpleNamespace(memory=SimpleNamespace()))  # type: ignore[arg-type]

    async def rejected_action(
        socket: object,
        action: str,
        params: dict[str, object],
        timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        return {"status": "failed", "retcode": 1200, "message": "record upload failed"}

    server.call_action_and_wait = rejected_action  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="record upload failed"):
        asyncio.run(
            server._send_one_reply(
                SimpleNamespace(),
                {"message_type": "private", "user_id": 10001},
                SimpleNamespace(kind="record", content=str(output)),
            )
        )


def test_onebot_singing_failure_does_not_send_generic_model_fallback() -> None:
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
        voice_tts_enabled=True,
        sticker_capture_enabled=False,
    )

    class FakeEngine:
        memory = SimpleNamespace()

        def __init__(self) -> None:
            self.recorded_replies: list[str] = []

        def remember_target(self, *args: object) -> None:
            return None

        def observe_incoming(self, *args: object, **kwargs: object) -> None:
            return None

        async def reply(self, *args: object, **kwargs: object) -> str:
            return "濂藉憖锛屾垜鐜板湪灏卞敱缁欎富浜哄惉锝炩櫔 鍟﹀暒鍟︹€︹€?

        def consume_voice_request(self, conversation_id: str) -> None:
            return None

        def record_bot_reply(
            self,
            conversation_id: str,
            reply_text: str,
            *args: object,
            **kwargs: object,
        ) -> None:
            self.recorded_replies.append(reply_text)

        def profile_for(self, conversation_id: str) -> dict[str, object]:
            return {"affection_score": 0, "message_count": 0}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, payload: str) -> None:
            self.sent.append(payload)

    fake_engine = FakeEngine()
    server = OneBotServer(config, fake_engine)  # type: ignore[arg-type]

    async def analyze(*args: object, **kwargs: object) -> None:
        return None

    async def synthesize(conversation_id: str, request: VoiceRequest) -> SynthesisResult:
        assert request.mode == "singing"
        raise RuntimeError("no singing clip")

    server.tools.analyze = analyze  # type: ignore[method-assign]
    server.voice.synthesize = synthesize  # type: ignore[method-assign]
    websocket = FakeWebSocket()
    asyncio.run(
        server._handle_event(
            websocket,
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": config.bot_qq,
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "鍞辨瓕"}}],
                "sender": {"nickname": "涓讳汉"},
            },
        )
    )

    payload = json.loads(websocket.sent[-1])
    text = payload["params"]["message"]
    assert "鍟﹀暒鍟? not in text
    assert text == "杩欐姝屽０娌℃湁鐢熸垚鎴愬姛銆?
    assert fake_engine.recorded_replies
    assert fake_engine.recorded_replies[-1] == "杩欐姝屽０娌℃湁鐢熸垚鎴愬姛銆?
    assert "鍟﹀暒鍟? not in fake_engine.recorded_replies[-1]


def test_voice_send_failure_uses_separate_brief_notice_and_text_fallback() -> None:
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key="test",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=200,
    )
    server = OneBotServer(
        config,
        SimpleNamespace(memory=SimpleNamespace()),
    )  # type: ignore[arg-type]
    sent: list[OutgoingMessage] = []

    async def fake_send(websocket: object, event: dict[str, object], message: OutgoingMessage) -> None:
        if not sent:
            sent.append(message)
            raise RuntimeError("NapCat retcode=1200")
        sent.append(message)

    server._send_one_reply = fake_send  # type: ignore[method-assign]
    asyncio.run(
        server.send_reply(
            object(),
            {"message_type": "private", "user_id": 10001},
            [OutgoingMessage("record", "voice.wav")],
            fallback_text="鏅氬畨锛屽仛涓ソ姊︺€?,
        )
    )

    assert len(sent) == 3
    assert sent[1].kind == "text"
    assert sent[1].content == "璇煶娌℃湁鍙戦€佹垚鍔熴€?
    assert sent[2] == OutgoingMessage("text", "鏅氬畨锛屽仛涓ソ姊︺€?)
    assert "NapCat" not in sent[1].content


def test_voice_config_is_disabled_by_default_and_can_be_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in (
        "VOICE_ASR_ENABLED",
        "VOICE_TTS_ENABLED",
        "VOICE_SERVICE_URL",
        "VOICE_MAX_CHARS",
        "VOICE_REPLY_TO_VOICE",
    ):
        monkeypatch.delenv(key, raising=False)
    env_path = tmp_path / "voice.env"
    env_path.write_text(
        "\n".join(
            [
                "VOICE_ASR_ENABLED=true",
                "VOICE_TTS_ENABLED=true",
                "VOICE_SERVICE_URL=http://127.0.0.1:9000/",
                "VOICE_MAX_CHARS=220",
                "VOICE_REPLY_TO_VOICE=true",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env_path)

    assert config.voice_asr_enabled is True
    assert config.voice_tts_enabled is True
    assert config.voice_service_url == "http://127.0.0.1:9000"
    assert config.voice_service_timeout_seconds == 180.0
    assert config.voice_max_chars == 220
    assert config.voice_reply_to_voice is True
