from __future__ import annotations

from atri_shared.reply_trace import fail_current

from .server_support import OneBotServerMixin, _sync_server_globals


class OneBotProactiveMixin(OneBotServerMixin):
    async def idle_nudge_loop(self) -> None:
        while True:
            await asyncio.sleep(max(10, int(self.config.idle_check_seconds)))
            if getattr(self, 'proactive_owner', 'core') == 'astrbot':
                continue
            if getattr(self.config, "proactive_v2_enabled", False):
                continue
            if not self.config.idle_proactive_enabled:
                continue

            websocket = self._first_active_websocket()
            if websocket is None:
                continue

            for conversation_id, target in self.reply_engine.due_idle_targets():
                user_id = target.get("user_id")
                if not user_id:
                    continue
                text = self.reply_engine.idle_nudge_text(conversation_id)
                try:
                    await asyncio.sleep(_first_reply_delay(self.config, text))
                    await self.call_action(
                        websocket,
                        "send_private_msg",
                        {"user_id": user_id, "message": text},
                    )
                    self.reply_engine.mark_idle_nudged(conversation_id)
                except Exception as exc:
                    print(f"[onebot] Idle nudge skipped because send failed: {exc}")
                    break

    async def morning_greeting_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            if getattr(self, 'proactive_owner', 'core') == 'astrbot':
                continue
            if getattr(self.config, "proactive_v2_enabled", False):
                continue
            if not self.config.morning_greeting_enabled:
                continue

            websocket = self._first_active_websocket()
            if websocket is None:
                continue

            try:
                due_targets = self.reply_engine.due_morning_targets()
            except Exception as exc:
                print(f"[onebot] Morning greeting scheduler skipped: {exc}")
                continue

            for conversation_id, target in due_targets:
                user_id = target.get("user_id")
                if not user_id:
                    continue
                text = self.reply_engine.morning_greeting_text()
                try:
                    await asyncio.sleep(_first_reply_delay(self.config, text))
                    await self.call_action(
                        websocket,
                        "send_private_msg",
                        {"user_id": user_id, "message": text},
                    )
                    self.reply_engine.mark_morning_greeted(conversation_id)
                    print(f"[onebot] Morning greeting sent to {user_id}.")
                except Exception as exc:
                    print(f"[onebot] Morning greeting send failed: {exc}")
                    break

    async def proactive_v2_loop(self) -> None:
        while True:
            policy = load_proactive_policy()
            await asyncio.sleep(max(15, int(policy.get("check_seconds", 60))))
            if not getattr(self.config, "proactive_v2_enabled", False):
                continue
            if not policy.get("enabled", True):
                continue

            websocket = self._first_active_websocket()
            if websocket is None:
                continue
            try:
                due_events = self.reply_engine.memory.due_personal_events(
                    getattr(self.config, "owner_qqs", ()),
                )
            except Exception as exc:
                print(f"[onebot] Personal event scheduler skipped: {exc}")
                due_events = []
            for conversation_id, target, personal_event in due_events:
                try:
                    text = _personal_event_message(personal_event)
                    await asyncio.sleep(_first_reply_delay(self.config, text))
                    await self.call_action(
                        websocket,
                        "send_private_msg",
                        {"user_id": target["user_id"], "message": text},
                    )
                    self.reply_engine.memory.mark_personal_event_sent(
                        conversation_id,
                        str(personal_event.get("id") or ""),
                    )
                    self.reply_engine.record_bot_reply(conversation_id, text)
                    print(f"[onebot] Personal event reminder sent to {target['user_id']}.")
                except Exception as exc:
                    print(f"[onebot] Personal event reminder failed: {exc}")
            # Explicit personal-event reminders remain owned by the core;
            # only automatic conversation starters transfer to the plugin.
            if getattr(self, 'proactive_owner', 'core') == 'astrbot':
                continue
            try:
                await self._evaluate_proactive_opportunity(websocket, policy)
            except Exception as exc:
                LOGGER.warning("[proactive] scheduler failed: %s", type(exc).__name__)

    async def _proactive_contact_scope(self, websocket, refresh=False):
        contacts = await self.fetch_contact_directory(websocket, refresh=refresh)
        return {f"private:{item['user_id']}" for item in contacts['users']} | {
            f"group:{item['group_id']}" for item in contacts['groups']}

    async def fetch_contact_directory(self, websocket=None, *, refresh=False):
        """共享只读联系人快照：目录展示与主动发送使用同一账号校验。"""
        if websocket is None:
            websocket = self._first_active_websocket()
        if websocket is None:
            raise RuntimeError("QQ 未连接，无法核实当前好友和群聊")
        binding = int(self.config.bot_qq or 0)
        login = await self.call_action_and_wait(websocket, "get_login_info", {}, timeout_seconds=5)
        if not self._proactive_action_ok(login) or int((login.get("data") or {}).get("user_id") or 0) != binding or not binding:
            raise RuntimeError("active account does not match binding")
        cache = getattr(self, '_contact_directory_cache', None)
        if not refresh and cache and cache[0] is websocket and cache[1] == binding and time.time() - cache[2] < 300:
            return cache[3]
        # 两个独立只读请求并行，断线时不让 WebUI 累积等待两个超时。
        replies = await asyncio.gather(*(self.call_action_and_wait(websocket, action, {}, timeout_seconds=5)
            for action in ("get_friend_list", "get_group_list")))
        contacts = {"state": "ready", "bot_qq": str(binding), "checked_at": time.time()}
        for reply, kind, key in zip(replies, ("users", "groups"), ("user_id", "group_id")):
            if not self._proactive_action_ok(reply) or not isinstance(reply.get("data"), list):
                raise RuntimeError("contact list unavailable")
            contacts[kind] = []
            for item in reply["data"]:
                identifier = int(item.get(key) or 0)
                if identifier > 0:
                    contacts[kind].append({key: str(identifier), **{name: str(item.get(name) or "")
                        for name in (("nickname", "remark") if kind == "users" else ("group_name",))}})
        # Do not cache a snapshot across a switch while awaiting network replies.
        if self._first_active_websocket() is not websocket or int(self.config.bot_qq or 0) != binding:
            raise RuntimeError("binding changed during contact lookup")
        self._contact_directory_cache = (websocket, binding, time.time(), contacts)
        return contacts

    @staticmethod
    def _proactive_action_ok(reply):
        return isinstance(reply, dict) and reply.get("status") == "ok" and reply.get("retcode") == 0

    async def _evaluate_proactive_opportunity(self, websocket, policy):
        engine, planner, config = self.reply_engine, self.proactive_planner, self.config
        binding = int(config.bot_qq or 0)
        scope = await self._proactive_contact_scope(websocket)
        if self.reply_engine is not engine or self.proactive_planner is not planner:
            return
        planner.update_owner_qqs(getattr(config, "owner_qqs", ()))
        plans = planner.due_plans(policy, allowed_targets=scope)
        if not plans:
            return
        plan = plans[0]
        memory = engine.memory
        baseline = memory.proactive_state(plan.conversation_id)
        started = time.monotonic()
        # Reserve this evaluation globally before the first expensive operation.
        memory.record_proactive_evaluation(plan.conversation_id, "evaluating", time.time())
        outcome = "failure"
        result = {}
        try:
            result = await engine.generate_proactive_message(plan.conversation_id, plan.event_type, policy)
            text = str(result.get("text") or "").strip()
            voice_request = engine.consume_voice_request(plan.conversation_id)
            if result.get("decision") in {"defer", "drop"}:
                outcome = result["decision"]
                return
            if not text and voice_request is None:
                outcome = "drop" if result.get("source") == "skipped-quality" else "failure"
                return
            permission_event = dict(plan.target)
            if voice_request is not None and not is_event_modality_allowed(permission_event, "voice"):
                text = text or str(voice_request.text or "").strip()
                voice_request = None
            message = text
            sent_text = text
            if voice_request is not None:
                sent_text = voice_request.text
                try:
                    synthesis = await self.voice.synthesize(plan.conversation_id, voice_request)
                    message = outgoing_to_onebot_message(OutgoingMessage("record", str(synthesis.audio_path)))
                except Exception:
                    message = voice_request.text
            await asyncio.sleep(_first_reply_delay(config, sent_text))
            # Generation can overlap a reply, settings change or account switch.
            fresh_scope = await self._proactive_contact_scope(websocket, refresh=True)
            if (self.reply_engine is not engine or self.proactive_planner is not planner
                    or int(self.config.bot_qq or 0) != binding
                    or self._first_active_websocket() is not websocket
                    or getattr(self, 'proactive_owner', 'core') == 'astrbot'):
                outcome = "stale"
                return
            current = memory.proactive_state(plan.conversation_id)
            current_policy = load_proactive_policy()
            from atri_bot.proactive.planner import candidate_tier as opportunity_tier, _is_quiet as opportunity_quiet
            tier, _ = opportunity_tier(current_policy, current, int(plan.target.get("user_id") or 0) in planner.owner_qqs,
                                       plan.target.get("message_type") == "group", time.time())
            if (not getattr(self.config, "proactive_v2_enabled", False) or not current_policy.get("enabled", True)
                    or opportunity_quiet(datetime.now(safe_zoneinfo(str(current_policy["timezone"]))), current_policy)
                    or plan.conversation_id not in fresh_scope or tier is None
                    or current.get("last_user_at") != baseline.get("last_user_at")
                    or current.get("last_bot_at") != baseline.get("last_bot_at")):
                outcome = "stale"
                return
            # From here any transport exception is ambiguous. Persist first so
            # cancellation/crash cannot turn an unknown receipt into a duplicate.
            memory.record_proactive_evaluation(plan.conversation_id, "sending", time.time())
            outcome = "unknown"
            group = plan.target.get("message_type") == "group"
            key = "group_id" if group else "user_id"
            reply = await self.call_action_and_wait(websocket, "send_group_msg" if group else "send_private_msg",
                {key: plan.target[key], "message": message}, timeout_seconds=10)
            if isinstance(reply, dict) and reply.get("status") == "failed":
                outcome = "failure"
                return
            if not self._proactive_action_ok(reply) or not (reply.get("data") or {}).get("message_id"):
                return
            local_now = datetime.now(safe_zoneinfo(str(policy["timezone"])))
            # Persist acknowledgement before ancillary history writes.
            memory.mark_proactive_sent(plan.conversation_id, plan.event_type, sent_text,
                str(result.get("source") or "unknown"), local_now.date().isoformat(), now=local_now.timestamp())
            outcome = "sent"
            engine.record_bot_reply(plan.conversation_id, sent_text)
        except Exception as exc:
            LOGGER.warning("[proactive] evaluation/send failed stage=%s error=%s", outcome, type(exc).__name__)
        finally:
            planner.complete(plan, policy, outcome)
            LOGGER.info("[proactive] at=%s target=%s decision=%s source=%s reason=%s elapsed=%.1fs model_calls=%s tokens=%s",
                datetime.now().isoformat(timespec="seconds"), plan.conversation_id, outcome, result.get("source", ""),
                result.get("reason", ""), time.monotonic() - started, result.get("model_calls", "unknown"), result.get("total_tokens", "unknown"))

    def proactive_status(self) -> dict[str, Any]:
        policy = load_proactive_policy()
        self.proactive_planner.update_owner_qqs(getattr(self.config, "owner_qqs", ()))
        return {
            "feature_enabled": bool(getattr(self.config, "proactive_v2_enabled", False)),
            "policy": policy,
            "schedule": self.proactive_planner.status(policy),
        }

    async def preview_proactive(
        self,
        event_type: str,
        target_id: int | None = None,
        scope: str = "private",
        prepare: bool = False,
    ) -> dict[str, str]:
        policy = load_proactive_policy()
        candidates = self.reply_engine.memory.proactive_candidates(
            getattr(self.config, "owner_qqs", ()),
            bool(policy.get("owner_only", False)),
            include_groups=bool(policy.get("group_enabled", False)),
        )
        scope = "group" if scope == "group" else "private"
        if target_id:
            conversation_id = f"{scope}:{int(target_id)}"
        elif matching := [item for item in candidates if item[1].get("message_type") == scope]:
            conversation_id = matching[0][0]
        else:
            raise ValueError(f"没有可预览的{'群聊' if scope == 'group' else '私聊'}目标")
        if prepare:
            if getattr(self, "proactive_owner", "core") != "core" or not getattr(self.config, "proactive_v2_enabled", False):
                return {"text": "", "decision": "drop", "reason": "当前路线未使用自研主动模块"}
            state = self.reply_engine.memory.proactive_state(conversation_id)
            from atri_bot.proactive.planner import candidate_tier
            tier, reason = candidate_tier(policy, state, int(target_id or 0) in self.proactive_planner.owner_qqs,
                                         scope == "group", time.time())
            if not policy.get("enabled", True) or not tier:
                return {"text": "", "decision": "drop", "reason": reason or "主动消息已关闭"}
            # Reading/preparing content must not reschedule a queued opportunity.
            # Only the existing scheduler advances expired slots at startup.
            if not state.get("next_at") or state["next_at"] <= time.time():
                return {"text": "", "decision": "defer", "reason": "等待调度器安排下一次机会，已过期的文案不补发"}
            event_type = state.get("next_event_type") or "check_in"
            result = await self.reply_engine.prepare_proactive_draft(conversation_id, event_type, policy)
            return {"conversation_id": conversation_id, "event_type": event_type,
                    "scheduled_at": state["next_at"], **result}
        result = await self.reply_engine.generate_proactive_message(
            conversation_id,
            event_type,
            policy,
        )
        return {"conversation_id": conversation_id, "event_type": event_type, **result}

    async def group_proactive_loop(self) -> None:
        while True:
            await asyncio.sleep(max(30, int(self.config.group_proactive_check_seconds)))
            if getattr(self, 'proactive_owner', 'core') == 'astrbot':
                continue
            if getattr(self.config, "proactive_v2_enabled", False):
                continue
            if not self.config.group_proactive_enabled:
                continue

            websocket = self._first_active_websocket()
            if websocket is None:
                continue

            for conversation_id, target in self.reply_engine.due_group_targets():
                group_id = target.get("group_id")
                if not group_id:
                    continue
                text = self.reply_engine.group_nudge_text(conversation_id)
                try:
                    await self.call_action(
                        websocket,
                        "send_group_msg",
                        {"group_id": group_id, "message": text},
                    )
                    self.reply_engine.mark_group_proactive(conversation_id)
                    self.reply_engine.record_bot_reply(conversation_id, text)
                    print(f"[onebot] Group proactive nudge sent to {group_id}.")
                except Exception as exc:
                    print(f"[onebot] Group proactive send failed: {exc}")
                    break

    def _first_active_websocket(self) -> Any | None:
        for websocket in list(self._active_websockets):
            return websocket
        return None

    def _log_message_decision(
        self,
        event: dict[str, Any],
        plain_text: str,
        should_send_reply: bool,
    ) -> None:
        with contextlib.suppress(Exception):
            self._event_log.parent.mkdir(parents=True, exist_ok=True)
            preview = plain_text.replace("\n", " ")[:120]
            line = (
                f"{_now_text()} mode={self.config.reply_mode} "
                f"type={event.get('message_type')} group={event.get('group_id')} "
                f"user={event.get('user_id')} reply={should_send_reply} text={preview}\n"
            )
            with self._event_log.open("a", encoding="utf-8") as file:
                file.write(line)

    def _log_voice_event(
        self,
        event: dict[str, Any],
        status: str,
        *,
        request: Any | None = None,
        message: OutgoingMessage | None = None,
        result: Any | None = None,
        error: Any = "",
        elapsed_ms: float | None = None,
    ) -> None:
        # Pytest uses synthetic QQ ids and temporary audio paths. Keeping those
        # events out of the operator log makes production failure rates usable.
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        with contextlib.suppress(Exception):
            quality = getattr(result, "quality", None)
            if not isinstance(quality, dict):
                quality = getattr(error, "quality", None)
            error_text = str(error or "").strip()
            if not error_text and isinstance(error, BaseException):
                error_text = f"{type(error).__name__}: {error!r}"
            payload = {
                "time": _now_text(),
                "status": status,
                "message_type": event.get("message_type"),
                "group_id": event.get("group_id"),
                "user_id": event.get("user_id"),
                "mode": getattr(request, "mode", ""),
                "text": str(getattr(request, "text", "") or "")[:200],
                "source": str(getattr(result, "source", "") or ""),
                "quality": quality if isinstance(quality, dict) else None,
                "file": str(
                    getattr(result, "audio_path", "")
                    or (message.content if message is not None else "")
                ),
                "retcode": result.get("retcode") if isinstance(result, dict) else None,
                "error": error_text[:500],
                "elapsed_ms": round(float(elapsed_ms), 1) if elapsed_ms is not None else None,
            }
            self._voice_event_log.parent.mkdir(parents=True, exist_ok=True)
            with self._voice_event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _record_reply_failure(
        self,
        event: dict[str, Any],
        *,
        turn_id: str,
        conversation_id: str,
        user_text: str,
        model_reply: str,
        reason: str,
        tool_context: Any | None = None,
        reply_focus: Any | None = None,
        quoted_message_id: str = "",
        model_type: str = "chat",
        model_name: str = "",
    ) -> None:
        """把失败写入诊断与评测旁路，不生成或发送任何 QQ 消息。"""
        fail_current()
        safe_reason = str(reason or "未知回复错误").strip()[:800]
        LOGGER.error(
            "回复失败，已保持用户侧静默：conversation=%s error=%s",
            conversation_id,
            safe_reason,
        )
        self._log_reply_event(
            event,
            conversation_id=conversation_id,
            user_text=user_text,
            model_reply=model_reply,
            delivered_reply="",
            material_read_level=str(getattr(tool_context, "read_level", "") or ""),
            reply_focus_source=str(getattr(reply_focus, "source", "") or ""),
            reply_focus_text=str(getattr(reply_focus, "focus_text", "") or ""),
            quoted_message_id=quoted_message_id,
            status="failed",
            failure_reason=safe_reason,
        )
        if self.insights is None:
            return
        sample = EvaluationSample(
            turn_id=turn_id,
            conversation_id=conversation_id,
            group_id=str(event.get("group_id") or ""),
            question=user_text,
            answer=model_reply,
            context=context_from_tool_context(tool_context),
            model_type=model_type,
            model_name=model_name,
        )
        submit_failure = getattr(self.insights, "submit_evaluation_failure", None)
        if callable(submit_failure):
            submit_failure(sample, safe_reason)

    def _log_reply_event(
        self,
        event: dict[str, Any],
        *,
        conversation_id: str,
        user_text: str,
        model_reply: str,
        delivered_reply: str,
        voice_mode: str = "",
        material_read_level: str = "",
        reply_focus_source: str = "",
        reply_focus_text: str = "",
        quoted_message_id: str = "",
        status: str = "delivered",
        failure_reason: str = "",
    ) -> None:
        with contextlib.suppress(Exception):
            payload = {
                "time": _now_text(),
                "conversation_id": conversation_id,
                "message_type": event.get("message_type"),
                "group_id": event.get("group_id"),
                "user_id": event.get("user_id"),
                "user_text": str(user_text or "")[:800],
                "model_reply": str(model_reply or "")[:1200],
                "delivered_reply": str(delivered_reply or "")[:1200],
                "voice_mode": voice_mode,
                "material_read_level": material_read_level,
                "reply_focus_source": reply_focus_source,
                "reply_focus_text": str(reply_focus_text or "")[:400],
                "quoted_message_id": str(quoted_message_id or ""),
                "status": str(status or "delivered"),
                "failure_reason": str(failure_reason or "")[:800],
            }
            self._reply_event_log.parent.mkdir(parents=True, exist_ok=True)
            with self._reply_event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")

