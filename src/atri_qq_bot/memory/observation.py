from __future__ import annotations

from . import _locked_mutation
from .support import MemoryMixin


class MemoryObservationMixin(MemoryMixin):
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
