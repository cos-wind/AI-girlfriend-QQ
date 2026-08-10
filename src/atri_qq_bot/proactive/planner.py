from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from .time_utils import parse_hhmm, safe_zoneinfo


@dataclass(frozen=True)
class ProactivePlan:
    conversation_id: str
    target: dict[str, Any]
    event_type: str
    scheduled_at: float
    tier_id: str


class ProactivePlanner:
    def __init__(self, memory: Any, owner_qqs: Iterable[int], rng: random.Random | None = None) -> None:
        self.memory = memory
        self.owner_qqs = tuple(int(value) for value in owner_qqs if int(value) > 0)
        self.rng = rng or random.Random()

    def update_owner_qqs(self, owner_qqs: Iterable[int]) -> None:
        self.owner_qqs = tuple(int(value) for value in owner_qqs if int(value) > 0)

    def due_plans(self, policy: dict[str, Any], now: datetime | None = None) -> list[ProactivePlan]:
        if not policy.get("enabled", True):
            return []
        timezone = safe_zoneinfo(str(policy["timezone"]))
        local_now = now.astimezone(timezone) if now else datetime.now(timezone)
        now_ts = local_now.timestamp()
        due: list[ProactivePlan] = []
        owner_ids = set(self.owner_qqs)
        candidates = self.memory.proactive_candidates(
            self.owner_qqs,
            False,
            include_groups=True,
        )

        for conversation_id, target in candidates:
            user_id = int(target.get("user_id") or 0)
            is_owner = user_id in owner_ids
            is_group = target.get("message_type") == "group"
            state = self.memory.proactive_state(
                conversation_id,
                is_owner=is_owner,
                now=now_ts,
            )
            tier, _ = candidate_tier(policy, state, is_owner, is_group, now_ts)
            if not tier:
                if state.get("next_at"):
                    self.memory.clear_proactive_plan(conversation_id)
                continue

            today = local_now.date().isoformat()
            today_count = int(state.get("daily_count", 0)) if state.get("daily_date") == today else 0
            scheduled_at = float(state.get("next_at") or 0)
            if scheduled_at <= 0:
                ignored_streak = int(state.get("ignored_streak", 0))
                if state.get("awaiting_reply"):
                    ignored_streak = self.memory.note_proactive_unanswered(conversation_id)
                planned = self._build_next_plan(local_now, tier, policy, ignored_streak, today_count)
                self.memory.set_proactive_plan(
                    conversation_id,
                    planned.timestamp(),
                    self._choose_event(planned, policy, state, is_group),
                )
                continue

            if scheduled_at > now_ts:
                continue
            if today_count >= int(tier["daily_limit"]):
                planned = self._tomorrow_plan(local_now, policy)
                self.memory.set_proactive_plan(
                    conversation_id,
                    planned.timestamp(),
                    self._choose_event(planned, policy, state, is_group),
                )
                continue
            if _is_quiet(local_now, policy):
                planned = _after_quiet(local_now, policy) + timedelta(minutes=self.rng.uniform(5, 35))
                self.memory.set_proactive_plan(
                    conversation_id,
                    planned.timestamp(),
                    self._choose_event(planned, policy, state, is_group),
                )
                continue

            due.append(
                ProactivePlan(
                    conversation_id=conversation_id,
                    target=target,
                    event_type=str(
                        state.get("next_event_type")
                        or self._choose_event(local_now, policy, state, is_group)
                    ),
                    scheduled_at=scheduled_at,
                    tier_id=str(tier["id"]),
                )
            )
        return due

    def status(self, policy: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        timezone = safe_zoneinfo(str(policy["timezone"]))
        local_now = now.astimezone(timezone) if now else datetime.now(timezone)
        owner_ids = set(self.owner_qqs)
        items: list[dict[str, Any]] = []
        for conversation_id, target in self.memory.proactive_candidates(
            self.owner_qqs,
            False,
            include_groups=True,
        ):
            user_id = int(target.get("user_id") or 0)
            is_owner = user_id in owner_ids
            is_group = target.get("message_type") == "group"
            state = self.memory.proactive_state(
                conversation_id,
                is_owner=is_owner,
                now=local_now.timestamp(),
            )
            tier, reason = candidate_tier(
                policy,
                state,
                is_owner,
                is_group,
                local_now.timestamp(),
            )
            items.append({
                "conversation_id": conversation_id,
                "target_type": "group" if is_group else "private",
                "target_id": int(target.get("group_id") or user_id),
                "user_id": user_id,
                "group_id": int(target.get("group_id") or 0),
                "affection_score": round(float(state.get("affection_score", 0)), 1),
                "group_activity_score": round(float(state.get("group_activity_score", 0)), 1),
                "message_count": int(state.get("message_count", 0)),
                "last_user_at": state.get("last_user_at"),
                "eligible": tier is not None,
                "eligibility_reason": reason,
                "tier": tier.get("name") if tier else ("活跃群聊" if is_group else "未入选"),
                "next_at": state.get("next_at"),
                "next_event_type": state.get("next_event_type") or "",
                "last_at": state.get("last_at"),
                "last_source": state.get("last_source") or "",
                "ignored_streak": int(state.get("ignored_streak", 0)),
            })
        return {"now": local_now.timestamp(), "timezone": str(policy["timezone"]), "items": items}

    def _build_next_plan(self, now: datetime, tier: dict[str, Any], policy: dict[str, Any], ignored_streak: int, today_count: int) -> datetime:
        if today_count >= int(tier["daily_limit"]):
            return self._tomorrow_plan(now, policy)
        backoff = float(policy.get("ignored_backoff", 1.5)) ** min(ignored_streak, 4)
        hours = self.rng.uniform(float(tier["min_hours"]), float(tier["max_hours"])) * backoff
        planned = now + timedelta(hours=min(hours, 336))
        if _is_quiet(planned, policy):
            planned = _after_quiet(planned, policy) + timedelta(minutes=self.rng.uniform(5, 35))
        return planned

    def _tomorrow_plan(self, now: datetime, policy: dict[str, Any]) -> datetime:
        _, end_minute = parse_hhmm(str(policy["quiet_end"]))
        end_hour, _ = parse_hhmm(str(policy["quiet_end"]))
        tomorrow = (now + timedelta(days=1)).replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        return tomorrow + timedelta(minutes=self.rng.uniform(10, 90))

    def _choose_event(
        self,
        planned: datetime,
        policy: dict[str, Any],
        state: dict[str, Any],
        is_group: bool,
    ) -> str:
        weights = dict(
            policy.get("group_content_weights" if is_group else "content_weights") or {}
        )
        if not policy.get("guided_topics", True):
            weights["guided_topic"] = 0
        hour = planned.hour
        today = planned.date().isoformat()
        event_dates = state.get("event_dates") or {}
        if not is_group and 6 <= hour < 11 and event_dates.get("morning") != today and weights.get("morning", 0) > 0:
            weights["morning"] = max(weights["morning"], 30)
        else:
            weights["morning"] = 0
        if not is_group and 21 <= hour <= 23 and event_dates.get("goodnight") != today and weights.get("goodnight", 0) > 0:
            weights["goodnight"] = max(weights["goodnight"], 30)
        else:
            weights["goodnight"] = 0
        choices = [(name, max(0, int(weight))) for name, weight in weights.items() if int(weight) > 0]
        if not choices:
            return "check_in"
        return self.rng.choices([item[0] for item in choices], weights=[item[1] for item in choices], k=1)[0]


def tier_for_affection(policy: dict[str, Any], affection: float) -> dict[str, Any] | None:
    for tier in policy.get("tiers") or []:
        if float(tier["min_affection"]) <= affection < float(tier["max_affection"]):
            return tier
    return None


def candidate_tier(
    policy: dict[str, Any],
    state: dict[str, Any],
    is_owner: bool,
    is_group: bool,
    now_ts: float,
) -> tuple[dict[str, Any] | None, str]:
    last_user_at = float(state.get("last_user_at") or 0)
    message_count = int(state.get("message_count", 0))
    override = str(state.get("proactive_override") or "auto").strip().lower()
    trust_tier = str(state.get("trust_tier") or "probation").strip().lower()
    if override == "deny":
        return None, "已手动禁止主动互动"
    if not is_group and not is_owner and trust_tier == "blocked":
        return None, "用户已被屏蔽"
    if is_group:
        if override == "allow":
            return {
                "id": "active_group",
                "name": "手动允许的群聊",
                "enabled": True,
                "min_hours": float(policy.get("group_min_hours", 3)),
                "max_hours": float(policy.get("group_max_hours", 9)),
                "daily_limit": max(1, int(policy.get("group_daily_limit", 2))),
            }, "已手动允许"
        if not policy.get("group_enabled", False):
            return None, "群聊主动互动未启用"
        if int(policy.get("group_daily_limit", 2)) <= 0:
            return None, "群聊每日上限为 0"
        if message_count < int(policy.get("group_min_messages", 12)):
            return None, "群消息量不足"
        if not last_user_at or now_ts - last_user_at > int(policy.get("group_active_days", 3)) * 86400:
            return None, "群聊近期不活跃"
        if float(state.get("group_activity_score", 0)) < float(policy.get("group_min_activity", 55)):
            return None, "群活跃度未达门槛"
        return {
            "id": "active_group",
            "name": "活跃群聊",
            "enabled": True,
            "min_hours": float(policy.get("group_min_hours", 3)),
            "max_hours": float(policy.get("group_max_hours", 9)),
            "daily_limit": int(policy.get("group_daily_limit", 2)),
        }, "已入选"

    if not is_owner and trust_tier not in {"approved", "trusted"} and override != "allow":
        return None, "尚未加入主动互动白名单"
    affection = float(state.get("affection_score", 0))
    tier = tier_for_affection(policy, affection)
    if override == "allow" and tier:
        forced_tier = dict(tier)
        forced_tier["enabled"] = True
        forced_tier["daily_limit"] = max(1, int(forced_tier.get("daily_limit", 0)))
        return forced_tier, "已手动允许"
    if not tier or not tier.get("enabled") or int(tier.get("daily_limit", 0)) <= 0:
        return None, "当前亲密阶段未启用"
    if is_owner:
        return tier, "主人"
    if policy.get("owner_only", False):
        return None, "当前仅给主人发送"
    if affection < float(policy.get("private_min_affection", 70)):
        return None, "好感度未达门槛"
    if message_count < int(policy.get("private_min_messages", 5)):
        return None, "私聊消息量不足"
    if not last_user_at or now_ts - last_user_at > int(policy.get("private_active_days", 14)) * 86400:
        return None, "近期未活跃"
    return tier, "高好感活跃用户"


def _is_quiet(value: datetime, policy: dict[str, Any]) -> bool:
    start_hour, start_minute = parse_hhmm(str(policy["quiet_start"]))
    end_hour, end_minute = parse_hhmm(str(policy["quiet_end"]))
    current = value.hour * 60 + value.minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _after_quiet(value: datetime, policy: dict[str, Any]) -> datetime:
    end_hour, end_minute = parse_hhmm(str(policy["quiet_end"]))
    candidate = value.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    start_hour, start_minute = parse_hhmm(str(policy["quiet_start"]))
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    current = value.hour * 60 + value.minute
    if start > end and current >= start:
        candidate += timedelta(days=1)
    elif candidate <= value:
        candidate += timedelta(days=1)
    return candidate
