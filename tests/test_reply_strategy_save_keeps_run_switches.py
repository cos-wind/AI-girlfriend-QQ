"""「运行规则」控件删除后的回归：保存不能把 enabled / 未列入名单 / 活跃时段改掉。

背景：这三个控件已从界面移除，策略改为常开。`collectReplyStrategyPolicy()` 以前从
DOM 读它们，元素消失后 `$('...')` 返回 null，那个写法会把 enabled 提交成 false
——一次普通的「保存全部配置」就会静默关掉整个策略。这个测试把行为钉住。
"""

from __future__ import annotations

from atri_webui.page import render_index


def _collect_source() -> str:
    html = render_index()
    start = html.index("function collectReplyStrategyPolicy()")
    end = html.index("async function saveReplyAndProactive(", start)
    return html[start:end]


def test_save_no_longer_reads_the_removed_run_controls() -> None:
    source = _collect_source()

    for element in (
        "replyStrategyEnabled",
        "replyUnlistedMode",
        "replyActiveHoursStart",
        "replyActiveHoursEnd",
    ):
        assert element not in source, f"保存流程仍在读 {element}"


def test_save_keeps_enabled_and_hours_from_the_server_policy() -> None:
    """以服务端 policy 为底稿时，这三项必须原样带回去。"""

    source = _collect_source()

    # confirm 底稿来自服务端 policy，而不是重新拼一个 defaults 对象。
    assert "JSON.parse(JSON.stringify(replyStrategyPolicy()))" in source
    # confirm 没有把这几个键重新赋值。
    for key in ("base.enabled", "defaults.unlisted_mode", "defaults.active_hours_start",
                "defaults.active_hours_end"):
        assert key not in source, f"保存流程仍在改写 {key}"


def test_handler_still_accepts_full_policy_payload() -> None:
    """后端仍以整份 policy 落盘，所以前端不提交就会保留原值（这是上面结论的前提）。"""

    from atri_qq_bot.runtime.reply_strategy import (
        default_reply_strategy,
        normalize_reply_strategy,
    )

    baseline = default_reply_strategy()
    baseline["enabled"] = True
    # 模拟前端只提交了 defaults 里的一部分键。
    saved = normalize_reply_strategy(
        {
            "version": baseline["version"],
            "enabled": True,
            "defaults": {"group_require_mention": False},
            "affection_tiers": baseline["affection_tiers"],
            "activity_tiers": baseline["activity_tiers"],
            "users": {},
            "groups": {},
        }
    )

    assert saved["enabled"] is True
    assert saved["defaults"]["unlisted_mode"] == "auto"
    assert saved["defaults"]["active_hours_start"] == ""
    assert saved["defaults"]["active_hours_end"] == ""
    assert len(saved["affection_tiers"]) == 5


def test_unlisted_mode_choices_are_documented_in_the_code() -> None:
    """模式词汇必须和后端一致：群聊三种，私聊四种，历史值由别名折算。"""

    from atri_qq_bot.runtime.reply_strategy import (
        GROUP_MODES,
        MODES,
        USER_MODES,
    )

    assert set(GROUP_MODES) == {"smart", "mention", "silence"}
    assert set(USER_MODES) == {"auto", "allow", "deny", "quiet"}
    assert set(MODES) >= set(GROUP_MODES) | set(USER_MODES)
    # 旧值必须仍然可解析，否则老配置会在界面上选不中任何一项。
    for legacy in ("auto", "allow", "deny", "quiet", "mention", "smart", "silence"):
        assert legacy in MODES, legacy


def test_no_stale_references_to_removed_controls() -> None:
    html = render_index()

    for stale in (
        "replyStrategySetInputValue",
        "$('replyStrategyEnabled')",
        "$('replyUnlistedMode')",
        "$('replyActiveHoursStart')",
        "$('replyActiveHoursEnd')",
        "$('replyGroupRequireMention')",
    ):
        assert stale not in html, stale

    # 只查脚本引用是不够的：真实事故是脚本侧删干净了、**标记**却留了下来，
    # 于是界面上出现"能改但不生效"的死控件，而上面那组断言全绿。
    # 元素本身也必须不在。
    for removed_id in (
        "replyStrategyEnabled",
        "replyUnlistedMode",
        "replyActiveHoursStart",
        "replyActiveHoursEnd",
        "replyGroupRequireMention",
    ):
        assert f'id="{removed_id}"' not in html, f"{removed_id} 的控件已被移除，标记必须一起删"

    # 状态行已删除；重置计数改为在 toast 里报用量，保证点击有反馈。
    assert 'id="replyStrategyState"' not in html
    assert "频率计数已重置" in html
    assert "本小时已回 " in html
