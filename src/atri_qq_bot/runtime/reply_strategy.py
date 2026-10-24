"""按对象配置的回复策略：是否回复、回复频率、回复长度。

设计要点
--------
* **三层优先级**：全局默认（``defaults``）→ 按好感度分档（``affection_tiers``）
  → 对象级覆盖（``users`` / ``groups``）。对象级只能收紧，不会放宽全局上限，
  避免"点错一下把整个群放开"。
* **默认不启用**：``enabled=false`` 时本模块一律放行，保持升级前的行为不变。
* **配置与计数分离**：策略写在 ``reply_strategy.json``（WebUI 写），频率计数写在
  ``reply_strategy_state.json``（OneBot 进程写），互不覆盖。
* **保存即生效**：读取带 mtime 缓存，WebUI 保存后下一次回复决策就生效，无需重启。
* **档位是唯一来源**：``affection_tiers`` 里的「档位 / 好感范围 / 启用」同时被回复
  门控（本模块 ``evaluate_reply``）和主动互动调度（``proactive.planner``）使用。
  主动互动侧只额外追加 ``min_hours`` / ``max_hours`` / ``daily_limit`` 三个频率字段，
  不再自己维护一张好感档位表——历史上两张表的好感范围完全重复，改一处漏一处。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import REPLY_STRATEGY_PATH, REPLY_STRATEGY_STATE_PATH

# 群聊的对象级模式只有三个，和界面上那个下拉一一对应：
#   smart   —— 被 @ 或命中触发词就回；被 @ 之后 5 分钟内不用再 @（续聊窗口）
#   mention —— 每一轮都要 @（续聊窗口不放行，也不打开）
#   silence —— 沉默，只观察不回复
# auto / allow / deny / quiet 是历史值：auto/allow 归一成 smart，quiet/deny 归一成 silence，
# 私聊对象不使用 @ 相关的模式。
GROUP_MODES = ("smart", "mention", "silence")
USER_MODES = ("auto", "allow", "deny", "quiet")
# 旧值到新值的映射。语义等价：allow/auto 就是不额外收紧，quiet/deny 都是不回。
GROUP_MODE_ALIASES = {
    "auto": "smart",
    "allow": "smart",
    "quiet": "silence",
    "deny": "silence",
    # 私聊专用的 auto 落到群聊时也按"不额外收紧"处理。
}
MODES = tuple(dict.fromkeys(GROUP_MODES + USER_MODES + tuple(GROUP_MODE_ALIASES)))
MAX_OBJECTS = 500
MAX_RECENT_REPLIES = 20
CONTINUATION_WINDOW_SECONDS = 300.0

# 档位里与「主动互动」共用的三个频率字段的取值范围；回复侧字段的取值范围见
# normalize_reply_strategy。这里集中定义，避免两处各写一份魔法数字。
PROACTIVE_TIER_DEFAULTS: tuple[tuple[str, float, float], ...] = (
    ("min_hours", 0.25, 168.0),
    ("max_hours", 0.25, 336.0),
)

# 群聊分档里几个"没有独立控件"的兜底值。以前它们在档位表里写 0，靠判定处回落到
# defaults；现在直接写具体数值，界面读到什么就是实际生效什么。
GROUP_TIER_COOLDOWN_SECONDS = 180.0
GROUP_TIER_CONTINUATION_MAX = 3
GROUP_TIER_TARGET_CHARS = 48

# 主动发起的随机间隔：越亲近间隔越短；daily_limit 为 0 表示这一档不主动发消息。
# 各档的每小时/每日上限、冷却、目标字数都写具体数值——0 只保留"不限制"这一种含义，
# 不再兼作"继承全局默认"的占位符（那种写法在界面上会显示成 0，很容易被误读）。
DEFAULT_TIERS: tuple[dict[str, Any], ...] = (
    {
        "id": "low",
        "name": "较低",
        "min_affection": 0.0,
        "max_affection": 35.0,
        "enabled": False,
        "per_hour": 30,
        "per_day": 200,
        "cooldown_seconds": 0.0,
        "target_chars": 48,
        "max_parts": 2,
        "min_hours": 18.0,
        "max_hours": 30.0,
        "daily_limit": 0,
    },
    {
        "id": "normal",
        "name": "普通",
        "min_affection": 35.0,
        "max_affection": 55.0,
        "enabled": True,
        "per_hour": 3,
        "per_day": 15,
        "cooldown_seconds": 0.0,
        "target_chars": 48,
        "max_parts": 2,
        "min_hours": 10.0,
        "max_hours": 24.0,
        "daily_limit": 1,
    },
    {
        "id": "familiar",
        "name": "熟悉",
        "min_affection": 55.0,
        "max_affection": 70.0,
        "enabled": True,
        "per_hour": 5,
        "per_day": 25,
        "cooldown_seconds": 0.0,
        "target_chars": 64,
        "max_parts": 2,
        "min_hours": 5.0,
        "max_hours": 14.0,
        "daily_limit": 2,
    },
    {
        "id": "close",
        "name": "亲近",
        "min_affection": 70.0,
        "max_affection": 85.0,
        "enabled": True,
        "per_hour": 8,
        "per_day": 40,
        "cooldown_seconds": 0.0,
        "target_chars": 72,
        "max_parts": 3,
        "min_hours": 2.5,
        "max_hours": 9.0,
        "daily_limit": 3,
    },
    {
        "id": "intimate",
        "name": "亲密",
        "min_affection": 85.0,
        "max_affection": 101.0,
        "enabled": True,
        "per_hour": 12,
        "per_day": 60,
        "cooldown_seconds": 0.0,
        "target_chars": 80,
        "max_parts": 3,
        "min_hours": 1.5,
        "max_hours": 6.0,
        "daily_limit": 4,
    },
)

# 群聊主动消息的间隔与每日上限：和用户分档同构，也写在档位表里。
# 默认值沿用原来那几个全局字段的值，避免升级后行为悄悄改变。
GROUP_PROACTIVE_MIN_HOURS = 3.0
GROUP_PROACTIVE_MAX_HOURS = 9.0
GROUP_PROACTIVE_DAILY_LIMIT = 2

# 群聊按「群活跃度」分档，设计对齐主动互动的分档表：越活跃的群越克制，
# 避免在高频群里刷屏。右两列（间隔 / 每日上限）同样供主动消息使用。
DEFAULT_ACTIVITY_TIERS: tuple[dict[str, Any], ...] = (
    {
        "id": "quiet",
        "name": "安静",
        "min_activity": 0.0,
        "max_activity": 20.0,
        "enabled": False,
        "per_hour": 8,
        "per_day": 40,
        "cooldown_seconds": GROUP_TIER_COOLDOWN_SECONDS,
        "continuation_max": GROUP_TIER_CONTINUATION_MAX,
        "target_chars": GROUP_TIER_TARGET_CHARS,
        "min_hours": GROUP_PROACTIVE_MIN_HOURS,
        "max_hours": GROUP_PROACTIVE_MAX_HOURS,
        "daily_limit": 0,
    },
    {
        "id": "normal",
        "name": "一般",
        "min_activity": 20.0,
        "max_activity": 45.0,
        "enabled": True,
        "per_hour": 4,
        "per_day": 20,
        "cooldown_seconds": 180.0,
        "continuation_max": 2,
        "target_chars": 40,
        "min_hours": GROUP_PROACTIVE_MIN_HOURS,
        "max_hours": GROUP_PROACTIVE_MAX_HOURS,
        "daily_limit": GROUP_PROACTIVE_DAILY_LIMIT,
    },
    {
        "id": "active",
        "name": "活跃",
        "min_activity": 45.0,
        "max_activity": 70.0,
        "enabled": True,
        "per_hour": 8,
        "per_day": 40,
        "cooldown_seconds": 180.0,
        "continuation_max": 3,
        "target_chars": 44,
        "min_hours": GROUP_PROACTIVE_MIN_HOURS,
        "max_hours": GROUP_PROACTIVE_MAX_HOURS,
        "daily_limit": GROUP_PROACTIVE_DAILY_LIMIT,
    },
    {
        "id": "hot",
        "name": "高热",
        "min_activity": 70.0,
        "max_activity": 101.0,
        "enabled": True,
        "per_hour": 12,
        "per_day": 60,
        "cooldown_seconds": 240.0,
        "continuation_max": 3,
        "target_chars": 48,
        "min_hours": GROUP_PROACTIVE_MIN_HOURS,
        "max_hours": GROUP_PROACTIVE_MAX_HOURS,
        "daily_limit": GROUP_PROACTIVE_DAILY_LIMIT,
    },
)

DEFAULT_DEFAULTS: dict[str, Any] = {
    # 没有单独配置规则的对象走哪种模式：auto 跟随好感/活跃分档；
    # 想做到"只跟名单里的人聊"就把它设成 deny（或 quiet）。
    "unlisted_mode": "auto",
    # 注意：这里**没有**好感度/活跃度/活跃期/消息量这类"受众门槛"。这类门槛
    # 完全由分档表的好感范围表达——把关掉某一档、或把最低档的 min_affection
    # 调高，效果和"低于门槛就不回"完全一致，而分档表还能顺带决定频率与长度。
    # 曾经这里也有一份同义的受众门槛，结果是同一件事有两个入口，改了一处
    # 另一处还在拦人。
    "group_require_mention": False,
    "target_reply_chars": 0,
    "min_reply_chars": 0,
    "max_reply_parts": 0,
    "active_hours_start": "",
    "active_hours_end": "",
}
# 这些曾经是"全局限额"，判定时作为档位为 0 时的回落值。现在档位表一律写具体
# 数值、不再有 0 回落，它们已经没有任何读取点，删掉以免留下"改了不生效"的旋钮。
REMOVED_DEFAULT_KEYS: tuple[str, ...] = (
    "group_replies_per_hour",
    "group_replies_per_day",
    "group_reply_cooldown_seconds",
    "continuation_max_replies",
    "private_replies_per_hour",
    "private_replies_per_day",
    # 群内"每人每小时"的上限：与分档表的每小时/每日上限语义重复，而且它排在判定
    # 顺序最后、数值又最小（2），实际总是它先拦——界面上调档位怎么调都绕不过它，
    # 表现就是"我把每小时上限设成 75，第 3 句还是被拦"。频率一律由分档表说了算。
    "group_replies_per_user_per_hour",
)

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_MTIME_NS: int | None = None
_STATE_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReplyDecision:
    """一次回复决策的结果；``strategy`` 只包含真正生效的长度/续聊参数。"""

    allowed: bool
    reason: str
    strategy: dict[str, Any] = field(default_factory=dict)


# ── 归一化工具 ──────────────────────────────────────────────


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return None if number is None else int(number)


def _bounded_int(value: Any, low: int, high: int, default: int = 0) -> int:
    number = _as_int(value)
    if number is None:
        return default
    return max(low, min(high, number))


def _bounded_float(value: Any, low: float, high: float, default: float) -> float:
    number = _as_float(value)
    if number is None:
        return default
    return max(low, min(high, number))


def _tier_optional_int(value: Any, high: int, fallback: int) -> int:
    """档位整数字段：缺省用档位默认值，显式填 0 表示"这一项不限制"。

    两个语义必须分开：档位默认值是"没配过"时的具体数值，0 是用户主动表达的不限制。
    以前两者都是 0，界面上只能显示 0，分不清是哪一个。
    """

    return fallback if value is None or value == "" else int(_optional_int(value, 0, high) or 0)


def _tier_optional_float(value: Any, high: float, fallback: float) -> float:
    number = _as_float(value)
    if number is None:
        return float(fallback)
    return max(0.0, min(high, number))


def _clock(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) != 2:
        return ""
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return ""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hour:02d}:{minute:02d}"


def _optional_number(value: Any, low: float, high: float) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    return max(low, min(high, number))


def _optional_int(value: Any, low: int, high: int) -> int | None:
    number = _as_int(value)
    if number is None:
        return None
    return max(low, min(high, number))


# ── 策略读写 ────────────────────────────────────────────────


def default_reply_strategy() -> dict[str, Any]:
    return {
        "version": 1,
        "enabled": False,
        # 主动互动曾经自己维护一张好感档位表（proactive_policy.json::tiers）。这份
        # 档位表合并进来之后，只要 WebUI 保存过一次就置位，之后读档不再把旧表里的
        # 间隔/每日上限盖回新表，避免"改了档位又被历史配置悄悄改回去"。
        "proactive_tiers_migrated": False,
        "defaults": dict(DEFAULT_DEFAULTS),
        "affection_tiers": [dict(tier) for tier in DEFAULT_TIERS],
        "activity_tiers": [dict(tier) for tier in DEFAULT_ACTIVITY_TIERS],
        "users": {},
        "groups": {},
    }


def proactive_tier_overrides(payload: Any) -> dict[str, dict[str, Any]]:
    """从旧的 ``proactive_policy.json::tiers`` 里取出需要迁移的频率字段。

    只认 ``min_hours`` / ``max_hours`` / ``daily_limit``：档位名、好感范围、启用状态
    一律以 ``affection_tiers`` 为准，否则两张表又会各说各话。
    """

    if not isinstance(payload, list):
        return {}
    overrides: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        tier_id = str(item.get("id") or "").strip()
        if not tier_id:
            continue
        entry: dict[str, Any] = {}
        for key in ("min_hours", "max_hours", "daily_limit"):
            if item.get(key) is not None:
                entry[key] = item[key]
        if entry:
            overrides[tier_id] = entry
    return overrides


def tier_by_id(tiers: Any, tier_id: str) -> dict[str, Any] | None:
    for tier in tiers or []:
        if isinstance(tier, dict) and str(tier.get("id") or "") == str(tier_id):
            return tier
    return None


AFFECTION_TIER_FIELDS: tuple[str, ...] = (
    "name",
    "enabled",
    "min_affection",
    "max_affection",
    "per_hour",
    "per_day",
    "cooldown_seconds",
    "target_chars",
    "max_parts",
    "min_hours",
    "max_hours",
    "daily_limit",
)

ACTIVITY_TIER_FIELDS: tuple[str, ...] = (
    "name",
    "enabled",
    "min_activity",
    "max_activity",
    "per_hour",
    "per_day",
    "cooldown_seconds",
    "continuation_max",
    "target_chars",
    "min_hours",
    "max_hours",
    "daily_limit",
)


# 这些档位字段在语义上不可能是 0：主动消息的"随机间隔"若是 0 小时，等于立刻又发
# 一条。界面上曾经出现过"数值渲染成空白 → 保存时被当成 0"的事故，把用户手配的间隔
# 一次性清零，所以合并时把 0 当作"没拿到值"处理，保留已存的数值。
# ``daily_limit`` 不在其中：0 是合法值，表示这一档不主动发消息。
_NON_ZERO_TIER_FIELDS = frozenset({"min_hours", "max_hours"})


def merge_tier_table(
    incoming: Any,
    *,
    table: str,
    fields: tuple[str, ...],
    migrate_marker: str | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """把一张（可能是局部的）档位表合并进指定档位表并落盘。

    WebUI 的档位表同时承载回复侧和主动互动侧的列，两个页面各自保存时都提交整张表；
    先读后改再写，避免后保存的一方把对方刚写进去的列冲掉（多标签页同时打开时尤其
    明显）。只覆盖 ``fields`` 里列出的键，且跳过空值——所以"没提交"不会把值清零。

    返回值是合并后的档位表，供调用方直接回给前端。
    """

    if not isinstance(incoming, list) or not incoming:
        return None
    policy = load_reply_strategy(path, force=True)
    tiers = [dict(tier) for tier in policy.get(table) or []]
    if not tiers:
        return None

    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        tier_id = str(raw.get("id") or "").strip()
        if not tier_id:
            continue
        current = tier_by_id(tiers, tier_id)
        if current is None:
            continue
        for key in fields:
            value = raw.get(key)
            if value is None or value == "":
                continue
            # 防误删：主动消息的"随机间隔"不可能真的是 0 小时（那等于立刻又发一条）。
            # 界面上曾经出现过"数值渲染成空白 → 保存时被当成 0"的事故，把用户手配的
            # 间隔一次性清零。这里把 0 视为"没拿到值"，保留已存的数值。
            # 注意 daily_limit 不在此列：0 是合法值（表示这一档不主动发消息）。
            if key in _NON_ZERO_TIER_FIELDS and _as_float(value) == 0:
                continue
            current[key] = value

    policy[table] = tiers
    if migrate_marker:
        # 整张表（含主动互动侧）已经在正文里，旧档位表可以退场。
        policy[migrate_marker] = True
    saved = save_reply_strategy(policy, path)
    return saved[table]


def normalize_reply_strategy(payload: Any) -> dict[str, Any]:
    """把任意输入整理成完整策略；非法值一律退回默认，绝不让坏值进入运行配置。"""

    result = default_reply_strategy()
    if not isinstance(payload, dict):
        return result
    result["enabled"] = _as_bool(payload.get("enabled", False))
    result["proactive_tiers_migrated"] = _as_bool(
        payload.get("proactive_tiers_migrated", False)
    )

    raw_defaults = payload.get("defaults")
    if isinstance(raw_defaults, dict):
        defaults = result["defaults"]
        defaults["unlisted_mode"] = _mode(
            raw_defaults.get("unlisted_mode", DEFAULT_DEFAULTS["unlisted_mode"])
        )
        # 这里不再有"受众门槛"字段：能不能回完全由分档表的好感范围决定。
        # 旧配置里残留的同名字段会被直接忽略（normalize 只挑已知键），
        # 所以不需要迁移，也不会再悄悄拦人。
        defaults["group_require_mention"] = _as_bool(
            raw_defaults.get("group_require_mention", False)
        )
        # 群内"每人每小时"上限已删除：频率由分档表决定。旧配置里残留的同名字段
        # 会被忽略（normalize 只挑已知键），下一次保存就从文件里消失。
        for key in ("target_reply_chars", "min_reply_chars", "max_reply_parts"):
            defaults[key] = _bounded_int(raw_defaults.get(key), 0, 2000, 0)
        defaults["active_hours_start"] = _clock(raw_defaults.get("active_hours_start"))
        defaults["active_hours_end"] = _clock(raw_defaults.get("active_hours_end"))

    raw_tiers = payload.get("affection_tiers")
    if isinstance(raw_tiers, list) and raw_tiers:
        tiers: list[dict[str, Any]] = []
        for index, raw_tier in enumerate(raw_tiers[:10]):
            if not isinstance(raw_tier, dict):
                continue
            # 回落默认值按 id 匹配，其次按位置。只按位置的话，提交一个局部档位表
            # （例如只改「熟悉」一档）会拿到「普通」的默认值，把没提交的字段写错。
            fallback = next(
                (
                    tier
                    for tier in DEFAULT_TIERS
                    if tier["id"] == str(raw_tier.get("id") or "").strip()
                ),
                DEFAULT_TIERS[min(index, len(DEFAULT_TIERS) - 1)],
            )
            low = _bounded_float(
                raw_tier.get("min_affection"), 0.0, 100.0, fallback["min_affection"]
            )
            high = _bounded_float(
                raw_tier.get("max_affection"), low, 101.0, fallback["max_affection"]
            )
            min_hours = _bounded_float(
                raw_tier.get("min_hours"), 0.25, 168.0, fallback["min_hours"]
            )
            tiers.append(
                {
                    "id": str(raw_tier.get("id") or fallback["id"])[:32],
                    "name": str(raw_tier.get("name") or fallback["name"])[:32],
                    "min_affection": low,
                    "max_affection": max(low, high),
                    "enabled": _as_bool(raw_tier.get("enabled", fallback["enabled"])),
                    # 缺省用档位默认值（具体数字），显式填 0 才是"这一项不限制"。
                    "per_hour": _tier_optional_int(
                        raw_tier.get("per_hour"), 5000, fallback["per_hour"]
                    ),
                    "per_day": _tier_optional_int(
                        raw_tier.get("per_day"), 5000, fallback["per_day"]
                    ),
                    "cooldown_seconds": _tier_optional_float(
                        raw_tier.get("cooldown_seconds"), 3600.0, fallback["cooldown_seconds"]
                    ),
                    "target_chars": _tier_optional_int(
                        raw_tier.get("target_chars"), 2000, fallback["target_chars"]
                    ),
                    "max_parts": _tier_optional_int(
                        raw_tier.get("max_parts"), 20, fallback["max_parts"]
                    ),
                    # 主动互动侧的频率：同一档位里一起配，省得两张表各填一次好感范围。
                    "min_hours": min_hours,
                    "max_hours": _bounded_float(
                        raw_tier.get("max_hours"), min_hours, 336.0, fallback["max_hours"]
                    ),
                    # daily_limit 的 0 是"这一档不主动发消息"，是真实数值而非"不限制"，
                    # 所以继续用 _bounded_int。
                    "daily_limit": _bounded_int(
                        raw_tier.get("daily_limit"), 0, 12, fallback["daily_limit"]
                    ),
                }
            )
        if tiers:
            result["affection_tiers"] = tiers

    raw_activity_tiers = payload.get("activity_tiers")
    if isinstance(raw_activity_tiers, list) and raw_activity_tiers:
        activity_tiers: list[dict[str, Any]] = []
        for index, raw_tier in enumerate(raw_activity_tiers[:10]):
            if not isinstance(raw_tier, dict):
                continue
            # 回落默认值同样优先按 id 匹配，避免局部提交时张冠李戴。
            fallback = next(
                (
                    tier
                    for tier in DEFAULT_ACTIVITY_TIERS
                    if tier["id"] == str(raw_tier.get("id") or "").strip()
                ),
                DEFAULT_ACTIVITY_TIERS[min(index, len(DEFAULT_ACTIVITY_TIERS) - 1)],
            )
            low = _bounded_float(
                raw_tier.get("min_activity"), 0.0, 100.0, fallback["min_activity"]
            )
            high = _bounded_float(
                raw_tier.get("max_activity"), low, 101.0, fallback["max_activity"]
            )
            min_hours = _bounded_float(
                raw_tier.get("min_hours"), 0.25, 168.0, fallback["min_hours"]
            )
            activity_tiers.append(
                {
                    "id": str(raw_tier.get("id") or fallback["id"])[:32],
                    "name": str(raw_tier.get("name") or fallback["name"])[:32],
                    "min_activity": low,
                    "max_activity": max(low, high),
                    "enabled": _as_bool(raw_tier.get("enabled", fallback["enabled"])),
                    "per_hour": _bounded_int(raw_tier.get("per_hour"), 0, 5000, 0),
                    "per_day": _bounded_int(raw_tier.get("per_day"), 0, 5000, 0),
                    "cooldown_seconds": _bounded_float(
                        raw_tier.get("cooldown_seconds"), 0.0, 3600.0, 0.0
                    ),
                    "continuation_max": _bounded_int(
                        raw_tier.get("continuation_max"), 0, 50, 0
                    ),
                    "target_chars": _bounded_int(raw_tier.get("target_chars"), 0, 2000, 0),
                    # 主动发起：与用户分档同构。缺省用档位默认值，0 表示不在群里主动说话。
                    "min_hours": min_hours,
                    "max_hours": _bounded_float(
                        raw_tier.get("max_hours"), min_hours, 336.0, fallback["max_hours"]
                    ),
                    "daily_limit": _bounded_int(
                        raw_tier.get("daily_limit"), 0, 12, fallback["daily_limit"]
                    ),
                }
            )
        if activity_tiers:
            result["activity_tiers"] = activity_tiers

    raw_users = payload.get("users")
    if isinstance(raw_users, list):  # 兼容早期可能提交的列表结构
        raw_users = {
            str(item.get("id") or item.get("user_id")): item
            for item in raw_users
            if isinstance(item, dict)
        }
    if isinstance(raw_users, dict):
        for raw_id, raw_user in list(raw_users.items())[:MAX_OBJECTS]:
            user_id = str(raw_id or "").strip()
            if not user_id.isdigit() or not isinstance(raw_user, dict):
                continue
            result["users"][user_id] = {
                "name": str(raw_user.get("name") or "").strip()[:120],
                "mode": _mode(raw_user.get("mode")),
                "min_affection": _optional_number(
                    raw_user.get("min_affection"), 0.0, 100.0
                ),
                "per_hour": _optional_int(raw_user.get("per_hour"), 0, 5000),
                "per_day": _optional_int(raw_user.get("per_day"), 0, 5000),
                "target_chars": _optional_int(raw_user.get("target_chars"), 0, 2000),
            }

    raw_groups = payload.get("groups")
    if isinstance(raw_groups, list):
        raw_groups = {
            str(item.get("id") or item.get("group_id")): item
            for item in raw_groups
            if isinstance(item, dict)
        }
    if isinstance(raw_groups, dict):
        for raw_id, raw_group in list(raw_groups.items())[:MAX_OBJECTS]:
            group_id = str(raw_id or "").strip()
            if not group_id.isdigit() or not isinstance(raw_group, dict):
                continue
            group_rule_value: dict[str, Any] = {
                "name": str(raw_group.get("name") or "").strip()[:120],
                "mode": _group_mode(raw_group.get("mode")),
                # None 表示"跟随 REPLY_MODE"，只有显式 true/false 才覆盖群聊的 @ 要求。
                "require_mention": (
                    _as_bool(raw_group.get("require_mention"))
                    if raw_group.get("require_mention") is not None
                    else None
                ),
                "min_activity": _optional_number(
                    raw_group.get("min_activity"), 0.0, 100.0
                ),
                "per_hour": _optional_int(raw_group.get("per_hour"), 0, 5000),
                "per_day": _optional_int(raw_group.get("per_day"), 0, 5000),
                "target_chars": _optional_int(raw_group.get("target_chars"), 0, 2000),
            }
            result["groups"][group_id] = group_rule_value
    return result


def _mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODES else "auto"


def _group_mode(value: Any) -> str:
    """群聊模式归一：只认 smart / mention / silence。

    历史值按等价语义折算——allow/auto 就是"不额外收紧"（→ smart），
    quiet/deny 都是"不回"（→ silence）。这样旧配置不需要手工迁移，
    界面上那个三选一的下拉也总能对上。
    """

    text = str(value or "").strip().lower()
    if text in GROUP_MODES:
        return text
    return GROUP_MODE_ALIASES.get(text, "smart")


def _strategy_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def load_reply_strategy(
    path: Path | None = None, *, force: bool = False
) -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME_NS

    target = path or REPLY_STRATEGY_PATH
    mtime_ns = _strategy_mtime_ns(target)
    with _LOCK:
        if not force and _CACHE is not None and mtime_ns == _CACHE_MTIME_NS:
            return json.loads(json.dumps(_CACHE, ensure_ascii=False))
        try:
            payload = (
                json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
            )
        except (OSError, TypeError, ValueError):
            payload = {}
        _CACHE = normalize_reply_strategy(payload)
        _CACHE_MTIME_NS = mtime_ns
        return json.loads(json.dumps(_CACHE, ensure_ascii=False))


def save_reply_strategy(payload: Any, path: Path | None = None) -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME_NS

    target = path or REPLY_STRATEGY_PATH
    normalized = normalize_reply_strategy(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with _LOCK:
        # 先备份上一份：档位数值是用户手工配的，写坏了很难凭记忆还原。
        # 和 proactive_policy 一样保留一个 .bak，出问题至少能回滚。
        if target.exists():
            try:
                target.with_suffix(".bak").write_bytes(target.read_bytes())
            except OSError:
                pass
        temporary.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        _CACHE = normalized
        _CACHE_MTIME_NS = _strategy_mtime_ns(target)
    return json.loads(json.dumps(normalized, ensure_ascii=False))


# ── 频率计数 ────────────────────────────────────────────────


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "objects": {}}


def load_reply_state(path: Path | None = None) -> dict[str, Any]:
    global _STATE_CACHE

    target = path or REPLY_STRATEGY_STATE_PATH
    with _LOCK:
        if _STATE_CACHE is not None and path is None:
            return json.loads(json.dumps(_STATE_CACHE, ensure_ascii=False))
        try:
            payload = (
                json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
            )
        except (OSError, TypeError, ValueError):
            payload = {}
        state = _empty_state()
        if isinstance(payload, dict) and isinstance(payload.get("objects"), dict):
            state["objects"] = payload["objects"]
        if path is None:
            _STATE_CACHE = state
        return json.loads(json.dumps(state, ensure_ascii=False))


def _persist_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or REPLY_STRATEGY_STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(target)


def _hour_key(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H", time.localtime(now))


def _day_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def _counter_key(scope: str, user_id: str, group_id: str) -> str:
    if scope == "group" and group_id:
        return f"group:{group_id}"
    return f"private:{user_id}"


def _object_bucket(state: dict[str, Any], key: str, now: float) -> dict[str, Any]:
    objects = state.setdefault("objects", {})
    bucket = objects.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        objects[key] = bucket
    hour_key, day_key = _hour_key(now), _day_key(now)
    if bucket.get("hour_key") != hour_key:
        bucket["hour_key"] = hour_key
        bucket["hour_count"] = 0
    if bucket.get("day_key") != day_key:
        bucket["day_key"] = day_key
        bucket["day_count"] = 0
    bucket.setdefault("hour_count", 0)
    bucket.setdefault("day_count", 0)
    recent = bucket.get("recent")
    if not isinstance(recent, list):
        recent = []
    bucket["recent"] = [float(item) for item in recent if _as_float(item) is not None][
        -MAX_RECENT_REPLIES:
    ]
    return bucket


def _within_active_hours(defaults: dict[str, Any], now: float) -> bool:
    start = _clock(defaults.get("active_hours_start"))
    end = _clock(defaults.get("active_hours_end"))
    if not start or not end:
        return True
    local = time.localtime(now)
    minutes = local.tm_hour * 60 + local.tm_min
    start_minutes = int(start[:2]) * 60 + int(start[3:])
    end_minutes = int(end[:2]) * 60 + int(end[3:])
    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= minutes < end_minutes
    # 跨零点，例如 09:00 → 01:00
    return minutes >= start_minutes or minutes < end_minutes


def _tier_for_affection(
    tiers: list[dict[str, Any]], affection: float
) -> dict[str, Any] | None:
    for tier in tiers:
        if float(tier["min_affection"]) <= affection < float(tier["max_affection"]):
            return tier
    return None


def _tier_for_activity(
    tiers: list[dict[str, Any]], activity: float
) -> dict[str, Any] | None:
    for tier in tiers:
        if float(tier["min_activity"]) <= activity < float(tier["max_activity"]):
            return tier
    return None


def _object_rule(
    policy: dict[str, Any], scope: str, user_id: str, group_id: str
) -> dict[str, Any] | None:
    if scope == "group":
        return (policy.get("groups") or {}).get(str(group_id)) if group_id else None
    return (policy.get("users") or {}).get(str(user_id)) if user_id else None


def object_mode(
    *,
    scope: str,
    user_id: str = "",
    group_id: str = "",
    policy: dict[str, Any] | None = None,
) -> str:
    """读取对象当前生效的模式（未列入名单的对象回落到 defaults.unlisted_mode）。"""

    policy = policy if policy is not None else load_reply_strategy()
    rule = _object_rule(policy, scope, user_id, group_id)
    if rule:
        return (
            _group_mode(rule.get("mode"))
            if scope == "group"
            else _mode(rule.get("mode"))
        )
    defaults = dict(policy.get("defaults") or DEFAULT_DEFAULTS)
    unlisted = defaults.get("unlisted_mode", "auto")
    return _group_mode(unlisted) if scope == "group" else _mode(unlisted)


def object_requires_mention(
    *,
    scope: str,
    user_id: str = "",
    group_id: str = "",
    policy: dict[str, Any] | None = None,
) -> bool:
    """群聊对象是否"每一轮都要 @"——也就是它的模式是不是 mention。

    模式是唯一判据：``smart`` 明确允许被触发词叫起来（所以不能要求 @），
    ``silence`` 本来就不回。规则里遗留的 ``require_mention`` 字段与全局
    ``group_require_mention`` 都不再参与判定（界面上已经没有它们的控件）。

    给 OneBot 层判定"要不要为这个对象打开续聊会话"用。@ 只存在于群聊，私聊恒为 False。
    """

    if scope != "group":
        return False
    policy = policy if policy is not None else load_reply_strategy()
    if not policy.get("enabled"):
        return False
    return object_mode(
        scope=scope, user_id=user_id, group_id=group_id, policy=policy
    ) == "mention"


def forced_event_block_reason(
    *,
    scope: str,
    user_id: str = "",
    group_id: str = "",
    is_owner: bool = False,
    policy: dict[str, Any] | None = None,
) -> str:
    """对象级模式是否硬拦「强制回复」事件（入群欢迎等）；返回空串表示放行。

    入群通知既没有 @ 也不是续聊，历史上靠 ``push_event`` 直接跳过整个回复策略，
    于是「只记录」和「仅 @ 回复」都拦不住它——群友会看到"设了禁言它还在欢迎新人"。

    这里把对象级模式抽成一条**独立**的硬门控：模式表达的是"这个对象该不该被主动
    搭话"，优先级高于任何强制回复旁路。刻意**不**参与频率、冷却和分档判定，否则
    同一批人陆续进群时，欢迎会被刚回过话的冷却误杀（"入群必回"的语义要保留）。
    """

    if is_owner:
        return ""
    policy = policy if policy is not None else load_reply_strategy()
    if not policy.get("enabled"):
        return ""
    mode = object_mode(scope=scope, user_id=user_id, group_id=group_id, policy=policy)
    if mode == "deny":
        return "对象策略强制禁止回复"
    if mode in {"silence", "quiet"}:
        return "对象策略静默（仅记录不回复）"
    if mode == "mention" and scope == "group":
        # 入群通知本身不是一次 @，所以 mention 模式的群里不发欢迎。
        return "该群要求被 @ 才回复"
    return ""


def evaluate_reply(
    *,
    scope: str,
    user_id: str = "",
    group_id: str = "",
    affection: float | None = None,
    activity: float | None = None,
    active_days: float | None = None,
    message_count: int | None = None,
    is_mention: bool = False,
    is_owner: bool = False,
    is_continuation: bool = False,
    now: float | None = None,
    policy: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> ReplyDecision:
    """判断这一条消息是否允许回复，并给出生效的长度策略（软引导）。

    判定顺序：对象例外（deny/quiet/silence/mention）→ 活跃时段 → 群 @ 要求
    → 分档（命中已停用的档位就拒绝）→ 通过。

    频率（每小时/每日上限、冷却、连聊上限）已经移除——历史经验是它和"该不该回"
    叠在一起后，用户只会看到"聊到一半突然不回"，却找不到是哪一层拦的。现在策略
    只决定"回不回"，长度（目标字数/最多分条）只作为软引导交给模型，由系统提示词
    决定质量与详略。

    "好感度不够就别回"这类门槛不需要单独的判断：把关掉低档、或把最低档的
    ``min_affection`` 调高即可，分档表本身就是门槛。
    """

    now = float(now if now is not None else time.time())
    policy = policy if policy is not None else load_reply_strategy()
    if not policy.get("enabled"):
        return ReplyDecision(True, "策略未启用", {})
    defaults = dict(policy.get("defaults") or DEFAULT_DEFAULTS)
    tiers = list(policy.get("affection_tiers") or DEFAULT_TIERS)
    activity_tiers = list(policy.get("activity_tiers") or DEFAULT_ACTIVITY_TIERS)

    if not _within_active_hours(defaults, now):
        return ReplyDecision(False, "不在活跃时段", {})

    group_rule = (
        (policy.get("groups") or {}).get(str(group_id))
        if scope == "group" and group_id
        else None
    )
    user_rule = (policy.get("users") or {}).get(str(user_id)) if user_id else None
    if scope == "group":
        rule, mode = group_rule, _group_mode((group_rule or {}).get("mode"))
    else:
        rule, mode = user_rule, _mode((user_rule or {}).get("mode"))
    rule = rule or {}
    if not rule:
        # 没有独立规则的对象走 defaults.unlisted_mode。群聊侧归一成 smart/mention/silence，
        # 私聊侧仍是 auto/allow/deny/quiet。
        unlisted = defaults.get("unlisted_mode", "auto")
        mode = _group_mode(unlisted) if scope == "group" else _mode(unlisted)

    if scope != "group" and mode == "mention":
        # @ 只存在于群聊：mention 落在用户对象上等价于跟随分档（历史兼容）。
        mode = "auto"

    if is_owner:
        # 主人永远可以聊；但仍遵守频率与长度策略，避免自己把号刷爆。
        mode = "allow"
    elif mode == "deny":
        return ReplyDecision(False, "对象策略强制禁止回复", {})
    elif mode in {"silence", "quiet"}:
        return ReplyDecision(False, "对象策略静默（仅记录不回复）", {})

    strategy: dict[str, Any] = {}

    if scope == "group" and mode == "mention" and not is_mention:
        # 只有 mention 模式会在这里拦人。smart 明确允许"被触发词叫起来"，
        # 所以它不能要求 @；也**不再**读历史字段 require_mention / group_require_mention
        # ——界面上早已没有这两个控件，模式下拉才是唯一可见、可改的开关。
        # 续聊也不放行：续聊窗口会滑动续期，@ 一次之后该成员的后续消息都会被持续
        # 当成续聊放行，表现就是"设了仅 @ 还自己冒泡"。mention 的语义是每轮都要 @。
        return ReplyDecision(False, "该群要求被 @ 才回复", {})

    # 分档：私聊按好感度、群聊按活跃度。优先级 对象覆盖 > 档位 > 全局默认。
    if scope == "group":
        tier = (
            _tier_for_activity(activity_tiers, activity) if activity is not None else None
        )
    else:
        tier = _tier_for_affection(tiers, affection) if affection is not None else None
    # 档位停用 = 命中这个区间就不回复。它只在"自动按档位"的对象上生效：
    # 对象的模式一旦是显式覆盖（mention / silence / deny / allow），档位的启用开关
    # 就不再是判据。群聊侧的 smart 也属于"自动按档位"，只是额外不要求 @，所以
    # 它必须包含在内——否则把某个活跃度档位取消勾选就再也不生效了。
    if tier is not None and mode in {"auto", "smart"} and not tier.get("enabled", True):
        return ReplyDecision(False, f"「{tier.get('name')}」档位已停用", {})
    tier = tier or {}

    rule_hour = (
        _optional_int(rule.get("per_hour"), 0, 5000)
        if rule.get("per_hour") is not None
        else None
    )
    rule_day = (
        _optional_int(rule.get("per_day"), 0, 5000)
        if rule.get("per_day") is not None
        else None
    )
    # 频率（每小时/每日上限、冷却、连聊上限）已从回复策略里移除：回退到"只决定
    # 这个对象该不该回（模式 / @ 要求 / 档位是否启用），不再决定多久能回一次"。
    # 长度与分条只作为软引导交给模型，不在这里做任何硬拦截。

    target_chars = 0
    rule_chars = _optional_int(rule.get("target_chars"), 0, 2000)
    if rule_chars:
        target_chars = rule_chars
    if not target_chars:
        target_chars = int(tier.get("target_chars") or 0)
    if not target_chars:
        target_chars = int(defaults.get("target_reply_chars") or 0)
    max_parts = int(tier.get("max_parts") or 0) or int(
        defaults.get("max_reply_parts") or 0
    )

    strategy.update(
        {
            "target_reply_chars": target_chars,
            "min_reply_chars": int(defaults.get("min_reply_chars") or 0),
            "max_reply_parts": max_parts,
            "tier_id": str(tier.get("id") or ""),
            "tier_name": str(tier.get("name") or ""),
            "mode": mode,
        }
    )
    return ReplyDecision(True, "允许", strategy)


def preview_limits(
    *,
    kind: str,
    value: float,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """给 WebUI 的"按好感/活跃度预览"用：返回命中的档位与生效上限。"""

    policy = policy if policy is not None else load_reply_strategy()
    defaults = dict(policy.get("defaults") or DEFAULT_DEFAULTS)
    score = max(0.0, min(100.0, float(value)))
    is_group = str(kind or "").strip().lower() == "group"
    if is_group:
        tiers = list(policy.get("activity_tiers") or DEFAULT_ACTIVITY_TIERS)
        tier = _tier_for_activity(tiers, score)
        limits = {
            "per_hour": int((tier or {}).get("per_hour") or 0),
            "per_day": int((tier or {}).get("per_day") or 0),
            "cooldown_seconds": float((tier or {}).get("cooldown_seconds") or 0.0),
            "continuation_max": int((tier or {}).get("continuation_max") or 0),
            "target_chars": int((tier or {}).get("target_chars") or 0),
            "max_parts": int(defaults.get("max_reply_parts") or 0),
        }
    else:
        tiers = list(policy.get("affection_tiers") or DEFAULT_TIERS)
        tier = _tier_for_affection(tiers, score)
        limits = {
            "per_hour": int((tier or {}).get("per_hour") or 0),
            "per_day": int((tier or {}).get("per_day") or 0),
            "cooldown_seconds": float((tier or {}).get("cooldown_seconds") or 0.0),
            "target_chars": int((tier or {}).get("target_chars") or 0),
            "max_parts": int((tier or {}).get("max_parts") or 0),
        }
    tier_enabled = bool((tier or {}).get("enabled", False))
    if tier is None:
        note = "没有匹配的档位，按全局默认执行"
    elif not tier_enabled:
        note = "该档位已停用：命中时不会回复"
    else:
        note = "命中该档位时按下列上限回复"
    return {
        "kind": "group" if is_group else "user",
        "value": score,
        "tier": dict(tier or {}),
        "enabled": tier_enabled,
        "limits": limits,
        "note": note,
    }


def record_reply(
    *,
    scope: str,
    user_id: str = "",
    group_id: str = "",
    now: float | None = None,
    state_path: Path | None = None,
) -> None:
    """记录一次真实回复，用于每小时/每日上限与群冷却。"""

    now = float(now if now is not None else time.time())
    with _LOCK:
        state = load_reply_state(state_path)
        key = _counter_key(scope, str(user_id), str(group_id))
        bucket = _object_bucket(state, key, now)
        bucket["hour_count"] = int(bucket.get("hour_count") or 0) + 1
        bucket["day_count"] = int(bucket.get("day_count") or 0) + 1
        bucket["last_reply_at"] = now
        recent = list(bucket.get("recent") or [])
        recent.append(now)
        bucket["recent"] = recent[-MAX_RECENT_REPLIES:]
        _persist_state(state, state_path)
        if state_path is None:
            global _STATE_CACHE
            _STATE_CACHE = state


def update_object_rule(
    kind: str,
    identifier: str,
    rule: Any,
    *,
    name: str = "",
    remove: bool = False,
    path: Path | None = None,
) -> dict[str, Any]:
    """只更新一个对象的规则。

    用户中心是按卡片逐个保存的，这里做"读改写"避免前端拿整份 policy 往返覆盖；
    ``remove=True`` 表示把该对象从名单里摘掉（回到"未列入名单的对象"默认模式）。
    """

    normalized_kind = "group" if str(kind or "").strip().lower() == "group" else "user"
    normalized_id = str(identifier or "").strip()
    if not normalized_id.isdigit():
        raise ValueError("对象编号必须是纯数字 QQ 号或群号")
    policy = load_reply_strategy(path, force=True)
    bucket = policy["groups"] if normalized_kind == "group" else policy["users"]
    if remove:
        bucket.pop(normalized_id, None)
    else:
        merged: dict[str, Any] = dict(bucket.get(normalized_id) or {})
        if isinstance(rule, dict):
            merged.update(rule)
        # 用户规则不带群字段，群规则不带好感门槛，避免张冠李戴。
        if normalized_kind == "group":
            merged.pop("min_affection", None)
        else:
            merged.pop("min_activity", None)
            merged.pop("require_mention", None)
        if str(name or "").strip():
            merged["name"] = str(name).strip()[:120]
        bucket[normalized_id] = merged
    saved = save_reply_strategy(policy, path)
    rules = saved["groups"] if normalized_kind == "group" else saved["users"]
    return {
        "policy": saved,
        "kind": normalized_kind,
        "id": normalized_id,
        "rule": rules.get(normalized_id),
    }


def reset_reply_counters(state_path: Path | None = None) -> None:
    global _STATE_CACHE

    with _LOCK:
        empty = _empty_state()
        _persist_state(empty, state_path)
        if state_path is None:
            _STATE_CACHE = empty


def counter_snapshot(state_path: Path | None = None) -> dict[str, Any]:
    """给 WebUI 展示用的计数快照（不含任何消息内容）。"""

    state = load_reply_state(state_path)
    objects = state.get("objects") or {}
    snapshot: dict[str, Any] = {}
    now = time.time()
    hour_key, day_key = _hour_key(now), _day_key(now)
    for key, bucket in list(objects.items())[:MAX_OBJECTS]:
        if not isinstance(bucket, dict):
            continue
        snapshot[key] = {
            "hour_count": int(bucket.get("hour_count") or 0)
            if bucket.get("hour_key") == hour_key
            else 0,
            "day_count": int(bucket.get("day_count") or 0)
            if bucket.get("day_key") == day_key
            else 0,
            "last_reply_at": _as_float(bucket.get("last_reply_at")),
        }
    return snapshot
