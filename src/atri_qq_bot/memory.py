from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .memory_parts import core as _memory_core

from .proactive import parse_hhmm, safe_zoneinfo


TOPIC_STOPWORDS = _memory_core.TOPIC_STOPWORDS
CORRECTION_HINTS = _memory_core.CORRECTION_HINTS
DIRECT_HINTS = _memory_core.DIRECT_HINTS
COMFORT_HINTS = _memory_core.COMFORT_HINTS
ABSTRACT_HINTS = _memory_core.ABSTRACT_HINTS
HISTORY_LIMIT = _memory_core.HISTORY_LIMIT
MEMORY_VERSION = _memory_core.MEMORY_VERSION
L1_CONFIRMATIONS_REQUIRED = _memory_core.L1_CONFIRMATIONS_REQUIRED
L2_SLEEP_THRESHOLD = _memory_core.L2_SLEEP_THRESHOLD
L2_DAILY_DECAY = _memory_core.L2_DAILY_DECAY
DEFAULT_AFFECTION = _memory_core.DEFAULT_AFFECTION
OWNER_INITIAL_AFFECTION = _memory_core.OWNER_INITIAL_AFFECTION
GROUP_ACTIVITY_DEFAULT = _memory_core.GROUP_ACTIVITY_DEFAULT
GROUP_ACTIVITY_DAILY_DECAY = _memory_core.GROUP_ACTIVITY_DAILY_DECAY
OWNER_AFFECTION_COEFFICIENT = _memory_core.OWNER_AFFECTION_COEFFICIENT
NORMAL_AFFECTION_COEFFICIENT = _memory_core.NORMAL_AFFECTION_COEFFICIENT
PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS = _memory_core.PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS
PRIVATE_AFFECTION_IDLE_DAILY_DECAY = _memory_core.PRIVATE_AFFECTION_IDLE_DAILY_DECAY
OWNER_AFFECTION_IDLE_DAILY_DECAY = _memory_core.OWNER_AFFECTION_IDLE_DAILY_DECAY
PRIVATE_NUDGE_STOP_AFFECTION = _memory_core.PRIVATE_NUDGE_STOP_AFFECTION
PRIVATE_NUDGE_SLOW_AFFECTION = _memory_core.PRIVATE_NUDGE_SLOW_AFFECTION
PRIVATE_NUDGE_CLOSE_AFFECTION = _memory_core.PRIVATE_NUDGE_CLOSE_AFFECTION
PRIVATE_NUDGE_SLOW_MULTIPLIER = _memory_core.PRIVATE_NUDGE_SLOW_MULTIPLIER
PRIVATE_NUDGE_NORMAL_MULTIPLIER = _memory_core.PRIVATE_NUDGE_NORMAL_MULTIPLIER
MAJOR_POSITIVE_HINTS = _memory_core.MAJOR_POSITIVE_HINTS
MAJOR_NEGATIVE_HINTS = _memory_core.MAJOR_NEGATIVE_HINTS
MEDIUM_POSITIVE_HINTS = _memory_core.MEDIUM_POSITIVE_HINTS
MEDIUM_NEGATIVE_HINTS = _memory_core.MEDIUM_NEGATIVE_HINTS
ACTIONABLE_STYLE_HINTS = _memory_core.ACTIONABLE_STYLE_HINTS
AGGRESSIVE_QUALITY_HINTS = _memory_core.AGGRESSIVE_QUALITY_HINTS
DAILY_POSITIVE_HINTS = _memory_core.DAILY_POSITIVE_HINTS
NEGATIVE_MOOD_HINTS = _memory_core.NEGATIVE_MOOD_HINTS
MEMORY_POLLUTION_PATTERNS = _memory_core.MEMORY_POLLUTION_PATTERNS
NOISY_MEMORY_HINTS = _memory_core.NOISY_MEMORY_HINTS
MEMORY_TOPIC_BLOCKLIST = _memory_core.MEMORY_TOPIC_BLOCKLIST
EVENT_HINTS = _memory_core.EVENT_HINTS
TIME_HINT_PATTERN = _memory_core.TIME_HINT_PATTERN
IMPLICIT_INTEREST_HINTS = _memory_core.IMPLICIT_INTEREST_HINTS



class UserMemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data = self._load()
        self._session_l3: dict[str, list[dict[str, Any]]] = {}

    def observe_user(
        self,
        conversation_id: str,
        text: str,
        now: float | None = None,
        actor_id: int | str | None = None,
        nickname: str | None = None,
        is_owner: bool = False,
        update_affection: bool | None = None,
        update_group_activity: bool | None = None,
        addressed_to_bot: bool = False,
    ) -> None:
        if is_memory_pollution_text(text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _decay_event_memories(item, now)
        _initialize_affection(item, is_owner)
        if update_affection is not False and not _is_group_conversation(conversation_id):
            _decay_private_affection_for_idle(item, now)
        if update_affection is None:
            update_affection = not _is_group_conversation(conversation_id)
        if update_group_activity is None:
            update_group_activity = _is_group_conversation(conversation_id)
        if update_group_activity:
            _update_group_activity(item, text, addressed_to_bot, now)
        previous_user_at = _as_float(item.get("last_user_at"))

        count = int(item.get("message_count", 0)) + 1
        item["message_count"] = count
        item["avg_user_chars"] = _running_average(
            _as_float(item.get("avg_user_chars")) or 0.0, count, len(text)
        )

        if previous_user_at:
            gap = max(1.0, now - previous_user_at)
            gap_count = int(item.get("gap_count", 0)) + 1
            item["gap_count"] = gap_count
            item["avg_user_gap_seconds"] = _running_average(
                _as_float(item.get("avg_user_gap_seconds")) or gap, gap_count, gap
            )

        item["last_user_at"] = now
        if not _is_group_conversation(conversation_id):
            item["last_affection_idle_decay_at"] = now
        item["emoji_count"] = int(item.get("emoji_count", 0)) + _emoji_count(text)
        item["question_count"] = int(item.get("question_count", 0)) + text.count("?") + text.count("？")
        style_flags = _style_flags(text)
        for key, enabled in style_flags.items():
            if enabled:
                item[key] = int(item.get(key, 0)) + 1
        if style_flags["correction_count"]:
            item["last_quality_complaint"] = _shorten(text, 80)
        _merge_feature_counts(item, _message_features(text))
        _append_history(item, "user", text, now, actor_id=actor_id, nickname=nickname)
        item["topic_words"] = _merge_topics(item.get("topic_words"), _extract_topics(text))
        _append_session_l3(self._session_l3, conversation_id, text, now)
        affection_event = _classify_affection_event(text)
        if update_affection:
            _update_affection(item, affection_event, is_owner)
        _remember_structured_from_user(item, text, now, affection_event)
        self._save()

    def observe_bot(
        self,
        conversation_id: str,
        reply_text: str,
        sent_sticker: bool = False,
        now: float | None = None,
    ) -> None:
        if is_memory_pollution_text(reply_text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        item["last_bot_at"] = now
        item["avg_bot_chars"] = _running_average(
            _as_float(item.get("avg_bot_chars")) or 0.0,
            int(item.get("bot_reply_count", 0)) + 1,
            len(reply_text),
        )
        item["bot_reply_count"] = int(item.get("bot_reply_count", 0)) + 1
        if sent_sticker:
            item["sent_sticker_count"] = int(item.get("sent_sticker_count", 0)) + 1
            item["last_sticker_at"] = now
        if not is_memory_pollution_text(reply_text):
            _append_history(item, "assistant", reply_text, now)
        self._save()

    def remember_target(self, conversation_id: str, event: dict[str, Any]) -> None:
        item = self._conversation(conversation_id)
        if event.get("message_type") == "private":
            item["target"] = {
                "message_type": "private",
                "user_id": event.get("user_id"),
            }
        elif event.get("message_type") == "group":
            target = {
                "message_type": "group",
                "group_id": event.get("group_id"),
            }
            if ":user:" in conversation_id:
                target["user_id"] = event.get("user_id")
            item["target"] = target
        self._save()

    def observe_group_message(
        self,
        group_id: int | str,
        user_id: int | str,
        text: str,
        nickname: str | None = None,
        now: float | None = None,
        addressed_to_bot: bool = False,
        is_owner: bool = False,
    ) -> tuple[str, str]:
        group_conversation_id = f"group:{group_id}"
        member_conversation_id = f"group:{group_id}:user:{user_id}"
        self.observe_user(
            group_conversation_id,
            text,
            now=now,
            actor_id=user_id,
            nickname=nickname,
            is_owner=False,
            update_affection=False,
            update_group_activity=True,
            addressed_to_bot=addressed_to_bot,
        )
        self.observe_user(
            member_conversation_id,
            text,
            now=now,
            actor_id=user_id,
            nickname=nickname,
            is_owner=is_owner,
            update_affection=addressed_to_bot,
            update_group_activity=False,
            addressed_to_bot=addressed_to_bot,
        )
        if addressed_to_bot:
            self.observe_affection_event(
                f"private:{user_id}",
                text,
                now=now,
                is_owner=is_owner,
            )
        return group_conversation_id, member_conversation_id

    def observe_affection_event(
        self,
        conversation_id: str,
        text: str,
        now: float | None = None,
        is_owner: bool = False,
    ) -> None:
        if is_memory_pollution_text(text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        affection_event = _classify_affection_event(text)
        _update_affection(item, affection_event, is_owner)
        _remember_important_interaction(item, text, now, affection_event)
        self._save()

    def record_iteration_decision(
        self,
        conversation_id: str,
        user_text: str,
        action: str,
        reason: str,
        now: float | None = None,
    ) -> None:
        if is_memory_pollution_text(user_text) or is_memory_pollution_text(reason):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        rule_text = _iteration_rule_text(user_text, action, reason)
        decisions = list(item.get("iteration_decisions") or [])
        decisions.append(
            {
                "at": now,
                "user_text": _shorten(user_text, 120),
                "action": action,
                "reason": reason,
                "rule": rule_text,
            }
        )
        item["iteration_decisions"] = decisions[-20:]
        item["last_iteration_decision"] = decisions[-1]

        bucket_name = (
            "accepted_iteration_rules" if action == "accept" else "rejected_iteration_rules"
        )
        _append_iteration_rule(
            item,
            bucket_name,
            {
                "at": now,
                "action": action,
                "rule": rule_text,
                "reason": reason,
                "source": _shorten(user_text, 120),
            },
        )
        self._save()

    def recent_history(self, conversation_id: str, limit: int = 10) -> list[dict[str, Any]]:
        item = self._conversation(conversation_id, save=False)
        history = item.get("history")
        if not isinstance(history, list):
            return []
        return [entry for entry in history[-max(0, limit) :] if isinstance(entry, dict)]

    def profile(self, conversation_id: str, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        item = self._conversation(conversation_id, save=False)
        _ensure_structured_memory(item)
        if _decay_event_memories(item, now):
            self._save()
        if _is_group_conversation(conversation_id) and ":user:" not in conversation_id:
            before_group_activity = item.get("group_activity_score")
            _decay_group_activity(item, now)
            if item.get("group_activity_score") != before_group_activity:
                self._save()
        message_count = int(item.get("message_count", 0))
        avg_chars = _as_float(item.get("avg_user_chars")) or 0.0
        avg_gap = _as_float(item.get("avg_user_gap_seconds"))
        emoji_rate = (int(item.get("emoji_count", 0)) / max(1, message_count)) if message_count else 0.0
        question_rate = (
            int(item.get("question_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        correction_rate = (
            int(item.get("correction_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        direct_rate = (
            int(item.get("direct_request_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        comfort_rate = (
            int(item.get("comfort_request_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        abstract_rate = (
            int(item.get("abstract_signal_count", 0)) / max(1, message_count)
        ) if message_count else 0.0

        if avg_chars <= 12:
            target_chars = 36
            preferred_parts = 1
            length_style = "用户常发短句，回复要更短、更像即时聊天。"
        elif avg_chars <= 45:
            target_chars = 64
            preferred_parts = 2
            length_style = "用户消息长度中等，回复 1 到 2 条短句，别写成长段。"
        else:
            target_chars = 92
            preferred_parts = 3
            length_style = "用户愿意讲细节，回复可以多接一点具体内容，但仍要分短句。"

        if avg_gap is not None and avg_gap <= 45:
            pace_style = "用户互动节奏较快，优先短平快，不要连续追问。"
        elif avg_gap is not None and avg_gap >= 1800:
            pace_style = "用户间隔较久才回来，先自然回应当前消息，不要责备或刷屏。"
        else:
            pace_style = "按正常 QQ 聊天节奏回应。"

        if emoji_rate >= 0.35:
            emoji_style = "用户常用表情，可以偶尔加一个轻表情。"
        else:
            emoji_style = "表情要克制，优先靠语气而不是堆符号。"

        adaptation_styles: list[str] = []
        if correction_rate >= 0.12 or int(item.get("correction_count", 0)) >= 2:
            adaptation_styles.append("用户已经明确讨厌空泛套话和答非所问，回复前必须先给具体重点，别解释模型限制。")
        if direct_rate >= 0.18 or int(item.get("direct_request_count", 0)) >= 2:
            adaptation_styles.append("用户偏好直接结论和明确观点，少铺垫，先表态。")
        if comfort_rate >= 0.18 or int(item.get("comfort_request_count", 0)) >= 2:
            adaptation_styles.append("用户近期有情绪压力，难受时先具体安慰，再给一个小动作，不要讲大道理。")
        if abstract_rate >= 0.18 or int(item.get("abstract_signal_count", 0)) >= 2:
            adaptation_styles.append("用户能接抽象梗和轻吐槽，可以偶尔用一句自然吐槽，但别破坏正事。")
        accepted_rules = [
            rule.get("rule")
            for rule in (item.get("accepted_iteration_rules") or [])[-4:]
            if isinstance(rule, dict) and rule.get("rule")
        ]
        rejected_rules = [
            rule.get("rule")
            for rule in (item.get("rejected_iteration_rules") or [])[-4:]
            if isinstance(rule, dict) and rule.get("rule")
        ]
        if accepted_rules:
            adaptation_styles.append(
                f"已采纳长期对话规则：{'；'.join(accepted_rules)}。这些规则要优先执行。"
            )
        if rejected_rules:
            adaptation_styles.append(
                f"已驳回或保留判断的修正：{'；'.join(rejected_rules)}。不要为了迁就而破坏人设、边界或防刷屏。"
            )
        last_iteration = item.get("last_iteration_decision")
        if isinstance(last_iteration, dict):
            action = last_iteration.get("action")
            reason = last_iteration.get("reason")
            if action == "accept":
                adaptation_styles.append(f"最近一次纠错已采纳：{reason}。下一轮要明显修正，不要重复旧问题。")
            elif action == "pushback":
                adaptation_styles.append(f"最近一次纠错需要保留判断：{reason}。可以认一半，但不要盲目改坏。")
            elif action == "reject":
                adaptation_styles.append(f"最近一次纠错已合理拒绝：{reason}。保持边界，但语气要傲娇不冷硬。")

        structured_memory = _structured_memory_profile(
            item,
            self._session_l3.get(conversation_id) or [],
        )
        affection_score = float(item.get("affection_score", DEFAULT_AFFECTION))
        group_activity_score = float(item.get("group_activity_score", GROUP_ACTIVITY_DEFAULT))
        topic_words = _safe_topics(item.get("topic_words") or [])

        return {
            "conversation_id": conversation_id,
            "message_count": message_count,
            "avg_user_chars": avg_chars,
            "avg_user_gap_seconds": avg_gap,
            "emoji_rate": emoji_rate,
            "question_rate": question_rate,
            "correction_rate": correction_rate,
            "direct_rate": direct_rate,
            "comfort_rate": comfort_rate,
            "abstract_rate": abstract_rate,
            "prefers_direct": direct_rate >= 0.18 or int(item.get("direct_request_count", 0)) >= 2,
            "needs_comfort_first": comfort_rate >= 0.18 or int(item.get("comfort_request_count", 0)) >= 2,
            "likes_light_tucao": abstract_rate >= 0.18 or int(item.get("abstract_signal_count", 0)) >= 2,
            "last_quality_complaint": item.get("last_quality_complaint"),
            "last_iteration_decision": item.get("last_iteration_decision"),
            "accepted_iteration_rules": item.get("accepted_iteration_rules") or [],
            "rejected_iteration_rules": item.get("rejected_iteration_rules") or [],
            "feature_counts": item.get("feature_counts") or {},
            "last_sticker_at": _as_float(item.get("last_sticker_at")),
            "target_reply_chars": target_chars,
            "preferred_parts": preferred_parts,
            "topic_words": topic_words,
            "structured_memory": structured_memory,
            "affection_score": affection_score,
            "affection_state": _affection_state_text(affection_score),
            "group_activity_score": group_activity_score,
            "group_activity_state": _group_activity_state_text(group_activity_score),
            "personal_question_interval": _personal_question_interval(affection_score),
            "prompt_hint": f"{length_style}{pace_style}{emoji_style}{''.join(adaptation_styles)}",
        }

    def recall_context(
        self,
        conversation_id: str,
        user_text: str,
        now: float | None = None,
    ) -> str:
        profile = self.profile(conversation_id, now=now)
        return _format_recall_context(profile, user_text)

    def affection_summary(self, conversation_id: str, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        return _affection_summary_text(float(item.get("affection_score", DEFAULT_AFFECTION)))

    def set_affection(self, conversation_id: str, value: float, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        item["affection_score"] = _clamp(value)
        self._save()
        return _affection_set_text(float(item["affection_score"]))

    def reset_affection(self, conversation_id: str, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        item["affection_initialized"] = False
        _initialize_affection(item, is_owner, force=True)
        self._save()
        return _affection_reset_text(float(item["affection_score"]))

    def due_idle_targets(
        self,
        idle_minutes: int,
        cooldown_minutes: int,
        now: float | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        now = now or time.time()
        due: list[tuple[str, dict[str, Any]]] = []
        idle_seconds = idle_minutes * 60
        cooldown_seconds = cooldown_minutes * 60

        for conversation_id, item in self._data.get("conversations", {}).items():
            target = item.get("target") or {}
            if target.get("message_type") != "private" or not target.get("user_id"):
                continue

            if _decay_private_affection_for_idle(item, now):
                self._save()
            multiplier = _private_nudge_multiplier(
                float(item.get("affection_score", DEFAULT_AFFECTION))
            )
            if multiplier is None:
                continue

            last_user_at = _as_float(item.get("last_user_at"))
            if not last_user_at:
                continue

            last_active = max(last_user_at, _as_float(item.get("last_bot_at")) or 0.0)
            last_nudge = _as_float(item.get("last_idle_nudge_at"))
            adjusted_idle_seconds = idle_seconds * multiplier
            adjusted_cooldown_seconds = cooldown_seconds * multiplier
            nudge_ready = (
                last_nudge is None or now - last_nudge >= adjusted_cooldown_seconds
            )
            if now - last_active >= adjusted_idle_seconds and nudge_ready:
                due.append((conversation_id, target))

        return due

    def due_group_targets(
        self,
        idle_minutes: int,
        cooldown_minutes: int,
        daily_limit: int,
        max_silence_days: int | None = None,
        now: float | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        now = now or time.time()
        due: list[tuple[str, dict[str, Any]]] = []
        idle_seconds = idle_minutes * 60
        cooldown_seconds = cooldown_minutes * 60
        silence_seconds = None
        if max_silence_days is not None:
            max_silence_days = max(0, int(max_silence_days))
            if max_silence_days > 0:
                silence_seconds = max_silence_days * 24 * 60 * 60
        today = datetime.fromtimestamp(now).date().isoformat()
        daily_limit = min(3, max(0, int(daily_limit)))
        if daily_limit <= 0:
            return []

        for conversation_id, item in self._data.get("conversations", {}).items():
            if not conversation_id.startswith("group:") or ":user:" in conversation_id:
                continue
            target = item.get("target") or {}
            if target.get("message_type") != "group" or not target.get("group_id"):
                continue

            last_user_at = _as_float(item.get("last_user_at"))
            if not last_user_at:
                continue
            if silence_seconds is not None and now - last_user_at > silence_seconds:
                continue
            last_active = max(last_user_at, _as_float(item.get("last_bot_at")) or 0.0)
            last_group_nudge = _as_float(item.get("last_group_proactive_at"))
            cooldown_ready = (
                last_group_nudge is None or now - last_group_nudge >= cooldown_seconds
            )
            daily_counts = item.get("group_proactive_daily_counts") or {}
            today_count = int(daily_counts.get(today, 0))
            if (
                now - last_active >= idle_seconds
                and cooldown_ready
                and today_count < daily_limit
            ):
                due.append((conversation_id, target))

        return due

    def mark_group_proactive(self, conversation_id: str, now: float | None = None) -> None:
        now = now or time.time()
        today = datetime.fromtimestamp(now).date().isoformat()
        item = self._conversation(conversation_id)
        counts = dict(item.get("group_proactive_daily_counts") or {})
        counts = {day: count for day, count in counts.items() if day >= today}
        counts[today] = int(counts.get(today, 0)) + 1
        item["group_proactive_daily_counts"] = counts
        item["last_group_proactive_at"] = now
        item["last_bot_at"] = now
        self._save()

    def mark_idle_nudged(self, conversation_id: str, now: float | None = None) -> None:
        item = self._conversation(conversation_id)
        item["last_idle_nudge_at"] = now or time.time()
        item["last_bot_at"] = item["last_idle_nudge_at"]
        self._save()

    def due_morning_targets(
        self,
        owner_qqs: Iterable[int],
        scheduled_time: str,
        catchup_minutes: int,
        timezone_name: str,
        now: datetime | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        timezone = safe_zoneinfo(timezone_name)
        now = now.astimezone(timezone) if now else datetime.now(timezone)
        hour, minute = parse_hhmm(scheduled_time)
        scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < scheduled_at:
            return []
        if now > scheduled_at + timedelta(minutes=max(0, catchup_minutes)):
            return []

        today = now.date().isoformat()
        due: list[tuple[str, dict[str, Any]]] = []
        for conversation_id, target in self._morning_candidate_targets(owner_qqs):
            item = self._conversation(conversation_id, save=False)
            if _decay_private_affection_for_idle(item, now.timestamp()):
                self._save()
            multiplier = _private_nudge_multiplier(
                float(item.get("affection_score", DEFAULT_AFFECTION))
            )
            if multiplier is None:
                continue
            if item.get("last_morning_greeting_date") == today:
                continue
            due.append((conversation_id, target))
        return due

    def mark_morning_greeted(
        self,
        conversation_id: str,
        timezone_name: str,
        now: datetime | None = None,
    ) -> None:
        timezone = safe_zoneinfo(timezone_name)
        now = now.astimezone(timezone) if now else datetime.now(timezone)
        item = self._conversation(conversation_id)
        item["last_morning_greeting_date"] = now.date().isoformat()
        item["last_bot_at"] = time.time()
        self._save()

    def _morning_candidate_targets(
        self, owner_qqs: Iterable[int]
    ) -> list[tuple[str, dict[str, Any]]]:
        owner_ids = [int(qq) for qq in owner_qqs if int(qq) > 0]
        if owner_ids:
            return [
                (f"private:{qq}", {"message_type": "private", "user_id": qq})
                for qq in owner_ids
            ]

        candidates: list[tuple[str, dict[str, Any]]] = []
        for conversation_id, item in self._data.get("conversations", {}).items():
            target = item.get("target") or {}
            if target.get("message_type") == "private" and target.get("user_id"):
                candidates.append((conversation_id, target))
        return candidates

    def _conversation(self, conversation_id: str, save: bool = True) -> dict[str, Any]:
        conversations = self._data.setdefault("conversations", {})
        if conversation_id not in conversations:
            conversations[conversation_id] = {}
            if save:
                self._save()
        return conversations[conversation_id]

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": MEMORY_VERSION, "conversations": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": MEMORY_VERSION, "conversations": {}}
        if not isinstance(data, dict):
            return {"version": MEMORY_VERSION, "conversations": {}}
        data["version"] = max(int(data.get("version", 1) or 1), MEMORY_VERSION)
        data.setdefault("conversations", {})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


_running_average = _memory_core._running_average
_as_float = _memory_core._as_float
_clamp = _memory_core._clamp
_is_group_conversation = _memory_core._is_group_conversation
_initialize_affection = _memory_core._initialize_affection
_contains_any = _memory_core._contains_any
_classify_affection_event = _memory_core._classify_affection_event
_update_affection = _memory_core._update_affection
_decay_private_affection_for_idle = _memory_core._decay_private_affection_for_idle
_private_nudge_multiplier = _memory_core._private_nudge_multiplier
_decay_group_activity = _memory_core._decay_group_activity
_is_unrelated_negative_group_message = _memory_core._is_unrelated_negative_group_message
_update_group_activity = _memory_core._update_group_activity
_emoji_count = _memory_core._emoji_count
_style_flags = _memory_core._style_flags
_message_features = _memory_core._message_features
_merge_feature_counts = _memory_core._merge_feature_counts
_append_iteration_rule = _memory_core._append_iteration_rule
_iteration_rule_text = _memory_core._iteration_rule_text
_append_history = _memory_core._append_history
_shorten = _memory_core._shorten
_extract_topics = _memory_core._extract_topics
_merge_topics = _memory_core._merge_topics
_safe_topics = _memory_core._safe_topics
_is_safe_topic = _memory_core._is_safe_topic
is_memory_pollution_text = _memory_core.is_memory_pollution_text
_ensure_structured_memory = _memory_core._ensure_structured_memory
_append_session_l3 = _memory_core._append_session_l3
_remember_structured_from_user = _memory_core._remember_structured_from_user
_actionable_style_candidate = _memory_core._actionable_style_candidate
_style_rule_value = _memory_core._style_rule_value
_extract_l1_candidates = _memory_core._extract_l1_candidates
_extract_l2_events = _memory_core._extract_l2_events
_candidate = _memory_core._candidate
_upsert_l1_candidate = _memory_core._upsert_l1_candidate
_upsert_l2 = _memory_core._upsert_l2
_find_memory = _memory_core._find_memory
_append_source = _memory_core._append_source
_memory_id = _memory_core._memory_id
_link_related_memories = _memory_core._link_related_memories
_apply_user_corrections = _memory_core._apply_user_corrections
_decay_event_memories = _memory_core._decay_event_memories
_structured_memory_profile = _memory_core._structured_memory_profile
_format_recall_context = _memory_core._format_recall_context
_natural_memory_line = _memory_core._natural_memory_line
_natural_predicate = _memory_core._natural_predicate
_memory_relevant = _memory_core._memory_relevant
_personal_question_interval = _memory_core._personal_question_interval
_remember_important_interaction = _memory_core._remember_important_interaction
_important_interaction_key = _memory_core._important_interaction_key
_attach_affection_metadata = _memory_core._attach_affection_metadata
_affection_state_text = _memory_core._affection_state_text
_group_activity_state_text = _memory_core._group_activity_state_text
_affection_summary_text = _memory_core._affection_summary_text
_affection_set_text = _memory_core._affection_set_text
_affection_reset_text = _memory_core._affection_reset_text
_event_key = _memory_core._event_key
_clean_value = _memory_core._clean_value
_valid_preference_value = _memory_core._valid_preference_value
_is_noisy_for_long_memory = _memory_core._is_noisy_for_long_memory
_is_negative_quality_complaint = _memory_core._is_negative_quality_complaint

