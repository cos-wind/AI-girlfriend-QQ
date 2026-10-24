"""回复策略（按对象/好感度/活跃度的回复门控与频率上限）回归测试。"""

from __future__ import annotations

import time

import pytest

from atri_qq_bot.runtime import reply_strategy
from atri_qq_bot.runtime.reply_strategy import (
    DEFAULT_TIERS,
    REMOVED_DEFAULT_KEYS,
    default_reply_strategy,
    evaluate_reply,
    forced_event_block_reason,
    normalize_reply_strategy,
    object_requires_mention,
    record_reply,
)

NOW = 1_700_000_000.0


def _enabled_policy(**overrides):
    policy = default_reply_strategy()
    policy["enabled"] = True
    policy["defaults"].update(overrides.pop("defaults", {}))
    for key, value in overrides.items():
        policy[key] = value
    return policy


def _state():
    return {"version": 1, "objects": {}}


def test_disabled_policy_allows_everything() -> None:
    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        policy=default_reply_strategy(),
        state=_state(),
        now=NOW,
    )

    assert decision.allowed is True
    assert decision.reason == "策略未启用"


def test_object_deny_and_quiet_modes_block_reply() -> None:
    policy = _enabled_policy(users={"10001": {"mode": "deny"}})
    denied = evaluate_reply(
        scope="private", user_id="10001", policy=policy, state=_state(), now=NOW
    )
    assert denied.allowed is False
    assert "禁止" in denied.reason

    policy = _enabled_policy(groups={"20001": {"mode": "quiet"}})
    quiet = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert quiet.allowed is False
    assert "静默" in quiet.reason


def test_group_smart_mode_never_requires_mention() -> None:
    """smart 就是"不额外收紧"：被触发词叫起来也要能回，所以不能要求 @。

    历史值 allow/auto 与它等价。规则里遗留的 require_mention 字段不再参与判定
    ——界面上早已没有那个控件，模式下拉才是唯一可见、可改的开关。
    """

    for stored in ("smart", "allow", "auto"):
        policy = _enabled_policy(
            groups={"20001": {"mode": stored, "require_mention": True}}
        )
        free = evaluate_reply(
            scope="group",
            user_id="10001",
            group_id="20001",
            is_mention=False,
            policy=policy,
            state=_state(),
            now=NOW,
        )
        assert free.allowed is True, stored
        assert free.strategy["mode"] == "smart", stored

    # 没写这条例外的群跟随 defaults.unlisted_mode（默认 auto → smart）。
    policy = _enabled_policy()
    follows_default = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="29999",
        is_mention=False,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert follows_default.allowed is True


def test_mention_mode_requires_at_only_for_that_group() -> None:
    """「仅 @ 回复」是对象级模式：只收紧写它的那个群，不动别的群，也不看全局默认。"""

    policy = _enabled_policy(
        groups={"20001": {"mode": "mention"}},
        defaults={"group_require_mention": False},
    )

    without_mention = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=False,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert without_mention.allowed is False
    assert "@" in without_mention.reason

    with_mention = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert with_mention.allowed is True
    assert with_mention.strategy["mode"] == "mention"

    # 「仅 @ 回复」下续聊**不**放行：窗口会滑动续期，@ 一次之后该成员的表情和插话
    # 都会被持续当成续聊放行，表现就是"设了仅 @ 还自己冒泡"。
    continuation = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=False,
        is_continuation=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert continuation.allowed is False
    assert "@" in continuation.reason

    # 续聊窗口里带 @ 的消息仍然要回。
    continuation_with_mention = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=True,
        is_continuation=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert continuation_with_mention.allowed is True

    # 非 mention 模式的群，续聊照旧不要求重复 @。
    allow_policy = _enabled_policy(groups={"20001": {"mode": "allow"}})
    allow_continuation = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=False,
        is_continuation=True,
        policy=allow_policy,
        state=_state(),
        now=NOW,
    )
    assert allow_continuation.allowed is True

    # 没写这条模式的群照旧跟随全局默认。
    other_group = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="29999",
        is_mention=False,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert other_group.allowed is True


def test_mention_mode_beats_an_explicit_require_mention_false() -> None:
    """下拉里的模式是用户看得见的开关，应压过规则里遗留的 require_mention 字段。"""

    policy = _enabled_policy(
        groups={"20001": {"mode": "mention", "require_mention": False}}
    )
    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        is_mention=False,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert decision.allowed is False
    assert "@" in decision.reason


def test_mention_mode_on_a_user_object_behaves_like_auto() -> None:
    """@ 只存在于群聊；用户对象上误选「仅 @ 回复」不能把私聊彻底关掉。"""

    policy = _enabled_policy(users={"10001": {"mode": "mention"}})
    decision = evaluate_reply(
        scope="private",
        user_id="10001",
        affection=40.0,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.strategy["mode"] == "auto"


def test_mention_mode_survives_normalize_roundtrip() -> None:
    saved = normalize_reply_strategy(
        {
            "version": 1,
            "enabled": True,
            "groups": {"20001": {"name": "招新群", "mode": "mention"}},
        }
    )
    assert saved["groups"]["20001"]["mode"] == "mention"


def test_object_requires_mention_is_decided_by_the_group_mode() -> None:
    """OneBot 层靠它决定"要不要为这个对象打开续聊会话"。

    模式是唯一判据：smart 明确允许被触发词叫起来，所以不能要求 @；
    历史字段 require_mention 与全局 group_require_mention 都不再参与。
    """

    assert object_requires_mention(
        scope="group", group_id="20001", policy=_enabled_policy(groups={"20001": {"mode": "mention"}})
    ) is True
    for stored in ("smart", "allow", "auto", "silence", "quiet", "deny"):
        assert object_requires_mention(
            scope="group", group_id="20001", policy=_enabled_policy(groups={"20001": {"mode": stored}})
        ) is False, stored
    # 遗留字段不再翻盘。
    assert object_requires_mention(
        scope="group",
        group_id="20001",
        policy=_enabled_policy(groups={"20001": {"mode": "smart", "require_mention": True}}),
    ) is False
    assert object_requires_mention(
        scope="group", group_id="20001", policy=_enabled_policy(defaults={"group_require_mention": True})
    ) is False
    assert object_requires_mention(
        scope="group", group_id="20001", policy=_enabled_policy()
    ) is False
    # @ 只存在于群聊。
    assert object_requires_mention(
        scope="private", user_id="10001", policy=_enabled_policy(users={"10001": {"mode": "mention"}})
    ) is False


def test_group_mode_aliases_fold_legacy_values() -> None:
    """旧配置不需要手工迁移：等价语义直接折算到三种新模式下。"""

    saved = normalize_reply_strategy(
        {
            "version": 1,
            "enabled": True,
            "groups": {
                "20001": {"mode": "allow"},
                "20002": {"mode": "auto"},
                "20003": {"mode": "quiet"},
                "20004": {"mode": "deny"},
                "20005": {"mode": "mention"},
            },
            "users": {"10001": {"mode": "deny"}},
        }
    )
    assert saved["groups"]["20001"]["mode"] == "smart"
    assert saved["groups"]["20002"]["mode"] == "smart"
    assert saved["groups"]["20003"]["mode"] == "silence"
    assert saved["groups"]["20004"]["mode"] == "silence"
    assert saved["groups"]["20005"]["mode"] == "mention"
    # 私聊侧不动。
    assert saved["users"]["10001"]["mode"] == "deny"


def test_forced_event_block_respects_object_mode_but_not_frequency() -> None:
    """入群欢迎这类强制事件必须尊重对象级模式，但不能被频率/冷却误杀。"""

    # silence（含历史值 quiet/deny）与 mention 一律拦下。
    for stored in ("silence", "quiet", "deny"):
        assert "静默" in forced_event_block_reason(
            scope="group", group_id="20001", policy=_enabled_policy(groups={"20001": {"mode": stored}})
        ), stored
    assert "@" in forced_event_block_reason(
        scope="group", group_id="20001", policy=_enabled_policy(groups={"20001": {"mode": "mention"}})
    )
    # 私聊对象的 deny 仍然报"强制禁止"。
    assert forced_event_block_reason(
        scope="private", user_id="10001", policy=_enabled_policy(users={"10001": {"mode": "deny"}})
    ) == "对象策略强制禁止回复"

    # smart 放行——包括把冷却和每小时上限压到最紧的情况。
    for stored in ("smart", "allow", "auto"):
        policy = _enabled_policy(groups={"20001": {"mode": stored, "per_hour": 1}})
        policy["activity_tiers"][0]["cooldown_seconds"] = 3600.0
        assert forced_event_block_reason(
            scope="group", group_id="20001", policy=policy
        ) == "", stored

    # 未列入名单的对象跟随 defaults.unlisted_mode。
    assert "静默" in forced_event_block_reason(
        scope="group", group_id="20001", policy=_enabled_policy(defaults={"unlisted_mode": "deny"})
    )

    # 主人不受对象级模式约束；策略未启用时一律放行。
    assert forced_event_block_reason(
        scope="group",
        group_id="20001",
        is_owner=True,
        policy=_enabled_policy(groups={"20001": {"mode": "deny"}}),
    ) == ""
    disabled = default_reply_strategy()
    disabled["enabled"] = False
    assert forced_event_block_reason(scope="group", group_id="20001", policy=disabled) == ""


def test_owner_bypasses_gates_without_any_caps() -> None:
    """主人不受对象级禁言约束，也不再有任何频率上限。"""

    policy = _enabled_policy(users={"10001": {"mode": "deny"}})
    allowed = evaluate_reply(
        scope="private",
        user_id="10001",
        affection=40.0,
        is_owner=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert allowed.allowed is True


def test_affection_floor_is_expressed_by_the_tier_table() -> None:
    """好感度门槛只有分档表这一个入口：停用低档就等于设了门槛。"""

    policy = _enabled_policy()
    tier_limited = evaluate_reply(
        scope="private",
        user_id="10001",
        affection=40.0,  # 命中「普通」档：目标 48 字
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert tier_limited.allowed is True
    assert tier_limited.strategy["target_reply_chars"] == 48

    # 停用「普通」档后，同一个好感度就不再回复——这就是门槛本身。
    policy["affection_tiers"][1]["enabled"] = False
    blocked = evaluate_reply(
        scope="private",
        user_id="10001",
        affection=40.0,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert blocked.allowed is False
    assert "档位" in blocked.reason


def test_group_activity_floor_is_expressed_by_the_tier_table() -> None:
    """群活跃度门槛同理：低活跃命中「安静」档，默认停用即不回复。"""

    policy = _enabled_policy()
    quiet_group = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=12.5,  # 命中「安静」档（0-20），该档默认停用
        is_mention=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert quiet_group.allowed is False
    assert "档位" in quiet_group.reason

    # 启用「安静」档后低活跃群就能回复了，说明拦人的是档位状态而不是别的门槛。
    policy["activity_tiers"][0]["enabled"] = True
    allowed = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=12.5,
        is_mention=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert allowed.allowed is True
    assert allowed.strategy["tier_id"] == "quiet"


def test_unlisted_objects_follow_defaults_mode() -> None:
    policy = _enabled_policy(
        defaults={"unlisted_mode": "deny"},
        users={"10001": {"mode": "allow"}},
    )
    assert (
        evaluate_reply(
            scope="private", user_id="10001", policy=policy, state=_state(), now=NOW
        ).allowed
        is True
    )
    blocked = evaluate_reply(
        scope="private", user_id="70007", policy=policy, state=_state(), now=NOW
    )
    assert blocked.allowed is False
    assert "禁止" in blocked.reason


def test_unlisted_mode_defaults_to_auto_for_compatibility() -> None:
    policy = _enabled_policy()
    assert policy["defaults"]["unlisted_mode"] == "auto"
    assert (
        evaluate_reply(
            scope="private", user_id="70007", policy=policy, state=_state(), now=NOW
        ).allowed
        is True
    )


def test_group_activity_tier_drives_soft_length_guidance() -> None:
    policy = _enabled_policy()
    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=50.0,  # 命中「活跃」档
        is_mention=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )

    assert decision.allowed is True
    assert decision.strategy["tier_id"] == "active"
    assert decision.strategy["target_reply_chars"] == 44
    # 频率字段已移除，不再出现在返回策略里。
    assert "per_hour" not in decision.strategy
    assert "cooldown_seconds" not in decision.strategy


def test_disabled_tier_blocks_even_with_mention() -> None:
    policy = _enabled_policy()
    # 「安静」档默认停用：低活跃群即使被 @ 也不回。
    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=5.0,
        is_mention=True,
        policy=policy,
        state=_state(),
        now=NOW,
    )

    assert decision.allowed is False
    assert "档位" in decision.reason


def test_disabled_tier_is_the_only_audience_threshold() -> None:
    """"好感/活跃度不够就不回"由分档表达，不再有第二套受众门槛。

    这里同时钉住两件事：停用低档等于门槛，且被移除的旧门槛字段不再参与判断。
    """

    policy = _enabled_policy(
        defaults={
            # 这些字段已经废弃，即使旧配置里还留着也不该影响判定。
            "private_min_affection": 90,
            "private_min_messages": 999,
            "private_active_days": 1,
            "group_min_activity": 90,
            "group_min_messages": 999,
            "group_active_days": 1,
        }
    )

    # 「普通」档（35-55）仍可回复：好感 40 没有触发任何门槛拦截。
    allowed = evaluate_reply(
        scope="private",
        user_id="1",
        affection=40.0,
        message_count=1,
        active_days=900.0,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert allowed.allowed is True
    assert allowed.strategy["tier_id"] == "normal"

    # 真正的门槛做法：停用「普通」档，同一个好感度就不再回复。
    policy["affection_tiers"][1]["enabled"] = False
    blocked = evaluate_reply(
        scope="private",
        user_id="1",
        affection=40.0,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert blocked.allowed is False
    assert "档位" in blocked.reason


def test_group_mention_requirement_comes_only_from_the_mode() -> None:
    """群聊的 @ 要求只由模式决定；遗留的 group_require_mention 字段不再翻盘。

    界面上那两个控件（全局「群里必须 @ 才回」与规则里的 require_mention）都已删除，
    留着半生效的隐藏开关正是"改了不生效"的来源。
    """

    policy = _enabled_policy(defaults={"group_require_mention": True})
    decision = evaluate_reply(
        scope="group",
        user_id="1",
        group_id="2",
        activity=50.0,
        is_mention=False,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.strategy["mode"] == "smart"

    # 只有 mention 模式才拦。
    policy = _enabled_policy(groups={"2": {"mode": "mention"}})
    decision = evaluate_reply(
        scope="group",
        user_id="1",
        group_id="2",
        activity=50.0,
        is_mention=False,
        policy=policy,
        state=_state(),
        now=NOW,
    )
    assert decision.allowed is False and "@" in decision.reason


def test_private_cooldown_no_longer_blocks_rapid_replies() -> None:
    """冷却已移除：即使刚回过、档位里还留着 cooldown_seconds，也不该拦。"""

    policy = _enabled_policy()
    policy["affection_tiers"][2]["cooldown_seconds"] = 60.0  # 「熟悉」档（已不再生效）
    state = _state()
    reply_strategy._object_bucket(state, "private:10001", NOW)["last_reply_at"] = NOW - 10

    decision = evaluate_reply(
        scope="private",
        user_id="10001",
        affection=60.0,
        policy=policy,
        state=state,
        now=NOW,
    )

    assert decision.allowed is True


def test_preview_limits_reports_tier_and_effective_caps() -> None:
    policy = _enabled_policy()

    user_preview = reply_strategy.preview_limits(kind="user", value=60.0, policy=policy)
    assert user_preview["tier"]["id"] == "familiar"
    assert user_preview["limits"]["per_hour"] == 5
    assert user_preview["limits"]["target_chars"] == 64
    assert user_preview["enabled"] is True

    group_preview = reply_strategy.preview_limits(kind="group", value=75.0, policy=policy)
    assert group_preview["tier"]["id"] == "hot"
    assert group_preview["limits"]["cooldown_seconds"] == 240.0

    disabled_preview = reply_strategy.preview_limits(kind="user", value=10.0, policy=policy)
    assert disabled_preview["enabled"] is False
    assert "停用" in disabled_preview["note"]


def test_group_cooldown_and_hourly_caps_are_removed() -> None:
    """群冷却与每小时上限都已移除：即使刚回过、计数已满，也不该再拦。"""

    policy = _enabled_policy()
    # 活跃度 60 → 「活跃」档；残留字段不再参与判定。
    policy["activity_tiers"][2]["per_hour"] = 8
    policy["activity_tiers"][2]["cooldown_seconds"] = 180.0
    state = _state()
    bucket = reply_strategy._object_bucket(state, "group:20001", NOW)
    bucket["last_reply_at"] = NOW - 30
    bucket["hour_count"] = 8

    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=60.0,
        is_mention=True,
        policy=policy,
        state=state,
        now=NOW,
    )
    assert decision.allowed is True


def test_group_replies_are_not_capped_by_frequency_at_all() -> None:
    """频率上限整体移除：同一成员反复说话、计数再高也不拦（只由模式/档位启用决定）。"""

    policy = _enabled_policy()
    state = _state()
    bucket = reply_strategy._object_bucket(state, "group:20001", NOW)
    bucket["last_reply_at"] = NOW - 10
    bucket["hour_count"] = 99
    bucket["recent"] = [NOW - 1, NOW - 2, NOW - 3]
    bucket["users"] = {
        "10001": {"hour_key": reply_strategy._hour_key(NOW), "hour_count": 99}
    }

    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=60.0,
        is_mention=True,
        is_continuation=True,
        policy=policy,
        state=state,
        now=NOW,
    )
    assert decision.allowed is True, decision.reason


def test_continuation_cap_no_longer_blocks_group_chat() -> None:
    """连聊上限已移除：续聊窗口里回复再多也不拦。"""

    policy = _enabled_policy()
    policy["activity_tiers"][2]["continuation_max"] = 2  # 已不再生效
    state = _state()
    bucket = reply_strategy._object_bucket(state, "group:20001", NOW)
    bucket["last_reply_at"] = NOW - 400
    bucket["recent"] = [NOW - 10, NOW - 20]

    decision = evaluate_reply(
        scope="group",
        user_id="10001",
        group_id="20001",
        activity=60.0,
        is_mention=False,
        is_continuation=True,
        policy=policy,
        state=state,
        now=NOW,
    )
    assert decision.allowed is True


def test_active_hours_window() -> None:
    policy = _enabled_policy(
        defaults={"active_hours_start": "08:00", "active_hours_end": "23:00"}
    )
    # NOW 是 22:13（本地时间取决于时区），用显式时间点覆盖两种情形。
    midnight = time.mktime(time.strptime("2026-01-01 03:00", "%Y-%m-%d %H:%M"))
    daytime = time.mktime(time.strptime("2026-01-01 12:00", "%Y-%m-%d %H:%M"))
    assert (
        evaluate_reply(
            scope="private", user_id="10001", policy=policy, state=_state(), now=midnight
        ).allowed
        is False
    )
    assert (
        evaluate_reply(
            scope="private", user_id="10001", policy=policy, state=_state(), now=daytime
        ).allowed
        is True
    )


def test_record_reply_updates_counters_and_persists(tmp_path) -> None:
    state_path = tmp_path / "reply_strategy_state.json"
    record_reply(scope="group", user_id="10001", group_id="20001", now=NOW, state_path=state_path)
    record_reply(scope="group", user_id="10001", group_id="20001", now=NOW, state_path=state_path)

    state = reply_strategy.load_reply_state(state_path)
    bucket = state["objects"]["group:20001"]
    assert bucket["hour_count"] == 2
    assert bucket["day_count"] == 2
    # 只按对象（群/私聊对象）计数：曾经还有一个按群成员的 users 子桶，只服务于已删除的
    # "每人每小时"上限，现在不再记录。
    assert "users" not in bucket
    assert state_path.exists()


def test_update_object_rule_merges_single_object(tmp_path) -> None:
    path = tmp_path / "reply_strategy.json"
    reply_strategy.save_reply_strategy({"enabled": True}, path)

    created = reply_strategy.update_object_rule(
        "user", "10001", {"mode": "allow", "per_hour": 2}, name="好友", path=path
    )
    assert created["rule"]["mode"] == "allow"
    assert created["rule"]["per_hour"] == 2
    assert created["rule"]["name"] == "好友"

    # 后续局部更新必须保留已有字段，而不是整体覆盖。
    updated = reply_strategy.update_object_rule("user", "10001", {"per_day": 5}, path=path)
    assert updated["rule"]["mode"] == "allow"
    assert updated["rule"]["per_hour"] == 2
    assert updated["rule"]["per_day"] == 5

    # 群规则不能带好感字段，用户规则不能带活跃度/@ 字段。
    # 群聊模式会折算成三种新值：deny 与 quiet 语义等价，都落到 silence。
    group = reply_strategy.update_object_rule(
        "group", "20001", {"mode": "deny", "min_affection": 50}, path=path
    )
    assert "min_affection" not in group["rule"]
    assert group["rule"]["mode"] == "silence"

    user = reply_strategy.update_object_rule(
        "user", "10001", {"min_activity": 60, "require_mention": True}, path=path
    )
    assert "min_activity" not in user["rule"]
    assert "require_mention" not in user["rule"]

    removed = reply_strategy.update_object_rule("user", "10001", {}, remove=True, path=path)
    assert removed["rule"] is None

    with pytest.raises(ValueError):
        reply_strategy.update_object_rule("user", "abc", {}, path=path)


def test_save_and_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "reply_strategy.json"
    saved = reply_strategy.save_reply_strategy(
        {
            "enabled": True,
            "defaults": {
                # 已删除的全局限额：提交进来也不该复活（旧配置文件里可能还留着）。
                "group_replies_per_user_per_hour": 3,
                "active_hours_start": "7:5",
            },
            "users": {"10001": {"name": "测试", "mode": "allow", "per_day": 5}},
            "groups": {"20001": {"require_mention": False}},
        },
        path,
    )
    assert saved["enabled"] is True
    assert "group_replies_per_user_per_hour" not in saved["defaults"]
    assert saved["defaults"]["active_hours_start"] == "07:05"  # 归一化成 HH:MM
    assert saved["users"]["10001"]["mode"] == "allow"

    loaded = reply_strategy.load_reply_strategy(path, force=True)
    assert loaded == saved


def test_normalize_drops_invalid_ids_and_clamps_ranges() -> None:
    policy = normalize_reply_strategy(
        {
            "enabled": "true",
            "defaults": {
                # 这几项已经废弃，一起验证它们不会复活。
                "group_reply_cooldown_seconds": -50,
                "private_replies_per_hour": "999999",
                "group_replies_per_user_per_hour": 2,
                "target_reply_chars": -10,
                "active_hours_start": "99:99",
            },
            "users": {
                "not-a-number": {"mode": "deny"},
                "10001": {"mode": "unknown", "per_hour": -5},
            },
            "groups": {"20001": {"min_activity": 300}},
        }
    )

    assert policy["enabled"] is True
    for removed in REMOVED_DEFAULT_KEYS:
        assert removed not in policy["defaults"], removed
    assert policy["defaults"]["target_reply_chars"] == 0
    assert policy["defaults"]["active_hours_start"] == ""
    assert "not-a-number" not in policy["users"]
    assert policy["users"]["10001"]["mode"] == "auto"
    assert policy["users"]["10001"]["per_hour"] == 0
    assert policy["groups"]["20001"]["min_activity"] == 100.0


def test_tier_zero_means_unlimited_by_defaults_are_concrete() -> None:
    """档位里填 0 = 不限制；没提交的字段用档位默认值（具体数字，不是 0）。

    这样界面读到的永远是"实际生效的数值"，不再有一片分不清含义的 0。
    """

    policy = normalize_reply_strategy(
        {
            "enabled": True,
            "affection_tiers": [
                {"id": "low", "per_hour": 0, "target_chars": 0, "max_parts": 0},
                {"id": "familiar"},
            ],
        }
    )

    zeroed = policy["affection_tiers"][0]
    assert zeroed["per_hour"] == 0  # 用户显式填 0 = 不限制
    assert zeroed["target_chars"] == 0
    assert zeroed["max_parts"] == 0

    # 没提交的字段回落到该档位自己的默认值（按 id 匹配，不受提交顺序影响）。
    untouched = next(t for t in policy["affection_tiers"] if t["id"] == "familiar")
    assert untouched["per_hour"] == DEFAULT_TIERS[2]["per_hour"] == 5
    assert untouched["target_chars"] == 64
    assert untouched["max_parts"] == 2
    # 默认档位表里没有一个"继承占位"的 0（daily_limit 的 0 是"不主动发消息"，是真实值）。
    for tier in DEFAULT_TIERS:
        assert tier["per_hour"] > 0
        assert tier["per_day"] > 0
        assert tier["target_chars"] > 0


# ── 与 OneBot 主流程的接线 ──────────────────────────────────


def _fake_server(*, affection: float = 10.0, activity: float = 5.0):
    from types import SimpleNamespace

    def proactive_state(conversation_id: str, is_owner: bool = False):
        return {
            "affection_score": affection,
            "group_activity_score": activity,
        }

    return SimpleNamespace(
        config=SimpleNamespace(bot_qq=999, owner_qqs=()),
        reply_engine=SimpleNamespace(
            memory=SimpleNamespace(proactive_state=proactive_state)
        ),
    )


def _sync_event_mixin_globals() -> None:
    """复刻 server_support 的全局注入，让 mixin 方法能在无真实服务端时运行。"""

    from atri_qq_bot.onebot.reply_policy import is_bot_mentioned
    from atri_qq_bot.onebot.server_parts import server_events as events

    events.is_bot_mentioned = is_bot_mentioned
    events.evaluate_reply = evaluate_reply
    events.load_reply_strategy = reply_strategy.load_reply_strategy
    events.ReplyDecision = reply_strategy.ReplyDecision


def test_gate_blocks_denied_object(monkeypatch, tmp_path) -> None:
    from atri_qq_bot.onebot.server_parts import server_events as events

    _sync_event_mixin_globals()
    path = tmp_path / "reply_strategy.json"
    reply_strategy.save_reply_strategy(
        {"enabled": True, "users": {"10001": {"mode": "deny"}}}, path
    )
    monkeypatch.setattr(reply_strategy, "REPLY_STRATEGY_PATH", path)
    monkeypatch.setattr(reply_strategy, "_CACHE", None)

    decision = events.OneBotEventMixin._evaluate_reply_strategy(
        _fake_server(),
        {"message_type": "private", "user_id": "10001"},
        profile_id="private:10001",
        plain_text="在吗",
        is_owner=False,
        is_continuation=False,
    )

    assert decision.allowed is False
    assert "禁止" in decision.reason


def test_gate_allows_when_policy_disabled(monkeypatch, tmp_path) -> None:
    from atri_qq_bot.onebot.server_parts import server_events as events

    _sync_event_mixin_globals()
    path = tmp_path / "reply_strategy.json"
    reply_strategy.save_reply_strategy({"enabled": False}, path)
    monkeypatch.setattr(reply_strategy, "REPLY_STRATEGY_PATH", path)
    monkeypatch.setattr(reply_strategy, "_CACHE", None)

    decision = events.OneBotEventMixin._evaluate_reply_strategy(
        _fake_server(),
        {"message_type": "group", "user_id": "10001", "group_id": "20001"},
        profile_id="group:20001:user:10001",
        plain_text="随便聊聊",
        is_owner=False,
        is_continuation=False,
    )

    assert decision.allowed is True
    assert decision.reason == "策略未启用"


def test_length_strategy_prompt_is_no_longer_injected() -> None:
    """长度/分条不再作为死命令注入系统提示词；函数恒定返回 None。"""

    from atri_qq_bot.onebot.server_parts import server_events as events

    _sync_event_mixin_globals()
    fake = _fake_server()

    assert events.OneBotEventMixin._reply_strategy_system_prompt(fake, None) is None
    assert events.OneBotEventMixin._reply_strategy_system_prompt(fake, {}) is None
    assert (
        events.OneBotEventMixin._reply_strategy_system_prompt(
            fake,
            {"target_reply_chars": 48, "min_reply_chars": 24, "max_reply_parts": 2},
        )
        is None
    )
