from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..runtime.paths import PROACTIVE_POLICY_PATH
from ..runtime.reply_strategy import (
    AFFECTION_TIER_FIELDS,
    ACTIVITY_TIER_FIELDS,
    load_reply_strategy,
    merge_tier_table,
    proactive_tier_overrides,
)
from .time_utils import parse_hhmm, safe_zoneinfo


DEFAULT_PROACTIVE_POLICY: dict[str, Any] = {
    "version": 2,
    "enabled": True,
    "owner_only": False,
    "use_ai": True,
    "guided_topics": True,
    "private_min_affection": 70,
    "private_active_days": 14,
    "private_min_messages": 5,
    "group_enabled": True,
    "group_min_activity": 55,
    "group_active_days": 3,
    "group_min_messages": 12,
    "group_min_hours": 3,
    "group_max_hours": 9,
    "group_daily_limit": 2,
    "timezone": "Asia/Shanghai",
    "quiet_start": "00:30",
    "quiet_end": "07:00",
    "check_seconds": 60,
    "history_limit": 8,
    "max_chars": 90,
    "ignored_backoff": 1.5,
    "content_weights": {
        "morning": 8,
        "goodnight": 7,
        "check_in": 18,
        "continue_topic": 18,
        "interest_topic": 14,
        "guided_topic": 20,
        "daily_share": 14,
        "affection": 12,
        "encouragement": 9,
    },
    "group_content_weights": {
        "check_in": 8,
        "continue_topic": 24,
        "interest_topic": 16,
        "guided_topic": 30,
        "daily_share": 14,
        "encouragement": 8,
    },
}


def default_proactive_policy() -> dict[str, Any]:
    policy = deepcopy(DEFAULT_PROACTIVE_POLICY)
    # 两张档位表都不在这里定义：它们住在 reply_strategy.json 的 affection_tiers /
    # activity_tiers 里，由 load_proactive_policy() 注入，见下面的 tier 合并说明。
    policy["tiers"] = []
    policy["activity_tiers"] = []
    return policy


def _effective_activity_tiers(policy: dict[str, Any]) -> list[dict[str, Any]]:
    """群聊活跃度档位：同样以回复策略里的 ``activity_tiers`` 为唯一来源。

    群聊的主动消息按群活跃度命中同一档，用这一档的随机间隔与每日上限，所以这份
    档位必须能被 planner 看到。
    """

    return [
        dict(tier) for tier in load_reply_strategy().get("activity_tiers") or []
    ]


def _effective_tiers(policy: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
    """给主动互动用的档位视图：以回复策略的档位表为唯一来源。

    旧版本 ``proactive_policy.json`` 里自带一张好感档位表，好感范围与回复策略里的
    完全重复。为了让升级后的用户不至于丢掉当时配好的随机间隔／每日上限，这里做一次
    只读合并：
    * 档位名、好感范围、启用状态一律取 ``affection_tiers``（唯一来源）；
    * 仅在 ``proactive_tiers_migrated`` 还没置位时，把旧表里的
      ``min_hours`` / ``max_hours`` / ``daily_limit`` 盖上去；
    * WebUI 保存过任意一次配置后标记置位，之后完全以 ``affection_tiers`` 为准。
    """

    tiers = [
        dict(tier) for tier in load_reply_strategy().get("affection_tiers") or []
    ]
    if not tiers:
        return []
    if _as_bool(policy.get("proactive_tiers_migrated", False)):
        return tiers
    if not isinstance(payload, dict):
        return tiers
    overrides = proactive_tier_overrides(payload.get("tiers"))
    if not overrides:
        return tiers
    for tier in tiers:
        merged = overrides.get(str(tier.get("id") or ""))
        if merged:
            tier.update(merged)
    return tiers


def load_proactive_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or PROACTIVE_POLICY_PATH
    if not target.exists():
        return default_proactive_policy()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_proactive_policy()
    policy = normalize_proactive_policy(payload)
    # 旧档位表只作为一次性迁移来源参与计算，结果不落盘：唯一来源是
    # reply_strategy.json，保存时由 WebUI 把合并后的整张表写回去。
    policy["tiers"] = _effective_tiers(policy, payload)
    policy["activity_tiers"] = _effective_activity_tiers(policy)
    return policy


def persist_tiers_from_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """把主动互动页面提交的档位表写回唯一来源 ``reply_strategy.json``。

    两张表分别承载两套分档：``tiers`` 是私聊好感档位（用户分档页签），
    ``activity_tiers`` 是群聊活跃度档位（群聊分档页签）。两边的保存入口都会提交
    同一份快照，所以这里两张都合并，返回值供接口直接回给前端。
    """

    if not isinstance(payload, dict):
        return {}
    merged: dict[str, list[dict[str, Any]]] = {}
    affection = merge_tier_table(
        payload.get("tiers"),
        table="affection_tiers",
        fields=AFFECTION_TIER_FIELDS,
        migrate_marker="proactive_tiers_migrated",
    )
    if affection is not None:
        merged["tiers"] = affection
    activity = merge_tier_table(
        payload.get("activity_tiers"),
        table="activity_tiers",
        fields=ACTIVITY_TIER_FIELDS,
    )
    if activity is not None:
        merged["activity_tiers"] = activity
    return merged


def save_proactive_policy(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = path or PROACTIVE_POLICY_PATH
    policy = normalize_proactive_policy(payload)
    # 两张档位表都不属于这个文件：唯一来源是 reply_strategy.json，写在这里只会变成
    # 第二个真相（历史上就是这么长出重复分档表的）。
    policy.pop("tiers", None)
    policy.pop("activity_tiers", None)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(".bak")
        backup.write_bytes(target.read_bytes())
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    # 档位表不进 proactive_policy.json：唯一来源是 reply_strategy.json，由
    # persist_tiers_from_payload() 负责落盘（见 WebUI 的 /api/proactive/save）。
    return policy


def normalize_proactive_policy(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("主动互动配置必须是 JSON 对象")
    policy = default_proactive_policy()
    for key in ("enabled", "owner_only", "use_ai", "guided_topics", "group_enabled"):
        if key in payload:
            policy[key] = _as_bool(payload[key])
    for key, minimum, maximum in (
        ("check_seconds", 15, 3600),
        ("history_limit", 0, 20),
        ("max_chars", 20, 240),
        ("private_active_days", 1, 365),
        ("private_min_messages", 1, 10000),
        ("group_active_days", 1, 90),
        ("group_min_messages", 1, 100000),
        ("group_daily_limit", 0, 12),
    ):
        if key in payload:
            policy[key] = _bounded_int(payload[key], minimum, maximum, key)
    if "ignored_backoff" in payload:
        policy["ignored_backoff"] = _bounded_float(payload["ignored_backoff"], 1.0, 3.0, "ignored_backoff")
    for key, minimum, maximum in (
        ("private_min_affection", 0, 100),
        ("group_min_activity", 0, 100),
        ("group_min_hours", 0.25, 168),
        ("group_max_hours", 0.25, 336),
    ):
        if key in payload:
            policy[key] = _bounded_float(payload[key], minimum, maximum, key)
    policy["group_max_hours"] = max(policy["group_min_hours"], policy["group_max_hours"])

    for key in ("quiet_start", "quiet_end"):
        if key in payload:
            value = str(payload[key]).strip()
            parse_hhmm(value)
            policy[key] = value
    if "timezone" in payload:
        timezone_name = str(payload["timezone"]).strip() or "Asia/Shanghai"
        safe_zoneinfo(timezone_name)
        policy["timezone"] = timezone_name

    incoming_weights = payload.get("content_weights")
    if isinstance(incoming_weights, dict):
        policy["content_weights"] = {
            key: _bounded_int(incoming_weights.get(key, value), 0, 100, key)
            for key, value in policy["content_weights"].items()
        }
    if not any(policy["content_weights"].values()):
        raise ValueError("至少需要启用一种主动消息内容")
    incoming_group_weights = payload.get("group_content_weights")
    if isinstance(incoming_group_weights, dict):
        policy["group_content_weights"] = {
            key: _bounded_int(incoming_group_weights.get(key, value), 0, 100, key)
            for key, value in policy["group_content_weights"].items()
        }
    if policy["group_enabled"] and not any(policy["group_content_weights"].values()):
        raise ValueError("启用群聊主动互动时，至少需要启用一种群聊内容")
    return policy


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    return min(maximum, max(minimum, parsed))


def _bounded_float(value: Any, minimum: float, maximum: float, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    return min(maximum, max(minimum, parsed))
