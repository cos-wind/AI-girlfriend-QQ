from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..runtime.paths import PROACTIVE_POLICY_PATH
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
    "tiers": [
        {"id": "low", "name": "较低", "min_affection": 0, "max_affection": 35, "enabled": False, "min_hours": 18, "max_hours": 30, "daily_limit": 0},
        {"id": "normal", "name": "普通", "min_affection": 35, "max_affection": 55, "enabled": True, "min_hours": 10, "max_hours": 24, "daily_limit": 1},
        {"id": "familiar", "name": "熟悉", "min_affection": 55, "max_affection": 70, "enabled": True, "min_hours": 5, "max_hours": 14, "daily_limit": 2},
        {"id": "close", "name": "亲近", "min_affection": 70, "max_affection": 85, "enabled": True, "min_hours": 2.5, "max_hours": 9, "daily_limit": 3},
        {"id": "intimate", "name": "亲密", "min_affection": 85, "max_affection": 101, "enabled": True, "min_hours": 1.5, "max_hours": 6, "daily_limit": 4},
    ],
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
    return deepcopy(DEFAULT_PROACTIVE_POLICY)


def load_proactive_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or PROACTIVE_POLICY_PATH
    if not target.exists():
        return default_proactive_policy()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_proactive_policy()
    return normalize_proactive_policy(payload)


def save_proactive_policy(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = path or PROACTIVE_POLICY_PATH
    policy = normalize_proactive_policy(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(".bak")
        backup.write_bytes(target.read_bytes())
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
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

    incoming_tiers = payload.get("tiers")
    if isinstance(incoming_tiers, list):
        by_id = {str(item.get("id")): item for item in incoming_tiers if isinstance(item, dict)}
        normalized_tiers: list[dict[str, Any]] = []
        for default in policy["tiers"]:
            incoming = by_id.get(default["id"], {})
            tier = dict(default)
            tier["name"] = str(incoming.get("name", tier["name"]))[:12]
            tier["enabled"] = _as_bool(incoming.get("enabled", tier["enabled"]))
            tier["min_affection"] = _bounded_float(incoming.get("min_affection", tier["min_affection"]), 0, 100, "min_affection")
            tier["max_affection"] = _bounded_float(incoming.get("max_affection", tier["max_affection"]), tier["min_affection"], 101, "max_affection")
            tier["min_hours"] = _bounded_float(incoming.get("min_hours", tier["min_hours"]), 0.25, 168, "min_hours")
            tier["max_hours"] = _bounded_float(incoming.get("max_hours", tier["max_hours"]), tier["min_hours"], 336, "max_hours")
            tier["daily_limit"] = _bounded_int(incoming.get("daily_limit", tier["daily_limit"]), 0, 12, "daily_limit")
            normalized_tiers.append(tier)
        policy["tiers"] = normalized_tiers

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
