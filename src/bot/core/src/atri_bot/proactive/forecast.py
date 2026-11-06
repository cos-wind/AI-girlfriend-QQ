"""Read-only, reproducible opportunity times; never a second scheduler."""
from __future__ import annotations

import hashlib
import random
import time
from datetime import datetime, timedelta

from .time_utils import safe_zoneinfo


def next_opportunity(conversation_id, anchor, policy, *, activity=0, ignored=0):
    from .planner import _after_quiet, _is_quiet

    prefix = "group_hot" if conversation_id.startswith("group:") and activity >= 70 else (
        "group" if conversation_id.startswith("group:") else "private")
    seed = hashlib.sha256(f"{conversation_id}:{anchor:.6f}".encode()).digest()
    rng = random.Random(seed)
    hours = rng.uniform(float(policy[f"{prefix}_min_hours"]), float(policy[f"{prefix}_max_hours"]))
    hours *= float(policy.get("ignored_backoff", 1.5)) ** min(ignored, 4)
    value = datetime.fromtimestamp(anchor, safe_zoneinfo(str(policy["timezone"]))) + timedelta(hours=min(hours, 336))
    if _is_quiet(value, policy):
        value = _after_quiet(value, policy) + timedelta(minutes=rng.uniform(5, 35))
    return value.timestamp()


def upcoming_times(conversation_id, anchor, policy, *, now=None, activity=0, ignored=0):
    now = time.time() if now is None else now
    if not anchor or anchor <= 0:
        return []
    # Old anchors can be years old. Bound work and restart the forecast from now.
    cursor = max(float(anchor), now - 8 * 86400)
    end = now + 7 * 86400
    values = []
    for _ in range(1600):
        if cursor > end:
            break
        if cursor > now:
            values.append(cursor)
        cursor = next_opportunity(conversation_id, cursor, policy, activity=activity, ignored=ignored)
    return values


def public_plan(conversation_id, item, policy, *, now=None):
    now = time.time() if now is None else now
    blocked = (not policy.get("enabled", True) or item.get("proactive_override") == "deny"
               or item.get("trust_tier") == "blocked" or item.get("proactive_delivery_uncertain")
               or int(item.get("proactive_ignored_streak", 0)) >= int(policy.get("max_unanswered", 2)))
    if conversation_id.startswith("group:") and not policy.get("group_enabled", False):
        blocked = True
    times = [] if blocked else upcoming_times(conversation_id, item.get("next_proactive_at"), policy,
        now=now, activity=float(item.get("group_activity_score") or 0),
        ignored=int(item.get("proactive_ignored_streak", 0)) + int(bool(item.get("proactive_awaiting_reply"))))
    next_at = times[0] if times else None
    if not blocked and not next_at and float(item.get("next_proactive_at") or 0) > now:
        next_at = item["next_proactive_at"]
    return {"next_at": next_at, "upcoming": times,
            "next_event_type": item.get("next_proactive_event_type", ""),
            "awaiting_reply": bool(item.get("proactive_awaiting_reply")),
            "delivery_uncertain": bool(item.get("proactive_delivery_uncertain")),
            "timezone": policy["timezone"], "conditional": True,
            "missed": bool(item.get("next_proactive_at") and item["next_proactive_at"] <= now)}
