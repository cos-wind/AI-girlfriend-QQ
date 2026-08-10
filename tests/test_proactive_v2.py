import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from atri_qq_bot.memory import UserMemoryStore
from atri_qq_bot.config import BotConfig
from atri_qq_bot.persona import AtriReplyEngine
from atri_qq_bot.persona.core import (
    _needs_proactive_grounding_repair,
    _needs_topic_guidance_repair,
)
from atri_qq_bot.proactive import (
    ProactivePlanner,
    default_proactive_policy,
    load_proactive_policy,
    normalize_proactive_policy,
    save_proactive_policy,
)
from atri_qq_bot.proactive.planner import candidate_tier
from atri_webui.page import render_index


CHINA = timezone(timedelta(hours=8))


def test_proactive_generation_skips_instead_of_using_template_without_model(
    tmp_path: Path,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key=None,
        openai_base_url="https://example.invalid/v1",
        openai_model="test-model",
        temperature=0.7,
        max_tokens=180,
        memory_path=tmp_path / "users.json",
    )
    engine = AtriReplyEngine(config)

    result = asyncio.run(
        engine.generate_proactive_message(
            "private:50001",
            "morning",
            default_proactive_policy(),
            datetime(2026, 7, 14, 8, 0, tzinfo=CHINA),
        )
    )

    assert result["text"] == ""
    assert result["source"] == "skipped-no-model"
    assert "未配置聊天模型" in result["error"]


def test_policy_save_is_normalized_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "proactive.json"
    policy = default_proactive_policy()
    policy["check_seconds"] = 1
    policy["max_chars"] = 999

    saved = save_proactive_policy(policy, path)

    assert saved["check_seconds"] == 15
    assert saved["max_chars"] == 240
    assert load_proactive_policy(path) == saved
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2
    assert not path.with_suffix(".tmp").exists()


def test_policy_rejects_disabling_every_content_type() -> None:
    policy = default_proactive_policy()
    policy["content_weights"] = {key: 0 for key in policy["content_weights"]}

    with pytest.raises(ValueError, match="至少需要启用"):
        normalize_proactive_policy(policy)


def test_proactive_grounding_guard_detects_unperformed_experience_claims() -> None:
    assert _needs_proactive_grounding_repair("这小程序我刚点进去看了下，还挺有意思")
    assert _needs_proactive_grounding_repair("让我想起自己用红石做过自动点歌机")
    assert not _needs_proactive_grounding_repair("如果用红石做自动点歌机，你们会先解决节奏还是音准？")


def test_topic_guidance_guard_requires_specific_response_entry() -> None:
    assert _needs_topic_guidance_repair("这个表情包很适合拿来接梗。", "guided_topic", True)
    assert _needs_topic_guidance_repair("大家最近怎么样？", "guided_topic", True)
    assert not _needs_topic_guidance_repair(
        "如果只能留一个优点，你们会选实用还是有趣？",
        "guided_topic",
        True,
    )


def test_planner_persists_random_plan_until_it_is_due(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "users.json")
    store.remember_target("private:10001", {"message_type": "private", "user_id": 10001})
    store.set_affection("private:10001", 82, is_owner=True)
    policy = default_proactive_policy()
    policy["quiet_start"] = "00:00"
    policy["quiet_end"] = "00:00"
    for tier in policy["tiers"]:
        if tier["id"] == "close":
            tier["min_hours"] = 2
            tier["max_hours"] = 2
    planner = ProactivePlanner(store, (10001,), rng=random.Random(7))
    now = datetime(2026, 7, 13, 12, 0, tzinfo=CHINA)

    assert planner.due_plans(policy, now) == []
    first_state = store.proactive_state("private:10001", is_owner=True)
    first_plan = first_state["next_at"]
    assert first_plan == (now + timedelta(hours=2)).timestamp()

    assert planner.due_plans(policy, now + timedelta(hours=1)) == []
    assert store.proactive_state("private:10001", is_owner=True)["next_at"] == first_plan

    due = planner.due_plans(policy, now + timedelta(hours=2, seconds=1))
    assert len(due) == 1
    assert due[0].conversation_id == "private:10001"
    assert due[0].scheduled_at == first_plan


def test_user_reply_clears_pending_plan_and_ignored_backoff(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "users.json")
    store.remember_target("private:10001", {"message_type": "private", "user_id": 10001})
    store.set_proactive_plan("private:10001", 2000, "check_in")
    store.mark_proactive_sent(
        "private:10001",
        "check_in",
        "来看看你。",
        "ai",
        "2026-07-13",
        now=1500,
    )
    store.note_proactive_unanswered("private:10001")
    assert store.proactive_state("private:10001")["ignored_streak"] == 1

    store.observe_user("private:10001", "刚刚在忙，现在回来啦", now=1600)
    state = store.proactive_state("private:10001")

    assert state["next_at"] is None
    assert state["awaiting_reply"] is False
    assert state["ignored_streak"] == 0


def test_planner_moves_quiet_hour_plan_to_morning(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "users.json")
    store.remember_target("private:10001", {"message_type": "private", "user_id": 10001})
    store.set_affection("private:10001", 90, is_owner=True)
    policy = default_proactive_policy()
    intimate = next(tier for tier in policy["tiers"] if tier["id"] == "intimate")
    intimate["min_hours"] = intimate["max_hours"] = 1
    planner = ProactivePlanner(store, (10001,), rng=random.Random(3))

    planner.due_plans(policy, datetime(2026, 7, 13, 23, 45, tzinfo=CHINA))
    planned = datetime.fromtimestamp(
        store.proactive_state("private:10001", is_owner=True)["next_at"],
        CHINA,
    )

    assert planned.date().isoformat() == "2026-07-14"
    assert planned.hour == 7
    assert planned.minute >= 5


def test_webui_merges_proactive_controls_and_plans_into_existing_pages() -> None:
    page = render_index()

    assert 'id="proactive" class="panel"' not in page
    assert "showTab(event,'proactive')" not in page
    assert 'id="advanced" class="panel"' in page
    assert 'id="proactiveTierRows"' in page
    assert "/api/proactive/save" in page
    assert "PROACTIVE_V2_ENABLED" in page
    assert 'id="proactiveEngineEnabled"' in page
    assert 'id="proactiveGroupEnabled"' in page
    assert 'id="proactivePrivateMinAffection"' in page
    assert 'id="proactiveScheduleRows"' not in page
    assert "proactive_plan" in page
    assert "好感 ${formatScore(x.affection)}" in page
    assert 'type="password" readonly aria-label="下次主动消息发送时间"' in page
    assert "toggleProactiveTime(this)" in page
    assert "input.type = reveal ? 'text' : 'password'" in page
    assert 'id="memoryAffectionScore"' in page
    assert 'id="memoryGroupActivityScore"' in page
    assert 'id="memoryProactiveOverride"' in page
    assert "saveRelationshipControls()" in page
    assert "/api/memory/relationship" in page


def test_advanced_config_excludes_model_and_legacy_proactive_fields() -> None:
    page = render_index()
    advanced_fields = page.split("const fields = [", 1)[1].split("];", 1)[0]

    assert "REPLY_MODE" in advanced_fields
    assert "STICKER_CHANCE" in advanced_fields
    assert "OPENAI_API_KEY" not in advanced_fields
    assert "OPENAI_MODEL" not in advanced_fields
    assert "TOOLBOX_VISION_MODEL" not in advanced_fields
    assert "IDLE_PROACTIVE_ENABLED" not in advanced_fields
    assert "GROUP_PROACTIVE_ENABLED" not in advanced_fields
    assert "MORNING_GREETING_ENABLED" not in advanced_fields


def test_manual_proactive_override_has_priority_over_automatic_thresholds() -> None:
    policy = default_proactive_policy()
    now = datetime(2026, 7, 14, 12, 0, tzinfo=CHINA).timestamp()
    low_activity = {
        "affection_score": 1,
        "group_activity_score": 0,
        "message_count": 0,
        "last_user_at": 0,
        "proactive_override": "allow",
    }

    private_tier, private_reason = candidate_tier(policy, low_activity, False, False, now)
    group_tier, group_reason = candidate_tier(policy, low_activity, False, True, now)
    denied_tier, denied_reason = candidate_tier(
        policy,
        {**low_activity, "proactive_override": "deny"},
        True,
        False,
        now,
    )

    assert private_tier is not None
    assert private_reason == "已手动允许"
    assert group_tier is not None
    assert group_reason == "已手动允许"
    assert denied_tier is None
    assert denied_reason == "已手动禁止主动互动"


def test_manual_allow_bypasses_owner_only_candidate_filter(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    store = UserMemoryStore(memory_path)
    store.remember_target("private:20001", {"message_type": "private", "user_id": 20001})
    store.set_affection("private:20001", 5)
    payload = json.loads(memory_path.read_text(encoding="utf-8"))
    payload["conversations"]["private:20001"]["proactive_override"] = "allow"
    memory_path.write_text(json.dumps(payload), encoding="utf-8")
    policy = default_proactive_policy()
    policy["owner_only"] = True

    items = ProactivePlanner(store, (10001,), rng=random.Random(8)).status(
        policy,
        datetime(2026, 7, 14, 12, 0, tzinfo=CHINA),
    )["items"]
    forced = next(item for item in items if item["target_id"] == 20001)

    assert forced["eligible"] is True
    assert forced["eligibility_reason"] == "已手动允许"


def test_only_active_high_affection_non_owner_is_eligible(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "users.json")
    now = datetime(2026, 7, 14, 12, 0, tzinfo=CHINA)
    for user_id, affection in ((20001, 69), (20002, 80)):
        conversation_id = f"private:{user_id}"
        store.remember_target(conversation_id, {"message_type": "private", "user_id": user_id})
        for index in range(5):
            store.observe_user(conversation_id, f"第 {index} 条活跃消息", now=now.timestamp() + index)
        store.set_affection(conversation_id, affection)
        store.set_trust_tier(conversation_id, "approved")

    planner = ProactivePlanner(store, (), rng=random.Random(5))
    items = planner.status(default_proactive_policy(), now)["items"]
    by_id = {item["target_id"]: item for item in items}

    assert by_id[20001]["eligible"] is False
    assert by_id[20001]["eligibility_reason"] == "好感度未达门槛"
    assert by_id[20002]["eligible"] is True
    assert by_id[20002]["eligibility_reason"] == "高好感活跃用户"


def test_active_group_is_scheduled_and_new_group_message_resets_plan(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "users.json")
    now = datetime(2026, 7, 14, 12, 0, tzinfo=CHINA)
    group_id = 30001
    conversation_id = f"group:{group_id}"
    store.remember_target(conversation_id, {"message_type": "group", "group_id": group_id})
    for index in range(12):
        store.observe_group_message(
            group_id,
            40000 + index,
            f"群里的第 {index} 条公开讨论",
            now=now.timestamp() + index,
            addressed_to_bot=index % 3 == 0,
        )

    planner = ProactivePlanner(store, (), rng=random.Random(8))
    policy = default_proactive_policy()
    assert planner.due_plans(policy, now + timedelta(minutes=1)) == []
    state = store.proactive_state(conversation_id, now=(now + timedelta(minutes=1)).timestamp())
    assert state["next_at"] is not None

    store.observe_group_message(
        group_id,
        49999,
        "新消息来了，应该重新计算主动时间",
        now=(now + timedelta(minutes=2)).timestamp(),
    )
    assert store.proactive_state(
        conversation_id,
        now=(now + timedelta(minutes=2)).timestamp(),
    )["next_at"] is None


def test_group_generation_uses_public_group_context_and_guides_topic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="test-key",
        openai_base_url="https://example.invalid/v1",
        openai_model="test-model",
        temperature=0.7,
        max_tokens=180,
        memory_path=tmp_path / "users.json",
    )
    engine = AtriReplyEngine(config)
    engine.memory.observe_user("private:50001", "这是不能出现在群里的私密内容", now=1000)
    engine.memory.remember_target(
        "group:60001",
        {"message_type": "group", "group_id": 60001},
    )
    engine.memory.observe_group_message(
        60001,
        50001,
        "群里刚才在讨论学习方法",
        nickname="群友甲",
        now=1100,
    )
    captured: dict[str, object] = {"calls": 0}

    async def fake_post(client, headers, payload):
        captured["calls"] = int(captured["calls"]) + 1
        captured["messages"] = payload["messages"]
        if captured["calls"] == 1:
            return {"choices": [{"message": {"content": "我刚点进去看了下。如果只能改一个学习习惯，你们会先改哪一个？"}}]}
        return {"choices": [{"message": {"content": "如果只能改一个学习习惯，你们会先改时间安排还是复盘方式？"}}]}

    monkeypatch.setattr(engine, "_post_chat_completion", fake_post)
    result = asyncio.run(
        engine.generate_proactive_message(
            "group:60001",
            "guided_topic",
            default_proactive_policy(),
            datetime(2026, 7, 14, 20, 0, tzinfo=CHINA),
        )
    )
    prompt = "\n".join(str(message.get("content") or "") for message in captured["messages"])

    assert result["source"] == "ai-reviewed"
    assert captured["calls"] == 2
    assert "点进去" not in result["text"]
    assert "群里刚才在讨论学习方法" in prompt
    assert "这是不能出现在群里的私密内容" not in prompt
    assert "只能使用上面列出的群聊公开内容" in prompt
    assert "低门槛回应方向" in prompt
    assert "最近怎么样" in prompt
    assert "近期关键词" not in prompt
    assert "只有标记为“用户”的原话" in prompt
