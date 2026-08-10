from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .memory_parts import core as _memory_core
from .memory_parts.ingestion import (
    MemoryExtractionRequest,
    MemoryExtractionResult,
    MemoryExtractionWorker,
    deterministic_operations as _memory_core_deterministic_operations,
)
from .retrieval import ContextRetrievalPlanner, RetrievalSettings

from .proactive import parse_hhmm, safe_zoneinfo


LOGGER = logging.getLogger("atri.memory")

# 记忆保存发生在消息处理链路中，不能因为一次内存不足就让整条回复任务失败。
# 失败后采用短暂退避，避免在系统内存紧张时每条消息都重复创建序列化缓冲区。
SAVE_RETRY_MIN_SECONDS = 5.0
SAVE_RETRY_MAX_SECONDS = 60.0
MAX_MEMORY_TEXT_CHARS = 2000
MEMORY_BACKFILL_VERSION = 1


def _locked_mutation(method):
    """为主消息写入与后台整合共用一把进程内可重入锁。"""
    def wrapped(self, *args, **kwargs):
        with self._memory_state_lock:
            return method(self, *args, **kwargs)
    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped


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
    def __init__(self, path: Path, config: Any | None = None) -> None:
        self.path = path
        self._loaded_file_state: tuple[int, int] | None = None
        self._data = self._load()
        self._loaded_file_state = self._current_file_state()
        self._session_l3: dict[str, list[dict[str, Any]]] = {}
        self._save_retry_after = 0.0
        self._save_failure_count = 0
        self._memory_state_lock = threading.RLock()
        # 检索器是可选的旁路；即使 SQLite 文件损坏，原 JSON 记忆仍能正常工作。
        self._retrieval = ContextRetrievalPlanner(
            RetrievalSettings.from_config(path, config)
        )
        self._memory_worker = MemoryExtractionWorker(
            self._apply_extraction_result,
            enabled=bool(getattr(config, "memory_extraction_enabled", True)),
            # 直接创建 UserMemoryStore（测试、迁移脚本、离线修复）默认不应
            # 意外拉起本地大模型；正式运行由 load_config 明确打开此开关。
            llm_enabled=bool(getattr(config, "memory_extraction_llm_enabled", False)),
            model=str(getattr(config, "memory_extraction_model", "qwen3:4b-instruct")),
            base_url=str(getattr(config, "memory_extraction_base_url", "http://127.0.0.1:11434")),
            api_key=getattr(config, "memory_extraction_api_key", None),
            timeout_seconds=float(getattr(config, "memory_extraction_timeout_seconds", 10.0)),
            cooldown_seconds=float(getattr(config, "memory_extraction_cooldown_seconds", 45.0)),
        )
        self._backfill_thread: threading.Thread | None = None
        self._memory_backfill_max_conversations = int(
            getattr(config, "memory_backfill_max_conversations", 250) or 250
        )
        if bool(getattr(config, "memory_backfill_enabled", False)):
            self._backfill_thread = threading.Thread(
                target=self._backfill_history_profiles,
                name="atri-memory-backfill",
                daemon=True,
            )
            self._backfill_thread.start()

    @_locked_mutation
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
        visibility: str = "private",
        source_context: str | None = None,
    ) -> None:
        # 记忆只需要保存可检索的摘要文本；超长媒体描述、转发内容或异常 payload
        # 不应原样进入持久化树，避免单条消息放大整个快照。
        text = _shorten(str(text or ""), MAX_MEMORY_TEXT_CHARS)
        if is_memory_pollution_text(text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        memory = _ensure_structured_memory(item)
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
        item.pop("next_proactive_at", None)
        item.pop("next_proactive_event_type", None)
        item["proactive_awaiting_reply"] = False
        item["proactive_ignored_streak"] = 0
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
        _append_session_l3(self._session_l3, conversation_id, text, now, memory)
        affection_event = _classify_affection_event(text)
        if update_affection:
            _update_affection(item, affection_event, is_owner, now=now)
        _remember_structured_from_user(
            item,
            text,
            now,
            affection_event,
            visibility=visibility,
            source_context=source_context,
        )
        self._enqueue_memory_extraction(
            conversation_id,
            text,
            now,
            visibility=visibility,
            source_context=source_context,
            scope_kind="group" if _is_group_conversation(conversation_id) and ":user:" not in conversation_id else "person",
        )
        if not _is_group_conversation(conversation_id):
            _remember_personal_event(item, text, now)
        self._save()

    @_locked_mutation
    def observe_bot(
        self,
        conversation_id: str,
        reply_text: str,
        sent_sticker: bool = False,
        now: float | None = None,
    ) -> None:
        reply_text = _shorten(str(reply_text or ""), MAX_MEMORY_TEXT_CHARS)
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

    @_locked_mutation
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

    @_locked_mutation
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
            visibility=f"group:{group_id}",
            source_context=f"group:{group_id}",
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
            visibility=f"group:{group_id}",
            source_context=f"group:{group_id}",
        )
        self.remember_person_profile_from_group(
            group_id,
            user_id,
            text,
            now=now,
            is_owner=is_owner,
        )
        if addressed_to_bot:
            self.observe_affection_event(
                f"private:{user_id}",
                text,
                now=now,
                is_owner=is_owner,
            )
        return group_conversation_id, member_conversation_id

    @_locked_mutation
    def remember_person_profile_from_group(
        self,
        group_id: int | str,
        user_id: int | str,
        text: str,
        now: float | None = None,
        is_owner: bool = False,
    ) -> None:
        if is_memory_pollution_text(text):
            return
        now = now or time.time()
        item = self._conversation(f"private:{user_id}")
        _ensure_structured_memory(item)
        memory = _ensure_structured_memory(item)
        _append_session_l3(
            self._session_l3,
            f"private:{user_id}",
            text,
            now,
            memory,
        )
        _initialize_affection(item, is_owner)
        affection_event = _classify_affection_event(text)
        _remember_structured_from_user(
            item,
            text,
            now,
            affection_event,
            visibility=f"group:{group_id}",
            source_context=f"group:{group_id}",
        )
        self._enqueue_memory_extraction(
            f"private:{user_id}",
            text,
            now,
            visibility=f"group:{group_id}",
            source_context=f"group:{group_id}",
            scope_kind="person",
        )
        self._save()

    @_locked_mutation
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
        _update_affection(item, affection_event, is_owner, now=now)
        _remember_important_interaction(item, text, now, affection_event)
        self._save()

    @_locked_mutation
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
        item = self._profile_item(conversation_id)
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
        if accepted_rules:
            adaptation_styles.append(
                f"已采纳长期对话规则：{'；'.join(accepted_rules)}。这些规则要优先执行。"
            )
        last_iteration = item.get("last_iteration_decision")
        last_iteration_at = (
            _as_float(last_iteration.get("at"))
            if isinstance(last_iteration, dict)
            else None
        )
        if (
            isinstance(last_iteration, dict)
            and last_iteration_at is not None
            and now - last_iteration_at <= 30 * 60
        ):
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
            self._session_l3.get(conversation_id)
            or (item.get("structured_memory") or {}).get("l3")
            or [],
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

    def _profile_item(self, conversation_id: str) -> dict[str, Any]:
        item = self._conversation(conversation_id, save=False)
        member = _group_member_identity(conversation_id)
        if not member:
            return item

        group_id, user_id = member
        canonical = self._data.get("conversations", {}).get(f"private:{user_id}")
        if not isinstance(canonical, dict):
            return item

        merged = dict(item)
        merged["structured_memory"] = _merge_group_safe_structured_memory(
            item,
            canonical,
            f"group:{group_id}",
        )
        return merged

    def recall_context(
        self,
        conversation_id: str,
        user_text: str,
        now: float | None = None,
    ) -> str:
        profile = self.profile(conversation_id, now=now)
        try:
            context = self._retrieval.build(profile, user_text)
            if context:
                return context
        except Exception as exc:  # 检索索引是增强项，绝不能让它阻断 QQ 回复。
            LOGGER.warning("semantic retrieval fallback: %s", exc)
        return _format_recall_context(profile, user_text)

    def retrieval_status(self) -> dict[str, Any]:
        """为 WebUI/诊断提供索引状态，不暴露任何跨会话的记忆内容。"""

        return self._retrieval.status()

    def update_retrieval_config(self, config: Any) -> None:
        """WebUI 热加载配置后重建轻量 Planner，不触碰 JSON 和记忆会话。"""

        self._retrieval = ContextRetrievalPlanner(
            RetrievalSettings.from_config(self.path, config)
        )

    def affection_summary(self, conversation_id: str, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        return _affection_summary_text(float(item.get("affection_score", DEFAULT_AFFECTION)))

    def trust_tier(self, conversation_id: str) -> str:
        item = self._conversation(conversation_id, save=False)
        member = _group_member_identity(conversation_id)
        if member:
            canonical = self._data.get("conversations", {}).get(f"private:{member[1]}")
            if isinstance(canonical, dict):
                item = canonical
        return _trust_tier(item.get("trust_tier"))

    def set_trust_tier(self, conversation_id: str, value: str) -> str:
        item = self._conversation(conversation_id)
        item["trust_tier"] = _trust_tier(value)
        self._save()
        return item["trust_tier"]

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
        self._reload_if_changed()
        now = now or time.time()
        due: list[tuple[str, dict[str, Any]]] = []
        idle_seconds = idle_minutes * 60
        cooldown_seconds = cooldown_minutes * 60

        for conversation_id, item in self._data.get("conversations", {}).items():
            target = item.get("target") or {}
            if target.get("message_type") != "private" or not target.get("user_id"):
                continue
            override = _proactive_override(item.get("proactive_override"))
            if override == "deny":
                continue

            if _decay_private_affection_for_idle(item, now):
                self._save()
            multiplier = _private_nudge_multiplier(
                float(item.get("affection_score", DEFAULT_AFFECTION))
            )
            if multiplier is None and override == "allow":
                multiplier = PRIVATE_NUDGE_NORMAL_MULTIPLIER
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
        self._reload_if_changed()
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
            if _proactive_override(item.get("proactive_override")) == "deny":
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

    def proactive_candidates(
        self,
        owner_qqs: Iterable[int],
        owner_only: bool,
        include_groups: bool = False,
    ) -> list[tuple[str, dict[str, Any]]]:
        self._reload_if_changed()
        owner_ids = [int(value) for value in owner_qqs if int(value) > 0]
        candidates: dict[int, tuple[str, dict[str, Any]]] = {
            user_id: (
                f"private:{user_id}",
                {"message_type": "private", "user_id": user_id},
            )
            for user_id in owner_ids
        }
        if not owner_only:
            for conversation_id, item in self._data.get("conversations", {}).items():
                target = item.get("target") or {}
                if target.get("message_type") != "private" or not target.get("user_id"):
                    continue
                user_id = int(target["user_id"])
                candidates[user_id] = (conversation_id, dict(target))

        groups: list[tuple[str, dict[str, Any]]] = []
        if include_groups:
            for conversation_id, item in self._data.get("conversations", {}).items():
                if not conversation_id.startswith("group:") or ":user:" in conversation_id:
                    continue
                target = item.get("target") or {}
                if target.get("message_type") == "group" and target.get("group_id"):
                    groups.append((conversation_id, dict(target)))
        return list(candidates.values()) + groups

    def due_personal_events(
        self,
        owner_qqs: Iterable[int],
        now: float | None = None,
    ) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
        self._reload_if_changed()
        now = now or time.time()
        owner_ids = {int(value) for value in owner_qqs if int(value) > 0}
        due: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for conversation_id, item in self._data.get("conversations", {}).items():
            if not conversation_id.startswith("private:") or not isinstance(item, dict):
                continue
            target = item.get("target") or {}
            user_id = int(target.get("user_id") or conversation_id.split(":", 1)[1] or 0)
            if user_id not in owner_ids and _trust_tier(item.get("trust_tier")) not in {"approved", "trusted"}:
                continue
            for event in item.get("personal_events") or []:
                if not isinstance(event, dict) or event.get("status") != "scheduled":
                    continue
                due_at = _as_float(event.get("due_at")) or 0.0
                if due_at <= now <= due_at + 12 * 60 * 60:
                    due.append((conversation_id, {"message_type": "private", "user_id": user_id}, dict(event)))
        return due

    def mark_personal_event_sent(
        self,
        conversation_id: str,
        event_id: str,
        now: float | None = None,
    ) -> None:
        item = self._conversation(conversation_id)
        for event in item.get("personal_events") or []:
            if isinstance(event, dict) and str(event.get("id") or "") == str(event_id):
                event["status"] = "sent"
                event["sent_at"] = now or time.time()
                self._save()
                return

    def proactive_state(
        self,
        conversation_id: str,
        is_owner: bool = False,
        now: float | None = None,
    ) -> dict[str, Any]:
        now = now or time.time()
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        is_group = conversation_id.startswith("group:") and ":user:" not in conversation_id
        changed = False
        if is_group:
            before_activity = item.get("group_activity_score")
            _decay_group_activity(item, now)
            changed = item.get("group_activity_score") != before_activity
        else:
            before_affection = item.get("affection_score")
            _initialize_affection(item, is_owner)
            changed = _decay_private_affection_for_idle(item, now)
            changed = changed or item.get("affection_score") != before_affection
        if changed:
            self._save()
        return {
            "affection_score": float(item.get("affection_score", DEFAULT_AFFECTION)),
            "group_activity_score": float(item.get("group_activity_score", GROUP_ACTIVITY_DEFAULT)),
            "message_count": int(item.get("message_count", 0)),
            "last_user_at": _as_float(item.get("last_user_at")),
            "last_bot_at": _as_float(item.get("last_bot_at")),
            "message_type": "group" if is_group else "private",
            "next_at": _as_float(item.get("next_proactive_at")),
            "next_event_type": item.get("next_proactive_event_type"),
            "last_at": _as_float(item.get("last_proactive_at")),
            "last_event_type": item.get("last_proactive_event_type"),
            "last_source": item.get("last_proactive_source"),
            "daily_date": item.get("proactive_daily_date"),
            "daily_count": int(item.get("proactive_daily_count", 0)),
            "ignored_streak": int(item.get("proactive_ignored_streak", 0)),
            "awaiting_reply": bool(item.get("proactive_awaiting_reply", False)),
            "event_dates": dict(item.get("proactive_event_dates") or {}),
            "recent_messages": list(item.get("recent_proactive_messages") or [])[-8:],
            "proactive_override": _proactive_override(item.get("proactive_override")),
            "trust_tier": _trust_tier(item.get("trust_tier")),
        }

    def set_proactive_plan(
        self,
        conversation_id: str,
        scheduled_at: float,
        event_type: str,
    ) -> None:
        item = self._conversation(conversation_id)
        item["next_proactive_at"] = float(scheduled_at)
        item["next_proactive_event_type"] = str(event_type)
        self._save()

    def clear_proactive_plan(self, conversation_id: str) -> None:
        item = self._conversation(conversation_id)
        changed = False
        for key in ("next_proactive_at", "next_proactive_event_type"):
            if key in item:
                item.pop(key, None)
                changed = True
        if changed:
            self._save()

    def note_proactive_unanswered(self, conversation_id: str) -> int:
        item = self._conversation(conversation_id)
        if item.get("proactive_awaiting_reply"):
            item["proactive_ignored_streak"] = min(
                8,
                int(item.get("proactive_ignored_streak", 0)) + 1,
            )
            item["proactive_awaiting_reply"] = False
            self._save()
        return int(item.get("proactive_ignored_streak", 0))

    def mark_proactive_sent(
        self,
        conversation_id: str,
        event_type: str,
        text: str,
        source: str,
        local_date: str,
        now: float | None = None,
    ) -> None:
        sent_at = now or time.time()
        item = self._conversation(conversation_id)
        count = int(item.get("proactive_daily_count", 0))
        if item.get("proactive_daily_date") != local_date:
            count = 0
        item["proactive_daily_date"] = local_date
        item["proactive_daily_count"] = count + 1
        item["last_proactive_at"] = sent_at
        item["last_proactive_event_type"] = str(event_type)
        item["last_proactive_source"] = str(source)
        item["proactive_awaiting_reply"] = True
        item["last_bot_at"] = sent_at
        item.pop("next_proactive_at", None)
        item.pop("next_proactive_event_type", None)
        dates = dict(item.get("proactive_event_dates") or {})
        dates[str(event_type)] = local_date
        item["proactive_event_dates"] = dates
        recent = list(item.get("recent_proactive_messages") or [])
        recent.append({"at": sent_at, "event_type": str(event_type), "text": str(text)[:240], "source": str(source)})
        item["recent_proactive_messages"] = recent[-8:]
        self._save()

    def due_morning_targets(
        self,
        owner_qqs: Iterable[int],
        scheduled_time: str,
        catchup_minutes: int,
        timezone_name: str,
        now: datetime | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        self._reload_if_changed()
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

    def _enqueue_memory_extraction(
        self,
        conversation_id: str,
        text: str,
        now: float,
        *,
        visibility: str,
        source_context: str | None,
        scope_kind: str,
    ) -> None:
        """把画像提取放入有界后台队列。

        这里故意只做快照和入队，不调用模型、不等待结果；消息主链路在此之后
        继续完成原有保存和回复。后台回写前会重新加载磁盘状态，避免覆盖 WebUI
        或另一条消息刚刚写入的内容。
        """
        if not self._memory_worker.enabled:
            return
        item = self._conversation(conversation_id, save=False)
        structured = _ensure_structured_memory(item)
        known_memory = tuple(
            f"{entry.get('key')}: {entry.get('value')}"
            for bucket in ("l1", "l2")
            for entry in list(structured.get(bucket) or [])[-12:]
            if isinstance(entry, dict)
            and entry.get("state") not in {"expired", "deleted", "rejected"}
        )
        history = list(item.get("history") or [])
        recent_context = tuple(
            f"{entry.get('role') or 'user'}: {entry.get('text') or ''}"
            for entry in history[-12:]
            if isinstance(entry, dict) and str(entry.get("text") or "").strip()
        )
        request = MemoryExtractionRequest(
            conversation_id=conversation_id,
            subject_id=conversation_id,
            text=text,
            recent_context=recent_context,
            known_memory=known_memory,
            now=now,
            visibility=visibility,
            source_context=source_context,
            scope_kind=scope_kind,
        )
        if self._memory_worker.submit(request):
            LOGGER.debug("记忆提取任务已入队 conversation=%s scope=%s", conversation_id, scope_kind)

    @_locked_mutation
    def _apply_extraction_result(self, result: MemoryExtractionResult) -> None:
        """在主进程内合并后台结果；失败只记日志，不影响下一条消息。"""
        request = result.request
        file_state_before = self._current_file_state()
        item = self._conversation(request.conversation_id, save=False)
        memory = _ensure_structured_memory(item)
        # WebUI 手工编辑优先级高于已经在队列里的旧消息。否则用户刚删除的
        # 记忆可能被旧任务重新写回，表现为“保存后又恢复”。新消息的时间戳
        # 晚于编辑时间时仍可正常进入提取流程。
        manual_edit_at = _as_float(item.get("memory_manual_edit_at")) or 0.0
        if manual_edit_at and request.now < manual_edit_at:
            LOGGER.debug(
                "跳过早于 WebUI 编辑的后台画像结果 conversation=%s",
                request.conversation_id,
            )
            return
        # WebUI 是独立 HTTP 服务，和本进程不共享 Python 锁。若后台读取快照
        # 后文件已经被 WebUI/人工流程改过，宁可丢弃这一批旧结果，也不能把
        # 旧画像覆盖回去；下一条真实消息会重新排队提取。
        if self._current_file_state() != file_state_before:
            self._reload_if_changed()
            return
        memory_ids: list[str] = []
        for operation in result.operations:
            # core 的操作入口接收 conversation item，并在内部取出
            # item["structured_memory"]；不能把已经取出的 memory 再传进去，
            # 否则会意外生成 structured_memory.structured_memory 嵌套树。
            memory_id = _memory_core.apply_extraction_operation(item, operation, request.now)
            if memory_id:
                memory_ids.append(str(memory_id))
        memory = _ensure_structured_memory(item)
        _memory_core._link_related_memories(memory, memory_ids)
        if memory_ids:
            if self._current_file_state() != file_state_before:
                self._reload_if_changed()
                LOGGER.debug(
                    "检测到外部记忆编辑，放弃旧后台画像结果 conversation=%s",
                    request.conversation_id,
                )
                return
            self._save()
            LOGGER.info(
                "后台画像提取完成 conversation=%s operations=%d model=%s",
                request.conversation_id,
                len(memory_ids),
                result.model_used,
            )
        if result.error:
            LOGGER.debug(
                "后台画像模型不可用，已保留规则提取结果 conversation=%s error=%s",
                request.conversation_id,
                result.error,
            )

    def memory_extraction_status(self) -> dict[str, Any]:
        """返回后台画像提取状态；仅用于 WebUI/诊断，不改变记忆。"""
        status = self._memory_worker.status()
        status["backfill_running"] = bool(self._backfill_thread and self._backfill_thread.is_alive())
        return status

    def _backfill_history_profiles(self) -> None:
        """低优先级回放旧 history，补齐升级前没有结构化画像的用户。

        只调用确定性提取器，不在启动时批量加载大模型；模型增强由真实新消息
        通过有界队列完成。每个会话单独持锁和保存，主回复最多只等待一次很短
        的锁竞争，异常会被吞掉并记录，绝不影响服务启动。
        """
        try:
            limit = self._memory_backfill_max_conversations
        except (TypeError, ValueError):
            limit = 250
        conversations = list(self._data.get("conversations", {}).items())[: max(10, min(limit, 500))]
        for conversation_id, original_item in conversations:
            try:
                history = list((original_item or {}).get("history") or [])
                if len(history) < 2:
                    continue
                with self._memory_state_lock:
                    item = self._conversation(conversation_id, save=False)
                    # 回填是一次性迁移；打标后重启不再重复扫描和写盘，避免启动抖动。
                    if int(item.get("memory_backfill_version", 0) or 0) >= MEMORY_BACKFILL_VERSION:
                        continue
                    memory = _ensure_structured_memory(item)
                    scope_kind = (
                        "group"
                        if conversation_id.startswith("group:") and ":user:" not in conversation_id
                        else "person"
                    )
                    visibility = (
                        conversation_id
                        if scope_kind == "group"
                        else "private"
                    )
                    changed = False
                    for entry in history[-300:]:
                        if not isinstance(entry, dict) or entry.get("role") != "user":
                            continue
                        text = _shorten(str(entry.get("text") or ""), MAX_MEMORY_TEXT_CHARS)
                        if not text or is_memory_pollution_text(text):
                            continue
                        operations = _memory_core_deterministic_operations(
                            text,
                            now=_as_float(entry.get("at")) or time.time(),
                            visibility=visibility,
                            source_context=visibility if scope_kind == "group" else None,
                            scope_kind=scope_kind,
                        )
                        for operation in operations:
                            if _memory_core.apply_extraction_operation(item, operation, operation.get("updated_at") or time.time()):
                                changed = True
                    item["memory_backfill_version"] = MEMORY_BACKFILL_VERSION
                    changed = True
                    if changed:
                        self._save()
                # 让出调度权，避免历史较多时与消息线程争用 CPU/磁盘。
                time.sleep(0.02)
            except Exception:
                LOGGER.exception("历史画像回放失败 conversation=%s", conversation_id)

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
        self._reload_if_changed()
        conversations = self._data.setdefault("conversations", {})
        if conversation_id not in conversations:
            conversations[conversation_id] = {}
            if save:
                self._save()
        return conversations[conversation_id]

    def _current_file_state(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _reload_if_changed(self) -> None:
        current_state = self._current_file_state()
        if current_state == self._loaded_file_state:
            return
        self._data = self._load()
        self._loaded_file_state = self._current_file_state()

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

    def _save(self) -> bool:
        """尽量持久化记忆，但绝不让持久化异常中断当前回复。

        旧实现先用 ``json.dumps`` 把整个记忆树拼成一个大字符串，再一次性写入
        临时文件。系统内存紧张时，这个额外的字符串缓冲区可能触发
        ``MemoryError``，异常会沿着消息处理链路冒泡，表现为“连接正常但不回复”。

        这里改为流式 ``json.dump`` 写临时文件，并对内存不足和文件 I/O 异常做
        有限退避。临时文件只有在完整写入后才替换正式文件，因此不会留下半截
        users.json；内存恢复后下一次保存会自动恢复。
        """
        now = time.monotonic()
        if now < self._save_retry_after:
            return False

        tmp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 直接向临时文件写入，避免额外创建完整 JSON 字符串。
            with tmp_path.open("w", encoding="utf-8") as stream:
                json.dump(self._data, stream, ensure_ascii=False, indent=2)
                stream.flush()
            for attempt in range(4):
                try:
                    tmp_path.replace(self.path)
                    break
                except PermissionError:
                    if attempt >= 3:
                        raise
                    time.sleep(0.025 * (attempt + 1))
        except MemoryError:
            self._save_failure_count += 1
            delay = min(
                SAVE_RETRY_MAX_SECONDS,
                SAVE_RETRY_MIN_SECONDS * (2 ** min(self._save_failure_count - 1, 4)),
            )
            self._save_retry_after = now + delay
            LOGGER.warning(
                "记忆保存暂缓：系统内存不足，当前回复继续执行；将在 %.1f 秒后重试",
                delay,
            )
            return False
        except (OSError, TypeError, ValueError) as exc:
            self._save_failure_count += 1
            delay = min(
                SAVE_RETRY_MAX_SECONDS,
                SAVE_RETRY_MIN_SECONDS * (2 ** min(self._save_failure_count - 1, 4)),
            )
            self._save_retry_after = now + delay
            LOGGER.warning(
                "记忆保存暂缓：文件写入失败（%s），当前回复继续执行；将在 %.1f 秒后重试",
                exc,
                delay,
            )
            return False
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        self._loaded_file_state = self._current_file_state()
        self._save_failure_count = 0
        self._save_retry_after = 0.0
        return True


def _group_member_identity(conversation_id: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"group:([^:]+):user:([^:]+)", str(conversation_id or ""))
    if not match:
        return None
    return match.group(1), match.group(2)


def _merge_group_safe_structured_memory(
    member_item: dict[str, Any],
    canonical_item: dict[str, Any],
    group_scope: str,
) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {"l1": [], "l2": [], "l3": [], "candidates": []}
    member_memory = _ensure_structured_memory(member_item)
    canonical_memory = _ensure_structured_memory(canonical_item)
    for bucket in ("l1", "l2", "candidates"):
        seen: set[str] = set()
        for entry in canonical_memory.get(bucket, []):
            if not isinstance(entry, dict) or not _entry_visible_in_group(entry, group_scope):
                continue
            key = str(entry.get("memory_key") or entry.get("id") or id(entry))
            if key not in seen:
                merged[bucket].append(dict(entry))
                seen.add(key)
        for entry in member_memory.get(bucket, []):
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("memory_key") or entry.get("id") or id(entry))
            if key not in seen:
                merged[bucket].append(dict(entry))
                seen.add(key)
    # 群成员会话的 L3 只给当前成员详情使用，不能把别人的原始对话混进来。
    # 群总览的 L3 仍由 group:<id> 自己维护。
    merged["l3"] = [
        dict(entry)
        for entry in list(member_memory.get("l3") or [])[-8:]
        if isinstance(entry, dict)
    ]
    return merged


def _entry_visible_in_group(entry: dict[str, Any], group_scope: str) -> bool:
    visibility = entry.get("visibility")
    if visibility == "public" or visibility == group_scope:
        return True
    if isinstance(visibility, list) and (
        "public" in visibility or group_scope in visibility
    ):
        return True
    return False


def _proactive_override(value: Any) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in {"auto", "allow", "deny"} else "auto"


def _trust_tier(value: Any) -> str:
    normalized = str(value or "probation").strip().lower()
    return normalized if normalized in {"probation", "approved", "trusted", "blocked"} else "probation"


_PERSONAL_EVENT_HINTS = (
    "生日", "考试", "面试", "答辩", "开会", "会议", "截止", "ddl", "DDL",
    "报名", "航班", "飞机", "火车", "旅行", "纪念日",
)


def _remember_personal_event(item: dict[str, Any], text: str, now: float) -> None:
    source = str(text or "").strip()
    if not source or not any(hint in source for hint in _PERSONAL_EVENT_HINTS):
        return
    local_now = datetime.fromtimestamp(now, safe_zoneinfo("Asia/Shanghai"))
    event_date = None
    if "大后天" in source:
        event_date = (local_now + timedelta(days=3)).date()
    elif "后天" in source:
        event_date = (local_now + timedelta(days=2)).date()
    elif "明天" in source:
        event_date = (local_now + timedelta(days=1)).date()
    elif "今天" in source or "今晚" in source:
        event_date = local_now.date()
    else:
        match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?", source)
        if match:
            year = int(match.group(1) or local_now.year)
            try:
                event_date = datetime(year, int(match.group(2)), int(match.group(3))).date()
            except ValueError:
                return
            if not match.group(1) and event_date < local_now.date():
                event_date = event_date.replace(year=event_date.year + 1)
    if event_date is None:
        return

    hour, minute = 9, 0
    time_match = re.search(r"(\d{1,2})[点:：](?:(\d{1,2})分?)?", source)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        if "下午" in source and hour < 12:
            hour += 12
        if "晚上" in source and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            return
    due = datetime.combine(event_date, datetime.min.time(), tzinfo=local_now.tzinfo).replace(
        hour=hour,
        minute=minute,
    )
    event_id = f"{event_date.isoformat()}:{hour:02d}{minute:02d}:{next(h for h in _PERSONAL_EVENT_HINTS if h in source).lower()}"
    events = [event for event in (item.get("personal_events") or []) if isinstance(event, dict)]
    if any(str(event.get("id") or "") == event_id for event in events):
        return
    events.append({
        "id": event_id,
        "title": source[:120],
        "kind": "birthday" if "生日" in source else "important_event",
        "due_at": due.timestamp(),
        "created_at": now,
        "status": "scheduled",
        "visibility": "private",
    })
    item["personal_events"] = events[-20:]


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

