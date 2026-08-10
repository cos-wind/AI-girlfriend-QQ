import asyncio

from atri_qq_bot.config import BotConfig
from atri_qq_bot.group_reply_focus import GroupReplyFocus, GroupReplyFocusStore
from atri_qq_bot.onebot.server import OneBotServer
from atri_qq_bot.persona import AtriReplyEngine


BOT_QQ = 100000001
GROUP_ID = 1095215340


def _group_event(user_id: int, *segments: dict) -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": GROUP_ID,
        "user_id": user_id,
        "message": list(segments),
    }


def _text(value: str) -> dict:
    return {"type": "text", "data": {"text": value}}


def _at_bot() -> dict:
    return {"type": "at", "data": {"qq": str(BOT_QQ)}}


def test_bare_mention_prioritizes_triggering_members_latest_message() -> None:
    store = GroupReplyFocusStore(ttl_seconds=120)
    member_a = _group_event(10001, _text("A刚发的最新内容"))
    member_b = _group_event(10002, _text("B刚问了一个更长、更显眼的问题"))

    store.remember(member_a, "A刚发的最新内容", addressed_to_bot=False, now=1)
    store.remember(member_b, "B刚问了一个更长、更显眼的问题", addressed_to_bot=False, now=2)
    focus = store.resolve(
        _group_event(10001, _at_bot()),
        "@群友",
        nickname="A",
        addressed_to_bot=True,
        now=3,
    )

    assert focus is not None
    assert focus.actor_id == "10001"
    assert focus.focus_text == "A刚发的最新内容"
    assert focus.source == "previous_same_sender"
    assert "B刚问了一个更长" not in focus.prompt_context()


def test_share_is_bound_to_following_mention_from_same_member() -> None:
    store = GroupReplyFocusStore(ttl_seconds=120)
    share = _group_event(
        10001,
        {
            "type": "share",
            "data": {"title": "中华亚", "url": "https://example.test/share/1"},
        },
    )
    store.remember(
        share,
        "[分享:中华亚 https://example.test/china-atri]",
        addressed_to_bot=False,
        now=10,
    )

    focus = store.resolve(
        _group_event(10001, _at_bot()),
        "@群友",
        nickname="A",
        addressed_to_bot=True,
        now=12,
    )

    assert focus is not None
    assert focus.focus_text.startswith("[分享:中华亚")
    assert [segment["type"] for segment in focus.analysis_event["message"]] == [
        "share",
        "at",
    ]


def test_substantive_current_message_wins_over_pending_message() -> None:
    store = GroupReplyFocusStore(ttl_seconds=120)
    store.remember(
        _group_event(10001, _text("旧话题")),
        "旧话题",
        addressed_to_bot=False,
        now=1,
    )

    current = _group_event(10001, _at_bot(), _text("今天吃什么？"))
    focus = store.resolve(
        current,
        "@群友 今天吃什么？",
        nickname="A",
        addressed_to_bot=True,
        now=2,
    )

    assert focus is not None
    assert focus.focus_text == "今天吃什么？"
    assert focus.source == "current_message"
    assert focus.analysis_event is current


def test_mention_opens_five_minute_same_member_session() -> None:
    store = GroupReplyFocusStore(active_session_ttl_seconds=300)
    mention = _group_event(10001, _at_bot(), _text("你觉得这个怎么样？"))
    store.open_session(mention, nickname="A", now=10)

    assert store.is_active_continuation(
        _group_event(10001, _text("那你为什么这么想？")),
        "那你为什么这么想？",
        now=309,
    )
    assert not store.is_active_continuation(
        _group_event(10002, _text("那你为什么这么想？")),
        "那你为什么这么想？",
        now=309,
    )


def test_active_session_expires_and_does_not_intercept_other_mentions() -> None:
    store = GroupReplyFocusStore(active_session_ttl_seconds=300)
    mention = _group_event(10001, _at_bot(), _text("聊聊这个"))
    store.open_session(mention, nickname="A", now=10)

    assert not store.is_active_continuation(
        _group_event(
            10001,
            {"type": "at", "data": {"qq": "10002"}},
            _text("你看一下"),
        ),
        "@群友 你看一下",
        now=20,
    )
    assert not store.is_active_continuation(
        _group_event(10001, _text("你还在吗？")),
        "你还在吗？",
        now=311,
    )


def test_group_prompt_marks_same_sender_focus_as_mandatory(monkeypatch, tmp_path) -> None:
    config = BotConfig(
        bot_qq=BOT_QQ,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="test-key",
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.4,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
        llm_tools_enabled=False,
    )
    engine = AtriReplyEngine(config)
    captured: dict[str, object] = {}

    async def fake_post(client, headers, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "我先回应A刚才的分享。"}}]}

    monkeypatch.setattr(engine, "_post_chat_completion", fake_post)
    focus = GroupReplyFocus(
        actor_id="10001",
        nickname="A",
        trigger_text="@群友",
        focus_text="[分享:中华亚 https://example.test/china-atri]",
        source="previous_same_sender",
        analysis_event=_group_event(10001, _at_bot()),
    )

    reply = asyncio.run(
        engine._reply_with_api(
            f"group:{GROUP_ID}",
            "@群友",
            "A",
            profile_id=f"group:{GROUP_ID}:user:10001",
            profile={},
            context_profile={},
            reply_focus=focus,
            allow_reply_voice=False,
        )
    )

    contents = [str(message.get("content") or "") for message in captured["messages"]]
    focus_prompt = next(content for content in contents if "本轮强制回复焦点" in content)
    assert reply == "我先回应A刚才的分享。"
    assert "回复对象：A" in focus_prompt
    assert "[分享:中华亚" in focus_prompt
    assert "其他群友消息只能作为背景" in focus_prompt


def test_server_routes_previous_share_and_focus_to_same_reply(monkeypatch, tmp_path) -> None:
    config = BotConfig(
        bot_qq=BOT_QQ,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.4,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
        voice_tts_enabled=False,
    )
    engine = AtriReplyEngine(config)
    server = OneBotServer(config, engine)
    server._event_log = tmp_path / "onebot-events.log"
    server._reply_event_log = tmp_path / "reply-events.jsonl"
    server._voice_event_log = tmp_path / "voice-events.log"
    captured: dict[str, object] = {}

    async def fake_analyze(event, plain_text, call_action):
        captured["analysis_event"] = event
        return None

    async def fake_reply(*args, **kwargs):
        captured["reply_focus"] = kwargs.get("reply_focus")
        return "收到"

    async def fake_send_reply(*args, **kwargs):
        return "收到"

    monkeypatch.setattr(server.tools, "analyze", fake_analyze)
    monkeypatch.setattr(engine, "reply", fake_reply)
    monkeypatch.setattr(server, "send_reply", fake_send_reply)

    share = _group_event(
        10001,
        {
            "type": "share",
            "data": {"title": "中华亚", "url": "https://example.test/share/2"},
        },
    )
    share.update({"self_id": BOT_QQ, "sender": {"card": "A"}})
    mention = _group_event(10001, _at_bot())
    mention.update({"self_id": BOT_QQ, "sender": {"card": "A"}})

    asyncio.run(server._handle_event(object(), share))
    asyncio.run(server._handle_event(object(), mention))

    focus = captured["reply_focus"]
    analysis_event = captured["analysis_event"]
    assert isinstance(focus, GroupReplyFocus)
    assert focus.focus_text.startswith("[分享:中华亚")
    assert [segment["type"] for segment in analysis_event["message"]] == [
        "share",
        "at",
    ]
