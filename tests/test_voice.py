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
    assert detect_explicit_delivery_intent("用语音回复我").mode == "speech"
    assert detect_explicit_delivery_intent("给我唱两句吧").mode == "singing"
    assert detect_explicit_delivery_intent("不要发语音，打字就好") is None


def test_explicit_delivery_guard_builds_voice_request_from_model_reply() -> None:
    request = build_explicit_voice_fallback(
        "别打字，唱两句给我听",
        "**早上好**，今天也要开心。",
        max_chars=160,
    )

    assert request is not None
    assert request.text == "早上好，今天也要开心。"
    assert request.reason == "explicit_request"
    assert request.mode == "singing"
    assert request.emotion == "happy"


def test_explicit_delivery_guard_preserves_exact_requested_speech() -> None:
    request = build_explicit_voice_fallback(
        "@群友 用语音说咕咕嘎嘎",
        "我切回正常中文：刚才那句不该乱飘。",
        max_chars=160,
    )

    assert request is not None
    assert request.text == "咕咕嘎嘎"
    assert request.mode == "speech"


def test_explicit_delivery_guard_overrides_unrelated_model_tool_text() -> None:
    request = stabilize_explicit_voice_request(
        "请用语音说早上好",
        VoiceRequest("我已经准备好语音了。", reason="explicit_request"),
        max_chars=160,
    )

    assert request.text == "早上好"
    assert request.reason == "explicit_request"
    assert request.mode == "speech"


def test_explicit_story_request_preserves_model_generated_story() -> None:
    request = stabilize_explicit_voice_request(
        "用语音讲个故事听听",
        VoiceRequest(
            "从前有个小机器人，她每天都在等主人回家。",
            reason="explicit_request",
        ),
        max_chars=160,
    )

    assert request.text == "从前有个小机器人，她每天都在等主人回家。"


def test_spoken_text_segmentation_prefers_sentences_and_clauses() -> None:
    text = (
        "嗯，看来主人确实很珍惜那些纸条呢。"
        "小机器人后来发现，主人把每一张纸条都按日期排好了序，"
        "夹在那本最喜欢的书里——就是封面上画着漂亮人影的那本。"
    )

    segments = split_spoken_text(text, maximum_units=26)

    assert segments == [
        "嗯。",
        "看来主人确实很珍惜那些纸条呢。",
        "小机器人后来发现，主人把每一张纸条都按日期排好了序，",
        "夹在那本最喜欢的书里——就是封面上画着漂亮人影的那本。",
    ]
    assert "".join(segments).replace("嗯。", "嗯，") == text


def test_spoken_text_segmentation_removes_bracket_fragments_across_segments() -> None:
    segments = split_spoken_text(
        "（图片里是一只白色的小猫，圆溜溜的眼睛盯着草莓看。）"
        "嘿嘿，这只小猫像不像我认真起来的样子？",
        maximum_units=20,
    )

    assert segments
    assert all(not any(char in segment for char in "（）()【】[]") for segment in segments)
    assert segments[-1].startswith("嘿嘿")


def test_explicit_story_fallback_uses_generated_reply_not_request_fragment() -> None:
    request = build_explicit_voice_fallback(
        "用语音讲个故事听听",
        "（轻声讲故事）从前有个小机器人，她住在海边。",
        max_chars=160,
    )

    assert request is not None
    assert request.text == "从前有个小机器人，她住在海边。"


@pytest.mark.parametrize(
    ("user_text", "reply_text", "expected"),
    [
        ("今天怎么样", "才、才不是特意为你准备的呢。", "shy"),
        ("我刚才说中了", "诶？你居然真的猜到了？", "surprised"),
        ("我好难受", "先抱抱你，我们慢慢说。", "gentle"),
        ("检查完成了吗", "好耶，已经成功完成啦！", "happy"),
        ("用语音提醒我", "不可以忘记，先听我说。", "serious"),
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
        {"type": "text", "data": {"text": "听一下"}},
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
            "text": "  晚安，做个好梦。  ",
            "emotion": "GENTLE",
            "intensity": 2,
            "language": "auto",
        },
        max_chars=80,
    )

    assert request.text == "晚安，做个好梦。"
    assert request.emotion == "gentle"
    assert request.intensity == 1.0
    assert request.language == "auto"


def test_voice_request_rejects_empty_or_overlong_text() -> None:
    with pytest.raises(ValueError):
        VoiceRequest.from_tool_arguments({"text": "   "}, max_chars=20)
    with pytest.raises(ValueError):
        VoiceRequest.from_tool_arguments({"text": "太" * 21}, max_chars=20)


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
    session = store.create("private:42", "测试", 1, 30, now=1000)
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
                "text": "今天有点累",
                "language": "zh",
                "emotion": "sad",
                "confidence": 0.91,
            }
        return {"ok": True, "audio_path": str(output), "duration_seconds": 2.4}

    monkeypatch.setattr(client, "_post_json", fake_post)

    transcript = asyncio.run(client.transcribe(audio))
    synthesis = asyncio.run(
        client.synthesize(VoiceRequest("早点休息吧。", "gentle", 0.7, "zh"), "atri")
    )

    assert transcript.text == "今天有点累"
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
                "error": "角色语音档案缺少参考音频",
                "quality": {"rejected": True, "error_rate": 0.5},
            },
            request=request,
        )

    def fake_client(*, timeout: float) -> httpx.AsyncClient:
        return async_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    client = SpeechServiceClient("http://127.0.0.1:8790", timeout_seconds=5)

    with pytest.raises(Exception, match="角色语音档案缺少参考音频") as captured:
        asyncio.run(client.synthesize(VoiceRequest("测试语音"), "atri"))

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

    result = asyncio.run(client.synthesize(VoiceRequest("测试语音"), "atri"))

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
        return TranscriptionResult("你好", "zh")

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

    assert result is not None and result.text == "你好"
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
    request = VoiceRequest("你好")

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
    with pytest.raises(Exception, match="冷却"):
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
                "语音回读未达到质量标准",
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
            VoiceRequest("点别的", language="zh", reason="explicit_request"),
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

    with pytest.raises(SpeechServiceError, match="中文救援档案也未通过"):
        asyncio.run(
            manager.synthesize(
                "private:1",
                VoiceRequest("早安", language="zh", reason="explicit_request"),
            )
        )

    assert profiles == ["atri-main", "atri-zh-rescue"]
    assert not hasattr(manager, "system_fallback")


def test_voice_prompt_context_preserves_material_and_voice_preference() -> None:
    class Material:
        def prompt_context(self) -> str:
            return "外部材料内容"

    context = VoicePromptContext(
        TranscriptionResult("今天有点累", "zh", "sad"),
        material_context=Material(),
        prefer_voice_reply=True,
    )

    prompt = context.prompt_context()
    assert "外部材料内容" in prompt
    assert "今天有点累" in prompt
    assert "speak_as_atri" in prompt


def test_onebot_server_sends_synthesized_voice_record(tmp_path: Path) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    config = BotConfig(
        bot_qq=100000001,
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
            return "语音已准备。"

        def consume_voice_request(self, conversation_id: str) -> VoiceRequest:
            assert conversation_id == "private:10001"
            return VoiceRequest("我已经把语音准备好了。", "gentle")

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
        assert request.text == "晚安"
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
                "message": [{"type": "text", "data": {"text": "用语音说晚安"}}],
                "sender": {"nickname": "主人"},
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
        bot_qq=100000001,
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
            return "晚安，做个好梦。"

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
        assert request.text == "晚安，做个好梦。"
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
                "message": [{"type": "text", "data": {"text": "用语音回复我"}}],
                "sender": {"nickname": "主人"},
            },
        )
    )

    payload = json.loads(websocket.sent[-1])
    assert payload["params"]["message"][0]["type"] == "record"


def test_onebot_streams_long_voice_as_each_segment_is_synthesized(
    tmp_path: Path,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
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
        "先讲第一件事，我们把今天的任务整理好。"
        "然后再慢慢休息，不需要一下子全部做完。"
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
        bot_qq=100000001,
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
        if request.text in {"哒哒哒哒", "呜呜呜"}:
            raise SpeechServiceError(
                "语音回读未达到质量标准，已拒绝发送（错误率 80%）",
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
    text = "哒哒哒哒，好想玩原神呜呜呜，看云彩缤纷"

    delivered = asyncio.run(
        server._send_streamed_speech_reply(
            object(),
            {
                "message_type": "group",
                "group_id": 1076073703,
                "user_id": 100000002,
            },
            "group:1076073703",
            VoiceRequest(text, language="zh"),
        )
    )

    assert delivered == text
    assert synthesized == ["哒哒哒哒", "好想玩原神", "呜呜呜", "看云彩缤纷"]
    assert [message.kind for message in sent] == [
        "text",
        "text",
        "record",
        "text",
        "record",
    ]
    assert sent[0].content == "有一小段语音没合成好，改用文字。"
    assert sent[1].content == "哒哒哒哒"
    assert sent[3].content == "呜呜呜"
    assert all("错误率" not in message.content for message in sent)


def test_onebot_service_failure_sends_readable_remaining_text(
    tmp_path: Path,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
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
        if request.text == "哒哒哒哒":
            output = tmp_path / "first.wav"
            output.write_bytes(b"RIFFvoice")
            return SynthesisResult(output)
        raise SpeechServiceError("语音服务连接失败")

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
                "user_id": 100000002,
            },
            "group:1076073703",
            VoiceRequest(
                "哒哒哒哒，好想玩原神呜呜呜，看云彩缤纷",
                language="zh",
            ),
        )
    )

    assert [message.kind for message in sent] == ["record", "text", "text"]
    assert sent[1].content == "有一小段语音没合成好，改用文字。"
    assert sent[2].content == "好想玩原神，呜呜呜，看云彩缤纷"


def test_onebot_probability_choice_converts_natural_reply_to_voice(
    tmp_path: Path,
) -> None:
    output = tmp_path / "atri.wav"
    output.write_bytes(b"RIFFvoice")
    config = BotConfig(
        bot_qq=100000001,
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
            return "（轻声）晚安，今天辛苦了。"

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
        assert request.text == "晚安，今天辛苦了。"
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
                "message": [{"type": "text", "data": {"text": "我准备睡了"}}],
                "sender": {"nickname": "主人"},
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
        bot_qq=100000001,
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
        bot_qq=100000001,
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
            return "好呀，我现在就唱给主人听～♪ 啦啦啦……"

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

    async def successful_action(
        target: FakeWebSocket,
        action: str,
        params: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        await target.send(
            json.dumps(
                {"action": action, "params": params, "echo": "test-send"},
                ensure_ascii=False,
            )
        )
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    server.call_action_and_wait = successful_action  # type: ignore[method-assign]
    asyncio.run(
        server._handle_event(
            websocket,
            {
                "post_type": "message",
                "message_type": "private",
                "self_id": config.bot_qq,
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "唱歌"}}],
                "sender": {"nickname": "主人"},
            },
        )
    )

    payload = json.loads(websocket.sent[-1])
    text = payload["params"]["message"]
    assert "啦啦啦" not in text
    assert text == "这次歌声没有生成成功。"
    assert fake_engine.recorded_replies
    assert fake_engine.recorded_replies[-1] == "这次歌声没有生成成功。"
    assert "啦啦啦" not in fake_engine.recorded_replies[-1]


def test_voice_send_failure_uses_separate_brief_notice_and_text_fallback() -> None:
    config = BotConfig(
        bot_qq=100000001,
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
            fallback_text="晚安，做个好梦。",
        )
    )

    assert len(sent) == 3
    assert sent[1].kind == "text"
    assert sent[1].content == "语音没有发送成功。"
    assert sent[2].kind == "text"
    assert sent[2].content == "晚安，做个好梦。"


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
