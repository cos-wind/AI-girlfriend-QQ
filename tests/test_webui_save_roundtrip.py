"""端到端验证：WebUI 的两次保存请求都能正常落盘，且两张档位表不被互相覆盖。

覆盖用户遇到的「配置保存失败」：那次故障来自前端读了一个已被删除的输入框，
但真正要钉住的是**保存链路本身**——把前端会提交的 payload 原样喂给两个处理函数，
确认不抛异常、两张表都写进去、并且第二次保存不会把第一次的结果冲掉。
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from atri_qq_bot.proactive import policy as proactive_policy
from atri_qq_bot.runtime import reply_strategy
from atri_webui.server_parts.handler_config import HandlerConfigMixin


class _Recorder(HandlerConfigMixin):
    """只实现 handler 用到的 IO 部分，其余靠 mixin。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.sent: dict | None = None
        self.error: tuple | None = None

    def _read_json(self) -> dict:
        return self._payload

    def _send_json(self, payload: dict) -> None:
        self.sent = payload

    def _send_error(self, status, message: str) -> None:
        self.error = (status, message)

    # 只读检视模式相关；WebUIHandlerMixin.__getattribute__ 会做全局注入
    webui_state = SimpleNamespace()


@pytest.fixture()
def isolated_configs(tmp_path, monkeypatch):
    strategy_path = tmp_path / "reply_strategy.json"
    proactive_path = tmp_path / "proactive_policy.json"
    monkeypatch.setattr(reply_strategy, "REPLY_STRATEGY_PATH", strategy_path)
    monkeypatch.setattr(reply_strategy, "_CACHE", None)
    monkeypatch.setattr(proactive_policy, "PROACTIVE_POLICY_PATH", proactive_path)
    reply_strategy.save_reply_strategy(reply_strategy.default_reply_strategy(), strategy_path)
    return strategy_path, proactive_path


def _front_end_payload() -> dict:
    """模拟「保存全部配置」时前端组装的 payload（两张表 + 主动互动字段）。"""

    strategy = reply_strategy.load_reply_strategy()
    affection = [dict(tier) for tier in strategy["affection_tiers"]]
    activity = [dict(tier) for tier in strategy["activity_tiers"]]
    # 用户在界面上改了「熟悉」档的目标字数与两档的群间隔。
    for tier in affection:
        if tier["id"] == "familiar":
            tier["target_chars"] = 70
    for tier in activity:
        tier["min_hours"] = 2.0
        tier["max_hours"] = 5.0
        tier["daily_limit"] = 2

    return {
        "enabled": True,
        "owner_only": False,
        "use_ai": True,
        "guided_topics": True,
        "group_enabled": True,
        "timezone": "Asia/Shanghai",
        "quiet_start": "00:30",
        "quiet_end": "07:00",
        "check_seconds": 59,
        "ignored_backoff": 1.5,
        "history_limit": 8,
        "max_chars": 90,
        # 没有控件的门槛：必须靠底稿保留，不能变成 NaN/0
        "private_active_days": 20,
        "private_min_messages": 5,
        "group_active_days": 3,
        "group_min_messages": 6,
        "tiers": affection,
        "activity_tiers": activity,
        "content_weights": dict(strategy and proactive_policy.DEFAULT_PROACTIVE_POLICY["content_weights"]),
        "group_content_weights": dict(proactive_policy.DEFAULT_PROACTIVE_POLICY["group_content_weights"]),
    }


def test_proactive_save_route_accepts_both_tier_tables(isolated_configs) -> None:
    strategy_path, _ = isolated_configs
    payload = _front_end_payload()

    handler = _Recorder(payload)
    handler._handle_proactive_save()

    assert handler.error is None, handler.error
    assert handler.sent and handler.sent["ok"] is True

    saved = json.loads(strategy_path.read_text(encoding="utf-8"))
    affection = {tier["id"]: tier for tier in saved["affection_tiers"]}
    activity = {tier["id"]: tier for tier in saved["activity_tiers"]}
    assert affection["familiar"]["target_chars"] == 70
    assert activity["hot"]["min_hours"] == 2.0
    assert activity["hot"]["max_hours"] == 5.0
    assert activity["hot"]["daily_limit"] == 2


def test_reply_strategy_save_does_not_wipe_group_tiers(isolated_configs) -> None:
    """回复策略的保存入口也要带上 activity_tiers，否则群聊档位会被写回旧值。"""

    strategy_path, _ = isolated_configs
    payload = _front_end_payload()

    # 先按主动互动的入口存一次
    _Recorder(payload)._handle_proactive_save()

    # 再模拟「保存回复策略」：前端提交整份 policy（含两张表）
    strategy_payload = reply_strategy.load_reply_strategy()
    for tier in strategy_payload["affection_tiers"]:
        if tier["id"] == "close":
            tier["target_chars"] = 99

    handler = _Recorder(strategy_payload)
    handler._handle_reply_strategy_save()

    assert handler.error is None, handler.error
    saved = json.loads(strategy_path.read_text(encoding="utf-8"))
    activity = {tier["id"]: tier for tier in saved["activity_tiers"]}
    assert activity["hot"]["min_hours"] == 2.0  # 没有被回复策略的保存冲掉
    affection = {tier["id"]: tier for tier in saved["affection_tiers"]}
    assert affection["close"]["target_chars"] == 99


def test_proactive_save_preserves_controls_without_inputs(isolated_configs) -> None:
    """没有控件的那几个门槛必须原值保留，不能变成 0 或 NaN。"""

    _, proactive_path = isolated_configs
    payload = _front_end_payload()

    _Recorder(payload)._handle_proactive_save()

    saved = json.loads(proactive_path.read_text(encoding="utf-8"))
    assert saved["private_active_days"] == 20
    assert saved["private_min_messages"] == 5
    assert saved["group_active_days"] == 3
    assert saved["group_min_messages"] == 6
    assert saved["group_enabled"] is True
    # 档位表不进这个文件
    assert "tiers" not in saved
    assert "activity_tiers" not in saved


# ── 防清零守卫 ────────────────────────────────────────────────
# 真实事故：在合并逻辑里引用了一个"定义在函数之后"的模块级常量，模块能 import 成功
# （函数体不在 import 时执行），但**第一次真正调用**就抛 NameError，接口回 400。
# 这类错误 import 测试与标记测试都抓不到，必须真的调用一次合并函数。


def test_merge_does_not_zero_the_proactive_interval(isolated_configs) -> None:
    """提交里把 min_hours/max_hours 写成 0 时，必须保留已存数值。"""

    strategy_path, _ = isolated_configs
    reply_strategy.save_reply_strategy(
        reply_strategy.default_reply_strategy(), strategy_path
    )

    # 人为造一个"非零间隔"的已存状态
    policy = reply_strategy.load_reply_strategy(strategy_path, force=True)
    for tier in policy["activity_tiers"]:
        tier["min_hours"] = 7.0
        tier["max_hours"] = 11.0
    reply_strategy.save_reply_strategy(policy, strategy_path)

    # 模拟前端把空白输入框当成 0 提交
    zeroed = [
        {**tier, "min_hours": 0, "max_hours": 0}
        for tier in reply_strategy.load_reply_strategy(strategy_path, force=True)["activity_tiers"]
    ]
    merged = reply_strategy.merge_tier_table(
        zeroed, table="activity_tiers", fields=reply_strategy.ACTIVITY_TIER_FIELDS
    )

    assert merged is not None
    for tier in merged:
        assert tier["min_hours"] == 7.0, tier
        assert tier["max_hours"] == 11.0, tier


def test_merge_still_accepts_a_real_interval_change(isolated_configs) -> None:
    """正常改间隔必须生效——守卫只拦 0。"""

    strategy_path, _ = isolated_configs
    reply_strategy.save_reply_strategy(
        reply_strategy.default_reply_strategy(), strategy_path
    )
    current = reply_strategy.load_reply_strategy(strategy_path, force=True)["activity_tiers"]
    wanted = [{**tier, "min_hours": 2.5, "max_hours": 5.5} for tier in current]

    merged = reply_strategy.merge_tier_table(
        wanted, table="activity_tiers", fields=reply_strategy.ACTIVITY_TIER_FIELDS
    )

    assert merged is not None
    for tier in merged:
        assert tier["min_hours"] == 2.5, tier
        assert tier["max_hours"] == 5.5, tier


def test_merge_accepts_daily_limit_zero(isolated_configs) -> None:
    """daily_limit 的 0 是合法值（表示这一档不主动发消息），不能被守卫拦掉。"""

    strategy_path, _ = isolated_configs
    reply_strategy.save_reply_strategy(
        reply_strategy.default_reply_strategy(), strategy_path
    )
    current = reply_strategy.load_reply_strategy(strategy_path, force=True)["activity_tiers"]
    wanted = [{**tier, "daily_limit": 0} for tier in current]

    merged = reply_strategy.merge_tier_table(
        wanted, table="activity_tiers", fields=reply_strategy.ACTIVITY_TIER_FIELDS
    )

    assert merged is not None
    for tier in merged:
        assert tier["daily_limit"] == 0, tier


def test_every_tier_field_constant_the_merge_uses_is_defined() -> None:
    """合并用到的模块级常量必须在调用前就已定义。

    对应的真实事故：常量被写在 ``def merge_tier_table`` **之后**，模块 import 正常，
    第一次调用却抛 ``NameError: name '_NON_ZERO_TIER_FIELDS' is not defined``，
    接口回 400，用户看到"保存失败"。
    """

    import inspect

    source = inspect.getsource(reply_strategy)
    merge_start = source.index("def merge_tier_table(")
    body = source[merge_start:]

    # 找出合并函数体里引用的、全部大写的模块级常量
    used = set(re.findall(r"\b(_[A-Z][A-Z0-9_]*|[A-Z][A-Z0-9_]{2,})\b", body))
    for name in sorted(used):
        if not hasattr(reply_strategy, name):
            continue
        definition = re.search(rf"(?m)^{re.escape(name)}\s*[:=]", source)
        if definition is None:
            # 由别的模块 import 进来的常量，不在本文件的定义顺序约束内
            continue
        assert definition.start() < merge_start, (
            f"{name} 定义在 merge_tier_table 之后，调用时会抛 NameError"
        )
