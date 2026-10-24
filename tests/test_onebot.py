import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from atri_qq_bot.message_plan import OutgoingMessage
from atri_qq_bot.onebot import (
    _merge_message_batch,
    extract_plain_text,
    extract_reply_message_id,
    normalize_poke_event,
    should_reply,
)
from atri_qq_bot.onebot.server import (
    OneBotServer,
    _compose_model_input,
    _event_has_visual_material,
    _is_visual_followup,
    _merge_pending_visual_event,
    _pending_visual_key,
    _should_reuse_cached_visual,
    _onebot_status_is_healthy,
)
from atri_qq_bot.voice import SynthesisResult, VoiceRequest


def test_onebot_status_probe_requires_real_online_and_good_flags() -> None:
    assert _onebot_status_is_healthy(
        {"status": "ok", "retcode": 0, "data": {"online": True, "good": True}}
    )
    assert not _onebot_status_is_healthy(
        {"status": "ok", "retcode": 0, "data": {"online": False, "good": True}}
    )
    assert not _onebot_status_is_healthy(
        {"status": "ok", "retcode": 0, "data": {"online": True, "good": False}}
    )


def test_conversational_tts_has_no_second_fixed_onebot_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    output = tmp_path / "speech.wav"
    output.write_bytes(b"RIFFvoice")
    server = object.__new__(OneBotServer)

    class FakeVoice:
        async def synthesize(self, *args, **kwargs):
            await asyncio.sleep(0.02)
            return SynthesisResult(output)

    server.voice = FakeVoice()
    monkeypatch.setattr(
        "atri_qq_bot.onebot.server.VOICE_SEGMENT_SYNTH_TIMEOUT_SECONDS",
        0.001,
        raising=False,
    )

    result = asyncio.run(
        server._synthesize_voice_segment(
            "private:10001",
            VoiceRequest("早安", reason="explicit_request"),
            enforce_cooldown=True,
        )
    )

    assert result.audio_path == output


def test_send_group_summary_uses_its_own_delivery_context(tmp_path) -> None:
    server = object.__new__(OneBotServer)
    websocket = object()
    server._active_websockets = {websocket}
    summary_path = tmp_path / "summary.png"
    summary_path.write_bytes(b"summary")
    captured: dict[str, object] = {}

    async def confirmed_action(target, action, params, timeout_seconds):
        captured.update(
            target=target,
            action=action,
            params=params,
            timeout_seconds=timeout_seconds,
        )
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    server.call_action_and_wait = confirmed_action  # type: ignore[method-assign]
    server._require_message_delivery = lambda result: None  # type: ignore[method-assign]

    asyncio.run(server.send_group_summary("20001", str(summary_path)))

    assert captured["target"] is websocket
    assert captured["action"] == "send_group_msg"
    assert captured["timeout_seconds"] == 15.0
    assert captured["params"] == {
        "group_id": "20001",
        "message": [
            {
                "type": "image",
                "data": {"file": str(summary_path.resolve()), "cache": 0},
            }
        ],
    }


def test_group_history_uses_message_id_as_pagination_cursor() -> None:
    """部分 NapCat 版本不返回 message_seq，不能因此只读取第一页。"""
    server = object.__new__(OneBotServer)
    websocket = object()
    server._active_websockets = {websocket}
    calls: list[dict[str, object]] = []
    now = datetime.now().astimezone()

    def item(message_id: int, at: datetime) -> dict[str, object]:
        return {
            "group_id": "20001",
            "message_seq": "0",
            "message_id": message_id,
            "time": int(at.timestamp()),
            "user_id": "10001",
            "raw_message": f"m-{message_id}",
        }

    async def fake_call_action_and_wait(target, action, params, timeout):
        assert target is websocket
        assert action == "get_group_msg_history"
        calls.append(dict(params))
        if len(calls) == 1:
            return {"status": "ok", "data": {"messages": [item(200, now), item(199, now - timedelta(minutes=1))]}}
        if len(calls) == 2:
            assert params["message_seq"] == "199"
            assert params["reverse_order"] is True
            assert params["disable_get_url"] is True
            assert params["parse_mult_msg"] is False
            return {"status": "ok", "data": {"messages": [item(198, now - timedelta(hours=2))]}}
        return {"status": "ok", "data": {"messages": []}}

    server.call_action_and_wait = fake_call_action_and_wait  # type: ignore[method-assign]
    result = asyncio.run(
        server.fetch_group_history(
            "20001", now - timedelta(hours=1), now + timedelta(minutes=1), 100
        )
    )

    assert [item["message_id"] for item in result] == [199, 200]
    assert len(calls) == 2


def test_text_delivery_waits_for_onebot_result_and_marks_qq_offline(monkeypatch) -> None:
    server = object.__new__(OneBotServer)
    server.config = SimpleNamespace(bot_qq=100000001)
    server._onebot_probe_failures = 0
    published: list[tuple[bool, str]] = []

    async def failed_action(websocket, action, params, timeout):
        assert action == "send_private_msg"
        assert timeout == 12.0
        return {"status": "failed", "retcode": 1200, "message": "网络连接异常!"}

    server.call_action_and_wait = failed_action
    monkeypatch.setattr(
        "atri_qq_bot.onebot.server.publish_onebot_probe_result",
        lambda healthy, *, detail="", self_id=None: published.append((healthy, detail)),
    )

    with pytest.raises(RuntimeError, match="网络连接异常"):
        asyncio.run(
            server._send_one_reply(
                object(),
                {"message_type": "private", "user_id": 10001},
                OutgoingMessage("text", "测试回复"),
            )
        )

    assert published == [(False, "网络连接异常!")]
    assert server._onebot_probe_failures == 1


def test_repeated_delivery_failures_request_manual_napcat_login(monkeypatch) -> None:
    server = object.__new__(OneBotServer)
    server._onebot_probe_failures = 2
    server._last_napcat_manual_login_notice_at = 0.0
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr("atri_qq_bot.onebot.server.time.monotonic", lambda: 1000.0)
    monkeypatch.setattr(
        "atri_qq_bot.onebot.server.publish_napcat_runtime_state",
        lambda state, *, detail="": notices.append((state, detail)),
    )

    asyncio.run(server._mark_napcat_manual_login_required())
    asyncio.run(server._mark_napcat_manual_login_required())

    assert notices == [
        ("login_required", "NapCat/QQ 状态连续异常，请打开 NapCat WebUI 手动扫码登录")
    ]


def test_reply_failure_is_logged_and_sent_only_to_evaluation_side_channel(
    tmp_path: Path,
) -> None:
    class FakeInsights:
        def __init__(self) -> None:
            self.failures: list[tuple[object, str]] = []

        def submit_evaluation_failure(self, sample, error: str) -> None:
            self.failures.append((sample, error))

    server = object.__new__(OneBotServer)
    server.insights = FakeInsights()
    server._reply_event_log = tmp_path / "reply-events.jsonl"

    server._record_reply_failure(
        {"message_type": "private", "user_id": 10001},
        turn_id="turn-1",
        conversation_id="private:10001",
        user_text="你好",
        model_reply="",
        reason="backend unavailable",
    )

    event = json.loads(server._reply_event_log.read_text(encoding="utf-8"))
    assert event["status"] == "failed"
    assert event["delivered_reply"] == ""
    assert event["failure_reason"] == "backend unavailable"
    assert len(server.insights.failures) == 1
    sample, error = server.insights.failures[0]
    assert sample.answer == ""
    assert error == "backend unavailable"


def test_extract_reply_message_id_from_onebot_segment() -> None:
    message = [
        {"type": "reply", "data": {"id": "1001"}},
        {"type": "text", "data": {"text": "这个是什么意思"}},
    ]

    assert extract_reply_message_id(message) == "1001"


def test_normalize_poke_event_only_targets_atri() -> None:
    event = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "self_id": 100000001,
        "user_id": 10001,
        "target_id": 100000001,
        "group_id": 20001,
    }

    normalized = normalize_poke_event(event, 100000001)

    assert normalized is not None
    assert normalized["post_type"] == "message"
    assert normalized["message_type"] == "group"
    assert normalized["_atri_poke_event"] is True
    assert extract_plain_text(normalized["message"]) == "[用户戳了戳亚托莉]"
    assert normalize_poke_event({**event, "target_id": 10002}, 100000001) is None


def test_handle_payload_routes_poke_as_a_normal_message(monkeypatch) -> None:
    server = object.__new__(OneBotServer)
    server.config = SimpleNamespace(bot_qq=100000001)
    captured: list[dict[str, object]] = []
    server._enqueue_message_event = lambda websocket, event: captured.append(event)
    event = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "self_id": 100000001,
        "user_id": 10001,
        "target_id": 100000001,
    }

    asyncio.run(server.handle_payload(object(), json.dumps(event)))

    assert len(captured) == 1
    assert captured[0]["post_type"] == "message"
    assert captured[0]["message_type"] == "private"
    assert captured[0]["_atri_poke_event"] is True


def test_handle_payload_ignores_valid_json_that_is_not_an_event_object() -> None:
    server = object.__new__(OneBotServer)
    server.config = SimpleNamespace(bot_qq=100000001)
    captured: list[dict[str, object]] = []
    server._enqueue_message_event = lambda websocket, event: captured.append(event)

    asyncio.run(server.handle_payload(object(), json.dumps(["not-an-event"])))

    assert captured == []


def test_handle_payload_bounds_a_busy_conversation_queue_and_keeps_latest_messages(
    monkeypatch,
    caplog,
) -> None:
    server = object.__new__(OneBotServer)
    server.config = SimpleNamespace(bot_qq=100000001)
    server._conversation_queues = {}
    server._conversation_workers = {}
    server._message_tasks = set()
    server._start_conversation_worker = lambda queue_id: None
    monkeypatch.setattr(
        "atri_qq_bot.onebot.server.CONVERSATION_QUEUE_MAXSIZE",
        2,
    )

    async def scenario() -> list[int]:
        for message_id in (1, 2, 3):
            await server.handle_payload(
                object(),
                json.dumps(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "user_id": 10001,
                        "self_id": 100000001,
                        "message_id": message_id,
                        "message": [{"type": "text", "data": {"text": str(message_id)}}],
                    }
                ),
            )
        queue = server._conversation_queues["private:10001"]
        return [item[1]["message_id"] for item in (queue.get_nowait(), queue.get_nowait())]

    assert asyncio.run(scenario()) == [2, 3]
    assert "会话队列已满" in caplog.text
    assert "dropped_message=1" in caplog.text


def test_server_shutdown_cancels_message_workers_and_pending_actions() -> None:
    server = object.__new__(OneBotServer)

    async def scenario() -> tuple[bool, bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        task = asyncio.create_task(worker())
        pending = asyncio.get_running_loop().create_future()
        server._message_tasks = {task}
        server._conversation_workers = {"private:10001": task}
        server._conversation_queues = {"private:10001": object()}
        server._pending_actions = {"echo-1": pending}

        await server.shutdown()

        return (
            task.cancelled(),
            pending.cancelled(),
            not server._message_tasks
            and not server._conversation_workers
            and not server._conversation_queues
            and not server._pending_actions,
        )

    assert asyncio.run(scenario()) == (True, True, True)


def test_quoted_text_is_delimited_from_current_message() -> None:
    result = _compose_model_input("@ATRI 那个是你啊", "ATRI：不过我可没在凑哦")

    assert result.startswith("【引用消息】")
    assert "ATRI：不过我可没在凑哦" in result
    assert result.endswith("【用户当前消息】\n@ATRI 那个是你啊")


def test_server_resolves_quoted_message_through_get_msg() -> None:
    server = object.__new__(OneBotServer)

    async def fake_call_action_and_wait(websocket, action, params, timeout):
        assert action == "get_msg"
        assert params == {"message_id": 1001}
        assert timeout == 3.0
        return {
            "status": "ok",
            "data": {
                "message": [
                    {"type": "text", "data": {"text": "被引用的原文"}},
                ]
            },
        }

    server.call_action_and_wait = fake_call_action_and_wait
    event = {
        "message": [
            {"type": "reply", "data": {"id": "1001"}},
            {"type": "text", "data": {"text": "请解释"}},
        ]
    }

    message_id, text, segments = asyncio.run(
        server._resolve_quoted_message(object(), event)
    )

    assert message_id == "1001"
    assert text == "被引用的原文"
    assert segments[0]["type"] == "text"
def test_extract_plain_text_from_string() -> None:
    assert extract_plain_text("你好，亚托莉") == "你好，亚托莉"


def test_connection_lifecycle_publishes_real_napcat_state(monkeypatch) -> None:
    states: list[tuple[str, str]] = []
    server = object.__new__(OneBotServer)
    server._active_websockets = set()

    class EmptyWebSocket:
        remote_address = ("127.0.0.1", 50000)

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    monkeypatch.setattr(
        "atri_qq_bot.onebot.server.publish_napcat_runtime_state",
        lambda state, *, detail="": states.append((state, detail)),
    )

    asyncio.run(server.handle_connection(EmptyWebSocket()))

    assert [state for state, _detail in states] == ["probing", "disconnected"]


def test_visual_followup_detection() -> None:
    assert _is_visual_followup("\u8fd9\u4e2a\u662f\u8c01\uff1f")
    assert _is_visual_followup("\u4e0a\u4e00\u5f20\u56fe\u5199\u4e86\u4ec0\u4e48")
    assert not _is_visual_followup("\u4eca\u5929\u665a\u4e0a\u5403\u4ec0\u4e48")


def test_current_visual_never_reuses_the_previous_visual_context() -> None:
    current_image = {
        "message": [
            {"type": "text", "data": {"text": "这是谁？"}},
            {"type": "image", "data": {"file": "new.jpg"}},
        ]
    }
    current_sticker = {
        "message": [{"type": "mface", "data": {"summary": "新动画表情"}}]
    }
    text_followup = {"message": [{"type": "text", "data": {"text": "这是谁？"}}]}

    assert _event_has_visual_material(current_image)
    assert _event_has_visual_material(current_sticker)
    assert not _should_reuse_cached_visual(current_image, "这是谁？")
    assert not _should_reuse_cached_visual(current_sticker, "这个表情什么意思")
    assert _should_reuse_cached_visual(text_followup, "这是谁？")


def test_group_visual_can_be_bound_to_the_following_addressed_message() -> None:
    visual_event = {
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [{"type": "mface", "data": {"file": "sticker-1"}}],
    }
    addressed_event = {
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [
            {"type": "at", "data": {"qq": "100000001"}},
            {"type": "text", "data": {"text": " 这是什么意思"}},
        ],
    }

    merged = _merge_pending_visual_event(visual_event, addressed_event)

    assert _pending_visual_key(visual_event) == "group:20001:user:10001"
    assert [segment["type"] for segment in merged["message"]] == [
        "mface",
        "at",
        "text",
    ]
    assert visual_event["message"] == [
        {"type": "mface", "data": {"file": "sticker-1"}}
    ]
    assert addressed_event["message"][0]["type"] == "at"


def test_server_retains_non_replied_group_visual_until_next_reply() -> None:
    server = object.__new__(OneBotServer)
    server._pending_group_visual_events = {}
    visual_event = {
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [{"type": "image", "data": {"file": "current.jpg"}}],
    }
    next_event = {
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [{"type": "at", "data": {"qq": "100000001"}}],
    }

    server._remember_pending_group_visual(visual_event)
    merged = server._event_with_pending_group_visual(next_event)

    assert _event_has_visual_material(merged)
    assert not server._pending_group_visual_events


def test_extract_plain_text_from_segments() -> None:
    message = [
        {"type": "at", "data": {"qq": "100000001"}},
        {"type": "text", "data": {"text": " 在吗"}},
        {"type": "image", "data": {"file": "x.jpg"}},
    ]

    assert extract_plain_text(message) == "@群友 在吗[表情包/图片:x.jpg]"


def test_extract_plain_text_from_all_at_segment() -> None:
    message = [
        {"type": "at", "data": {"qq": "all"}},
        {"type": "text", "data": {"text": " 集合"}},
    ]

    assert extract_plain_text(message) == "@全体成员 集合"


def test_extract_plain_text_from_mface_segment() -> None:
    message = [
        {"type": "mface", "data": {"summary": "笑哭"}},
        {"type": "face", "data": {"id": "14"}},
    ]

    assert extract_plain_text(message) == "[动画表情:笑哭][QQ表情:14]"


def test_extract_plain_text_from_file_video_and_share_segments() -> None:
    share_payload = {
        "meta": {
            "detail_1": {
                "title": "罗翔：如何面对嫉妒",
                "qqdocurl": "https://b23.tv/example",
            }
        }
    }
    message = [
        {"type": "file", "data": {"name": "课堂笔记.txt", "file_id": "abc"}},
        {"type": "video", "data": {"title": "寝室项目记录"}},
        {"type": "json", "data": {"data": json.dumps(share_payload, ensure_ascii=False)}},
    ]

    text = extract_plain_text(message)

    assert "[文件:课堂笔记.txt]" in text
    assert "[视频:寝室项目记录]" in text
    assert "罗翔：如何面对嫉妒" in text
    assert "https://b23.tv/example" in text


def test_private_message_should_reply() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "private",
        "user_id": 10001,
        "message": "你好",
    }

    assert should_reply(event, 100000001, "mention")


def test_private_message_should_reply_in_smart_mode() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "private",
        "user_id": 10001,
        "message": "你好",
    }

    assert should_reply(event, 100000001, "smart")


def test_group_message_requires_mention_in_mention_mode() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "你好",
    }

    assert not should_reply(event, 100000001, "mention")


def test_group_smart_mode_does_not_reply_to_owner_without_mention() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 100000002,
        "message": "你好",
    }

    assert not should_reply(event, 100000001, "smart", (100000002,))


def test_group_smart_mode_replies_to_obvious_chat_trigger() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "帮我看看这个怎么处理",
    }

    assert should_reply(event, 100000001, "smart")


def test_group_smart_mode_does_not_reply_to_random_group_chatter() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "今天下午三点开会",
    }

    assert not should_reply(event, 100000001, "smart")


def test_group_message_replies_when_bot_is_mentioned() -> None:
    event = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [{"type": "at", "data": {"qq": "100000001"}}],
    }

    assert should_reply(event, 100000001, "mention")


def test_message_batch_merges_share_card_and_followup_text() -> None:
    first = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "private",
        "user_id": 10001,
        "message": [{"type": "video", "data": {"title": "测试视频"}}],
    }
    second = {
        "post_type": "message",
        "self_id": 100000001,
        "message_type": "private",
        "user_id": 10001,
        "message": "分析一下",
    }

    _, merged = _merge_message_batch([(object(), first), (object(), second)])
    text = extract_plain_text(merged["message"])

    assert "[视频:测试视频]" in text
    assert "分析一下" in text
