"""入群欢迎：OneBot 的 group_increase 通知 → 普通群消息事件。

和戳一戳同一套做法：适配层归一化，回复链路里不加特例分支。
"""

from __future__ import annotations

from atri_qq_bot.onebot.message_parser import (
    group_increase_text,
    is_group_increase_event,
    normalize_group_increase_event,
)

BOT_QQ = 900000002


def _notice(**overrides):
    event = {
        "post_type": "notice",
        "notice_type": "group_increase",
        "sub_type": "approve",
        "self_id": BOT_QQ,
        "group_id": 900001001,
        "user_id": 900001003,
        "operator_id": 900000001,
        "time": 1700000000,
    }
    event.update(overrides)
    return event


# ---- 识别 ---------------------------------------------------------------


def test_recognizes_group_increase_notice() -> None:
    assert is_group_increase_event(_notice()) is True


def test_does_not_match_other_notices() -> None:
    assert is_group_increase_event(_notice(notice_type="group_decrease")) is False
    assert is_group_increase_event(_notice(notice_type="poke")) is False
    assert is_group_increase_event({"post_type": "message", "message_type": "group"}) is False
    assert is_group_increase_event({}) is False


# ---- 归一化 -------------------------------------------------------------


def test_normalizes_into_a_group_message_event() -> None:
    normalized = normalize_group_increase_event(_notice(), BOT_QQ)

    assert normalized is not None
    # post_type 必须变成 message，否则不会进入回复链路。
    assert normalized["post_type"] == "message"
    assert normalized["message_type"] == "group"
    assert normalized["sub_type"] == "group_increase"
    assert normalized["_atri_group_increase_event"] is True
    # 群号与新成员 QQ 必须原样保留——回复要发到这个群，记忆也按这个会话记。
    assert normalized["group_id"] == 900001001
    assert normalized["user_id"] == 900001003
    assert normalized["self_id"] == BOT_QQ
    # 文本要用「亚托莉看到…」的事件口吻，且带上新成员标识。
    text = normalized["message"][0]["data"]["text"]
    assert text.startswith("[亚托莉看到新成员")
    assert "900001003" in text
    assert normalized["raw_message"] == text
    # 结构化上下文供上层使用（日志、后续扩展），不至于只能靠解析文本。
    assert normalized["_atri_group_increase_member"] == {
        "user_id": "900001003",
        "group_id": "900001001",
        "nickname": "",
    }


def test_uses_nickname_when_the_notice_carries_one() -> None:
    normalized = normalize_group_increase_event(_notice(nickname="新人甲"), BOT_QQ)

    assert normalized is not None
    text = normalized["message"][0]["data"]["text"]
    assert "新人甲" in text
    # 昵称与 QQ 都要在文本里——只给 QQ 号的话欢迎语会很生硬。
    assert "900001003" in text
    assert normalized["_atri_group_increase_member"]["nickname"] == "新人甲"


def test_bot_joining_a_group_is_ignored() -> None:
    """亚托莉自己被拉进群不是"新人入群"，不该由她欢迎自己。"""
    assert normalize_group_increase_event(_notice(user_id=BOT_QQ), BOT_QQ) is None


def test_missing_group_or_member_is_ignored() -> None:
    assert normalize_group_increase_event(_notice(group_id=None), BOT_QQ) is None
    assert normalize_group_increase_event(_notice(user_id=None), BOT_QQ) is None
    assert normalize_group_increase_event(_notice(user_id="abc"), BOT_QQ) is None


def test_other_notices_are_not_normalized() -> None:
    assert normalize_group_increase_event(_notice(notice_type="poke"), BOT_QQ) is None


def test_normalized_event_is_a_valid_message_for_the_reply_path() -> None:
    """归一化后必须满足回复链路对"群消息"的最低要求，否则会被整体忽略。"""
    normalized = normalize_group_increase_event(_notice(), BOT_QQ)

    assert normalized is not None
    assert normalized["post_type"] == "message"
    assert normalized["message_type"] == "group"
    # 事件不是别的 QQ 号发来的（server_events 的 is_message 会检查这两条）。
    assert normalized["self_id"] in {None, BOT_QQ}
    assert normalized["user_id"] != BOT_QQ
    assert isinstance(normalized["message"], list)
    assert normalized["message"][0]["type"] == "text"


# ---- 文本格式 -----------------------------------------------------------


def test_text_uses_the_event_framing() -> None:
    """用「亚托莉看到…」的事件口吻，而不是"有人在对你说话"。"""
    assert group_increase_text("", "123") == "[亚托莉看到新成员 QQ 123 加入了本群]"
    assert (
        group_increase_text("新人甲", "123")
        == "[亚托莉看到新成员「新人甲」(QQ 123) 加入了本群]"
    )


def test_text_never_repeats_the_qq_number() -> None:
    """没昵称时不要把 QQ 号写两遍。"""
    text = group_increase_text("", "123")

    assert text.count("123") == 1


# ---- 补昵称（额外问一次 QQ 内核）--------------------------------------


def _enrich_stub(payload=None, error=None):
    class Stub:
        async def call_action_and_wait(self, websocket, action, params, timeout):
            Stub.action = action
            Stub.params = params
            if error is not None:
                raise error
            return {"status": "ok", "retcode": 0, "data": payload or {}}

    return Stub()


def _pending_join_event():
    return {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "group_increase",
        "self_id": BOT_QQ,
        "group_id": 900001001,
        "user_id": 900001003,
        "_atri_group_increase_event": True,
        "_atri_group_increase_member": {
            "user_id": "900001003",
            "group_id": "900001001",
            "nickname": "",
        },
        "message": [{"type": "text", "data": {"text": "占位"}}],
    }


def test_enrichment_fetches_the_group_card_and_rewrites_the_text() -> None:
    import asyncio

    from atri_qq_bot.onebot.server_parts.server_events import OneBotEventMixin

    stub = _enrich_stub({"card": "四氯化碳", "nickname": "不理不理"})

    enriched = asyncio.run(
        OneBotEventMixin._resolve_group_increase_name(stub, None, _pending_join_event())
    )

    # 群名片优先于昵称——群里显示的就是群名片。
    assert enriched["_atri_group_increase_member"]["nickname"] == "四氯化碳"
    assert "四氯化碳" in enriched["message"][0]["data"]["text"]
    assert enriched["raw_message"] == enriched["message"][0]["data"]["text"]
    assert stub.action == "get_group_member_info"
    assert stub.params["user_id"] == 900001003


def test_enrichment_falls_back_to_nickname_when_card_is_empty() -> None:
    import asyncio

    from atri_qq_bot.onebot.server_parts.server_events import OneBotEventMixin

    stub = _enrich_stub({"card": "", "nickname": "新人甲"})

    enriched = asyncio.run(
        OneBotEventMixin._resolve_group_increase_name(stub, None, _pending_join_event())
    )

    assert "新人甲" in enriched["message"][0]["data"]["text"]


def test_enrichment_never_blocks_the_welcome_when_the_action_fails() -> None:
    """补昵称是纯增益步骤：拿不到名字也必须照常欢迎。"""
    import asyncio

    from atri_qq_bot.onebot.server_parts.server_events import OneBotEventMixin

    stub = _enrich_stub(error=RuntimeError("QQ 内核不通"))

    enriched = asyncio.run(
        OneBotEventMixin._resolve_group_increase_name(stub, None, _pending_join_event())
    )

    assert "900001003" in enriched["message"][0]["data"]["text"]
    assert enriched["_atri_group_increase_member"]["nickname"] == ""


def test_enrichment_skips_the_action_when_the_notice_already_has_a_name() -> None:
    import asyncio

    from atri_qq_bot.onebot.server_parts.server_events import OneBotEventMixin

    event = _pending_join_event()
    event["_atri_group_increase_member"]["nickname"] = "已经有名字了"

    class NeverCalled:
        async def call_action_and_wait(self, *args, **kwargs):
            raise AssertionError("不该再发动作")

    enriched = asyncio.run(
        OneBotEventMixin._resolve_group_increase_name(NeverCalled(), None, event)
    )

    assert "已经有名字了" in enriched["message"][0]["data"]["text"]


# ---- 绕开频率门控，但不绕开对象级模式（用户明确要求"入群必回"）------------


def test_join_event_bypasses_the_frequency_gates() -> None:
    """入群事件刻意绕开群内冷却、blocked 档案与回复策略的**频率**门控。

    语义上它是一次"事件"而不是一次群聊插话——同一批人陆续进群时不该因为
    刚回过话就漏掉欢迎（用户反馈的"没有都回"就是这个）。
    """
    import inspect

    from atri_qq_bot.onebot.server_parts import server_events

    source = inspect.getsource(server_events.OneBotEventMixin._handle_event)

    assert "join_event = bool(event.get(\"_atri_group_increase_event\"))" in source
    # 三道频率门控都要有 not join_event 守卫。
    assert source.count("not join_event") >= 3
    assert "and not self._smart_group_reply_allowed(" in source
    assert "if is_message and should_send_reply and not join_event:" in source
    # 补昵称必须在抽取纯文本之前。
    assert source.index("_resolve_group_increase_name") < source.index(
        "plain_text = extract_plain_text"
    )


def test_join_event_still_respects_the_object_mode() -> None:
    """绕开频率不等于绕开对象级模式。

    对象级的「禁止回复 / 只记录 / 仅 @ 回复」表达的是"这个对象不该被主动搭话"，
    优先级高于"入群必回"。历史事故：19:16 有一条入群欢迎是在 quiet（只记录）
    模式下的群里发出去的——入群事件当时完全没走策略判定。
    """
    import inspect

    from atri_qq_bot.onebot.server_parts import server_events

    source = inspect.getsource(server_events.OneBotEventMixin._handle_event)

    assert "forced_event_block_reason(" in source
    assert "if should_send_reply and join_event:" in source
    # 判定必须发生在真正派发回复之前。
    assert source.index("forced_event_block_reason(") < source.index(
        "if is_message and should_send_reply and not join_event:"
    )


def test_mention_only_group_does_not_open_a_continuation_session() -> None:
    """「仅 @ 回复」的群里不能打开续聊会话。

    会话一旦打开，该成员之后的表情和插话都会被当成续聊绕过 @ 检查，而且每次
    命中还会滑动续期——表现就是"设了仅 @ 它还在自己冒泡"。
    """
    import inspect

    from atri_qq_bot.onebot.server_parts import server_events

    source = inspect.getsource(server_events.OneBotEventMixin._handle_event)

    assert "object_requires_mention(" in source
    assert source.index("object_requires_mention(") < source.index(
        "self._group_reply_focus.open_session("
    )
