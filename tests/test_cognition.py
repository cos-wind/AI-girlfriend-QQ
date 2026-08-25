from __future__ import annotations

import asyncio

from atri_qq_bot.application import ConversationTurnRequest
from atri_qq_bot.cognition import CognitionKernel, CognitionStateStore
from atri_qq_bot.cognition.prompt_context import render_cognition_context


def request(
    turn_id: str,
    text: str,
    *,
    conversation_id: str = "private:1",
    profile_id: str = "private:1",
) -> ConversationTurnRequest:
    return ConversationTurnRequest(
        turn_id=turn_id,
        conversation_id=conversation_id,
        profile_id=profile_id,
        kind="group" if conversation_id.startswith("group:") else "private",
        user_text=text,
        actor_id=profile_id.rsplit(":", 1)[-1],
    )


def test_cognition_keeps_goal_continuity_and_modifies_song(tmp_path) -> None:
    kernel = CognitionKernel(CognitionStateStore(tmp_path / "state.sqlite3"))

    first = asyncio.run(kernel.deliberate(request("1", "唱一首你会的歌")))
    second = asyncio.run(kernel.deliberate(request("2", "换一首，别唱这个了")))

    assert first.proposal.capability == "music.sing"
    assert second.meaning.relation_to_previous == "modify"
    assert second.proposal.capability == "music.sing"
    assert "排除上一轮使用的对象" in second.state.goal.constraints
    assert "修正当前目标" in second.state.goal.objective


def test_correction_replaces_old_understanding_without_reasking_everything(tmp_path) -> None:
    kernel = CognitionKernel(CognitionStateStore(tmp_path / "state.sqlite3"))
    asyncio.run(kernel.deliberate(request("1", "给我发语音")))

    decision = asyncio.run(kernel.deliberate(request("2", "不是，我说的是唱歌")))

    assert decision.meaning.relation_to_previous == "correct"
    assert decision.meaning.action_domain == "music.sing"
    assert decision.proposal.capability == "music.sing"
    assert decision.proposal.action == "act"
    assert "采用用户最新修正" in decision.response_strategy


def test_group_users_have_independent_thought_threads(tmp_path) -> None:
    kernel = CognitionKernel(CognitionStateStore(tmp_path / "state.sqlite3"))
    a = request(
        "1",
        "唱一首歌",
        conversation_id="group:9",
        profile_id="group:9:user:100",
    )
    b = request(
        "2",
        "这张图片什么意思",
        conversation_id="group:9",
        profile_id="group:9:user:200",
    )
    asyncio.run(kernel.deliberate(a))
    asyncio.run(kernel.deliberate(b))

    a_state = kernel.store.load("group:9:user:100")
    b_state = kernel.store.load("group:9:user:200")

    assert a_state.goal.capability == "music.sing"
    assert b_state.goal.capability == "vision.understand"
    assert a_state.world.turn_count == b_state.world.turn_count == 1


def test_affect_has_emotion_and_slow_mood_continuity(tmp_path) -> None:
    kernel = CognitionKernel(CognitionStateStore(tmp_path / "state.sqlite3"))
    sad = asyncio.run(kernel.deliberate(request("1", "我今天有点难受，想哭")))
    happy = asyncio.run(kernel.deliberate(request("2", "不过你陪我我很开心")))

    assert sad.state.affect.emotion == "concerned"
    assert happy.state.affect.emotion == "happy"
    assert happy.state.affect.valence < 0.72
    assert happy.state.self_state.current_thought
    assert happy.state.self_state.recent_experiences


def test_state_survives_kernel_recreation(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    first = CognitionKernel(CognitionStateStore(path))
    asyncio.run(first.deliberate(request("1", "帮我查最新的ATRI消息")))

    restored = CognitionKernel(CognitionStateStore(path))
    decision = asyncio.run(restored.deliberate(request("2", "继续看看")))

    assert decision.state.world.turn_count == 2
    assert decision.meaning.relation_to_previous == "continue"
    assert decision.state.self_state.recent_experiences


def test_weather_only_clarifies_when_location_cannot_be_inferred(tmp_path) -> None:
    kernel = CognitionKernel(CognitionStateStore(tmp_path / "state.sqlite3"))
    missing = asyncio.run(kernel.deliberate(request("1", "今天天气怎么样")))
    known = asyncio.run(kernel.deliberate(request("2", "查十堰的天气")))

    assert missing.proposal.capability == "weather.lookup"
    assert missing.proposal.action == "clarify"
    assert known.proposal.capability == "weather.lookup"
    assert known.proposal.action == "retrieve"


def test_prompt_context_exposes_continuity_without_hidden_thought(tmp_path) -> None:
    store = CognitionStateStore(tmp_path / "state.sqlite3")
    kernel = CognitionKernel(store)
    asyncio.run(kernel.deliberate(request("1", "我今天有点难受，想听你唱首歌")))

    context = render_cognition_context(store, "private:1")

    assert "当前心情" in context
    assert "正在延续的目标" in context
    assert "近期共同经历" in context
    assert "隐藏推理" in context
    assert "下一步应通过" not in context


def test_prompt_context_is_empty_before_first_cognition_turn(tmp_path) -> None:
    store = CognitionStateStore(tmp_path / "state.sqlite3")

    assert render_cognition_context(store, "private:new") == ""


def test_elliptical_followup_inherits_capability_without_new_intent_label(tmp_path) -> None:
    kernel = CognitionKernel(CognitionStateStore(tmp_path / "state.sqlite3"))
    asyncio.run(kernel.deliberate(request("1", "帮我查一下今天的AI新闻")))

    decision = asyncio.run(kernel.deliberate(request("2", "那国外的呢")))

    assert decision.meaning.relation_to_previous == "continue"
    assert decision.meaning.action_domain == "research.web"
    assert decision.proposal.capability == "research.web"
