from __future__ import annotations

from .support import MemoryMixin


class MemoryProactiveMixin(MemoryMixin):
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
