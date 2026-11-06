from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from atri_bot.proactive.time_utils import parse_hhmm, safe_zoneinfo


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
        self._ready_at = 0.0

    def update_owner_qqs(self, owner_qqs: Iterable[int]) -> None:
        self.owner_qqs = tuple(int(value) for value in owner_qqs if int(value) > 0)

    def due_plans(self, policy: dict[str, Any], now: datetime | None = None,
                  allowed_targets: set[str] | None = None) -> list[ProactivePlan]:
        if not policy.get("enabled", True):
            return []
        timezone = safe_zoneinfo(str(policy["timezone"]))
        local_now = now.astimezone(timezone) if now else datetime.now(timezone)
        now_ts = local_now.timestamp()
        starting = not self._ready_at
        if starting:
            self._ready_at = now_ts + self.rng.uniform(120, 300)
        due: list[ProactivePlan] = []
        states: dict[str, dict[str, Any]] = {}
        latest_evaluation = 0.0
        owner_ids = set(self.owner_qqs)
        candidates = self.memory.proactive_candidates(
            self.owner_qqs,
            False,
            include_groups=True,
        )

        for conversation_id, target in candidates:
            if allowed_targets is not None and conversation_id not in allowed_targets:
                continue
            user_id = int(target.get("user_id") or 0)
            is_owner = user_id in owner_ids
            is_group = target.get("message_type") == "group"
            state = self.memory.proactive_state(
                conversation_id,
                is_owner=is_owner,
                now=now_ts,
            )
            latest_evaluation = max(latest_evaluation, float(state.get("evaluated_at") or 0), float(state.get("last_at") or 0))
            scheduled_at = float(state.get("next_at") or 0)
            if scheduled_at and scheduled_at <= now_ts and state.get("awaiting_reply"):
                state["ignored_streak"] = self.memory.note_proactive_unanswered(conversation_id)
                state["awaiting_reply"] = False
            tier, _ = candidate_tier(policy, state, is_owner, is_group, now_ts)
            if not tier:
                if state.get("next_at"):
                    self.memory.clear_proactive_plan(conversation_id)
                continue

            if scheduled_at <= 0 or state.get("schedule_version") != 3:
                # One-time migration and first-run catch-up; never replay a backlog.
                if not state.get("evaluated_at") and not state.get("last_at"):
                    planned = local_now + timedelta(seconds=self.rng.uniform(120, 300))
                elif state.get("schedule_version") != 3:
                    planned = local_now + timedelta(seconds=self.rng.uniform(120, 300))
                else:
                    planned = self._build_next_plan(local_now, tier, policy,
                        int(state.get("ignored_streak", 0)) + int(bool(state.get("awaiting_reply"))))
                planned = self._respect_quiet(planned, policy)
                self.memory.set_proactive_plan(
                    conversation_id,
                    planned.timestamp(),
                    self._choose_event(planned, policy, state, is_group),
                )
                continue

            if scheduled_at > now_ts:
                continue
            if starting:
                # Missed while offline: advance the same calendar, never catch up.
                from .forecast import upcoming_times
                upcoming = upcoming_times(conversation_id, scheduled_at, policy, now=now_ts,
                    activity=float(state.get("group_activity_score", 0)),
                    ignored=int(state.get("ignored_streak", 0)))
                if upcoming:
                    planned = datetime.fromtimestamp(upcoming[0], timezone)
                    self.memory.set_proactive_plan(conversation_id, upcoming[0],
                        self._choose_event(planned, policy, state, is_group))
                continue
            if _is_quiet(local_now, policy):
                planned = _after_quiet(local_now, policy) + timedelta(minutes=self.rng.uniform(5, 35))
                self.memory.set_proactive_plan(
                    conversation_id,
                    planned.timestamp(),
                    self._choose_event(planned, policy, state, is_group),
                )
                continue

            last_active = max(float(state.get("last_user_at") or 0), float(state.get("last_bot_at") or 0))
            if now_ts - last_active < float(policy.get("conversation_cooldown_minutes", 10)) * 60:
                continue
            states[conversation_id] = state

            event_type = state.get("next_event_type")
            if ((event_type == "morning" and not 6 <= local_now.hour < 11)
                    or (event_type == "goodnight" and not 21 <= local_now.hour <= 23)):
                event_type = None

            due.append(
                ProactivePlan(
                    conversation_id=conversation_id,
                    target=target,
                    # Keep the prepared type unless its greeting window has passed.
                    event_type=event_type or self._choose_event(local_now, policy, state, is_group),
                    scheduled_at=scheduled_at,
                    tier_id=str(tier["id"]),
                )
            )
        if now_ts < max(self._ready_at, latest_evaluation + float(policy.get("global_gap_minutes", 7)) * 60):
            return []
        # Least recently evaluated first, including deferred/error candidates.
        due.sort(key=lambda plan: (float(states[plan.conversation_id].get("evaluated_at") or 0),
                                  float(states[plan.conversation_id].get("last_at") or 0),
                                  plan.scheduled_at, plan.conversation_id))
        return due[:1]

    def complete(self, plan: ProactivePlan, policy: dict[str, Any], outcome: str,
                 now: datetime | None = None) -> None:
        local_now = now or datetime.now(safe_zoneinfo(str(policy["timezone"])))
        self.memory.record_proactive_evaluation(plan.conversation_id, outcome, local_now.timestamp())
        state = self.memory.proactive_state(plan.conversation_id, now=local_now.timestamp())
        tier, _ = candidate_tier(policy, state, int(plan.target.get("user_id") or 0) in self.owner_qqs,
                                 plan.target.get("message_type") == "group", local_now.timestamp())
        if outcome in {"unknown", "sending"} or tier is None:
            self.memory.clear_proactive_plan(plan.conversation_id)
            return
        if outcome == "failure":
            planned = local_now + timedelta(minutes=min(120, 15 * 2 ** min(3, int(state["failures"]) - 1)))
        else:
            from .forecast import next_opportunity
            anchor = max(plan.scheduled_at, local_now.timestamp() - 8 * 86400)
            while anchor <= local_now.timestamp():
                anchor = next_opportunity(plan.conversation_id, anchor, policy,
                    activity=float(state.get("group_activity_score", 0)),
                    ignored=int(state.get("ignored_streak", 0)) + int(bool(state.get("awaiting_reply"))))
            planned = datetime.fromtimestamp(anchor, local_now.tzinfo)
        planned = self._respect_quiet(planned, policy)
        self.memory.set_proactive_plan(plan.conversation_id, planned.timestamp(),
            self._choose_event(planned, policy, state, plan.target.get("message_type") == "group"))

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
                "decision": state.get("decision"),
                "evaluated_at": state.get("evaluated_at"),
                "delivery_uncertain": state.get("delivery_uncertain"),
            })
        return {"now": local_now.timestamp(), "timezone": str(policy["timezone"]), "items": items}

    def _build_next_plan(self, now: datetime, tier: dict[str, Any], policy: dict[str, Any], ignored_streak: int) -> datetime:
        backoff = float(policy.get("ignored_backoff", 1.5)) ** min(ignored_streak, 4)
        hours = self.rng.uniform(float(tier["min_hours"]), float(tier["max_hours"])) * backoff
        planned = now + timedelta(hours=min(hours, 336))
        return self._respect_quiet(planned, policy)

    def _respect_quiet(self, planned: datetime, policy: dict[str, Any]) -> datetime:
        if _is_quiet(planned, policy):
            return _after_quiet(planned, policy) + timedelta(minutes=self.rng.uniform(5, 35))
        return planned

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
    # 保留旧档位查询接口；机会调度使用 candidate_tier 的独立间隔。
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
    override = str(state.get("proactive_override") or "auto")
    if override == "deny":
        return None, "已手动禁止主动互动"
    if state.get("trust_tier") == "blocked":
        return None, "用户已被屏蔽"
    if state.get("delivery_uncertain"):
        return None, "发送回执未知，等待明确回应后恢复"
    if int(state.get("ignored_streak", 0)) >= int(policy.get("max_unanswered", 2)):
        return None, "连续未回复，等待明确回应后恢复"
    if is_group and not policy.get("group_enabled", False):
        return None, "群聊主动互动未启用"
    if not is_group and not is_owner and policy.get("owner_only", False) and override != "allow":
        return None, "当前仅给主人发送"
    if override != "allow" and not is_owner:
        prefix = "group" if is_group else "private"
        if int(state.get("message_count", 0)) < int(policy.get(f"{prefix}_min_messages", 12 if is_group else 5)):
            return None, "消息量不足"
        last_at = float(state.get("last_user_at") or 0)
        if not last_at or now_ts - last_at > int(policy.get(f"{prefix}_active_days", 3 if is_group else 14)) * 86400:
            return None, "近期未活跃"
    prefix = "group_hot" if is_group and float(state.get("group_activity_score", 0)) >= 70 else ("group" if is_group else "private")
    return {
        "id": prefix, "name": {"private": "活跃好友", "group": "普通群", "group_hot": "活跃群"}[prefix],
        "enabled": True,
        "min_hours": float(policy[f"{prefix}_min_hours"]),
        "max_hours": float(policy[f"{prefix}_max_hours"]),
    }, "已手动允许" if override == "allow" else ("主人" if is_owner else "近期活跃会话")



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
