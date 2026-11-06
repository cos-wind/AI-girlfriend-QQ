from __future__ import annotations

from . import core as _core
from atri_bot.proactive.content import CONTEXT_FREE_EVENTS, proactive_context, proactive_content_rejection


class EngineProactiveMixin:
    async def generate_proactive_message(
        self, conversation_id, event_type, policy, now=None,
    ):
        from atri_bot.proactive.draft import current_draft
        timestamp = now.timestamp() if now else _core.time.time()
        cached = current_draft(self, conversation_id, event_type, policy, timestamp)
        if cached:
            local_now = _core.datetime.fromtimestamp(timestamp, _core.safe_zoneinfo(str(policy["timezone"])))
            state = self.memory.proactive_state(conversation_id, now=timestamp)
            sources, _, bot_texts = proactive_context(
                self.memory.recent_history(conversation_id, limit=80), state.get("recent_messages", []), local_now,
                is_group=conversation_id.startswith("group:"), limit=int(policy.get("history_limit", 8)))
            if ((sources or event_type in CONTEXT_FREE_EVENTS)
                    and not proactive_content_rejection(cached["text"], bot_texts, sources)):
                self._pending_voice_requests.pop(conversation_id, None)
                return {"text": cached["text"][:int(policy.get("max_chars", 90))],
                        "source": "prepared-draft", "decision": "send",
                        "model_calls": "0", "total_tokens": "0", "error": ""}
        return await self._generate_proactive_message(conversation_id, event_type, policy, now)

    async def prepare_proactive_draft(self, conversation_id, event_type, policy):
        import asyncio
        from atri_bot.proactive.draft import current_draft, draft_key
        locks = getattr(self, "_proactive_draft_locks", None)
        if locks is None:
            self._proactive_draft_locks = locks = {}
        async with locks.setdefault(conversation_id, asyncio.Lock()):
            # Normalize legacy relationship/state fields before taking the snapshot.
            self.memory.profile(conversation_id)
            self.memory.proactive_state(conversation_id)
            cached = current_draft(self, conversation_id, event_type, policy, _core.time.time())
            if cached:
                return {"text": cached["text"], "source": "prepared-draft", "decision": "send"}
            scheduled_at = self.memory._conversation(conversation_id).get("next_proactive_at")
            if not scheduled_at or scheduled_at <= _core.time.time():
                return {"text": "", "decision": "defer", "reason": "等待下一次有效计划"}
            key = draft_key(self, conversation_id, event_type, policy)
            result = await self._generate_proactive_message(conversation_id, event_type,
                {**policy, "draft_text_only": True},
                now=_core.datetime.fromtimestamp(scheduled_at, _core.safe_zoneinfo(str(policy["timezone"]))))
            if key != draft_key(self, conversation_id, event_type, policy):
                return {"text": "", "decision": "defer", "reason": "context-changed"}
            if result.get("text") and result.get("decision") == "send":
                self.memory._conversation(conversation_id)["proactive_draft"] = {
                    "key": key, "created_at": _core.time.time(), "text": result["text"], "event_type": event_type}
                self.memory._save()
            return result

    async def _generate_proactive_message(
        self,
        conversation_id: str,
        event_type: str,
        policy: dict[str, _core.Any],
        now: _core.datetime | None = None,
    ) -> dict[str, str]:
        text_only = bool(policy.get("draft_text_only"))
        if not text_only:
            self._pending_voice_requests.pop(conversation_id, None)
        timezone = _core.safe_zoneinfo(str(policy.get("timezone") or "Asia/Shanghai"))
        local_now = now.astimezone(timezone) if now else _core.datetime.now(timezone)
        is_group = conversation_id.startswith("group:") and ":user:" not in conversation_id
        if not policy.get("use_ai", True):
            return {
                "text": "",
                "source": "skipped-ai-disabled",
                "error": "主动消息已关闭 AI 生成，本次不发送模板",
            }
        if not self.config.ai_enabled:
            return {
                "text": "",
                "source": "skipped-no-model",
                "error": "未配置聊天模型，本次主动消息未发送",
            }

        profile = self.memory.profile(conversation_id)
        history = self.memory.recent_history(
            conversation_id,
            limit=max(40, int(policy.get("history_limit", 8)) * 4),
        )
        state = self.memory.proactive_state(conversation_id)
        human_pipeline = bool(getattr(self.config, "human_reply_pipeline_enabled", True))
        sources, history_text, bot_texts = proactive_context(
            [entry for entry in history if not _core.is_memory_pollution_text(str(entry.get("text") or ""))],
            state.get("recent_messages", []), local_now,
            is_group=is_group, limit=int(policy.get("history_limit", 8)),
        )
        if not sources and event_type not in CONTEXT_FREE_EVENTS:
            return {"text": "", "source": "content-decision", "decision": "drop",
                    "reason": "no-fresh-user-context", "error": "", "model_calls": "0", "total_tokens": "0"}
        recent_proactive = "\n".join(f"- {text[:240]}" for text in bot_texts)
        event_labels = {
            "morning": "自然地说早安，可以顺带关心今天的状态",
            "goodnight": "自然地提醒休息或说晚安，不催促用户回复",
            "check_in": "像熟悉的人随手来问候，关心近况",
            "continue_topic": "从最近聊天里挑一个仍值得继续的话题",
            "interest_topic": "结合用户明确记录的兴趣开启话题",
            "guided_topic": "制造一个有具体切入点、容易回应的新话题",
            "daily_share": "分享一个轻巧的想法或数字世界里的小发现，不编造现实经历",
            "affection": "表达一点自然的想念或亲近，不黏人、不索取回复",
            "encouragement": "结合近期情况给具体而不过度的鼓励",
        }
        scene = "群聊" if is_group else "私聊"
        relationship = (
            f"群活跃状态：{profile.get('group_activity_state', '普通')}。"
            if is_group
            else f"关系状态：{profile.get('affection_state', '普通')}，好感值仅用于控制亲近程度，禁止直接报数值。"
        )
        context_name = "最近群聊公开内容" if is_group else "最近私聊"
        privacy_rule = (
            "- 这是群聊。只能使用上面列出的群聊公开内容，禁止引用、暗示或推断任何成员的私聊记忆；不要称呼任何人为主人。\n"
            "- 话题要让多个人都能参与，避免点名单个成员回答，也不要表现得像群管理员在强行暖场。"
            if is_group
            else "- 这是私聊。亲近程度要符合关系状态，不要对非主人使用主人称呼。"
        )
        topic_rule = ""
        if policy.get("guided_topics", True) and event_type in {
            "guided_topic",
            "continue_topic",
            "interest_topic",
            "daily_share",
            "check_in",
        }:
            topic_rule = _core.load_prompt("proactive_topic_rule")
        prompt = _core.render_prompt(
            "proactive",
            local_time=local_now.strftime("%Y-%m-%d %H:%M"),
            scene=scene,
            event_label=event_labels.get(event_type, event_type),
            relationship=relationship,
            profile_hint=profile.get("prompt_hint", ""),
            context_name=context_name,
            history=history_text or "暂无可用上下文",
            recent_proactive=recent_proactive or "暂无",
            privacy_rule=privacy_rule,
            topic_rule=topic_rule,
        )
        prompt += (
            "\n本次只是评估开口机会，不要求必须说话。只有最近话题、未完交流或可靠兴趣提供了"
            "有意义且不重复的切入点才发送；不得为完成任务硬找话题。"
            "时机不合适、对方忙或正在聊别的话题，只输出 [DEFER]；"
            "没有新内容、重复寒暄或缺乏可靠依据，只输出 [DROP]。这两个标记不会发给对方。"
        )
        import random
        max_chars = int(policy.get("max_chars", 90))
        length = random.choices([min(24, max_chars), min(48, max_chars), max_chars], weights=[5, 4, 1])[0]
        form = random.choice(["直接说一句想说的话，不提问", "表达一个具体感受，不必提问",
                              "只提出一个简短具体的问题", "简短分享一个有依据的观点，不必提问"])
        prompt += (f"\n本次表达形式：{form}。正文最多{length}个字符，所有标点也计数。"
                   "历史只是理解背景，不需要交代来源；避免用‘你上次说’‘还记得你说’作惯常开场。"
                   "不要把简短招呼扩写为回顾、分析、建议和追问的长段落。")
        messages = [
            {"role": "system", "content": _core.PERSONA_PROMPT},
            {"role": "system", "content": _core.LANGUAGE_GUARD_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_schemas = [
            item
            for item in _core.available_tool_schemas(self.config)
            if not text_only and item.get("function", {}).get("name") == "speak_as_atri"
        ]
        if tool_schemas:
            messages.insert(
                2,
                {"role": "system", "content": _core.AUTOMATIC_TOOL_INSTRUCTION_PROMPT},
            )
            messages.insert(
                3,
                {
                    "role": "system",
                    "content": (
                        _core.voice_policy_prompt(conversation_id, profile)
                        + " 这是主动消息；仅在语音明显更自然时调用，reason 必须填 proactive。"
                    ),
                },
            )
        payload = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": min(1.0, max(0.55, float(self.config.temperature))),
            "max_tokens": min(220, max(80, int(self.config.max_tokens))),
            "frequency_penalty": max(0.35, float(self.config.frequency_penalty)),
        }
        payload.update(
            _core._provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        model_calls = 0
        total_tokens = 0

        async def completion(client, request):
            nonlocal model_calls, total_tokens
            model_calls += 1
            response = await self._post_chat_completion(client, headers, request)
            total_tokens += int((response.get("usage") or {}).get("total_tokens") or 0)
            return response

        def abstention(content):
            if content.strip().upper() in {"[DEFER]", "[DROP]"}:
                if not text_only:
                    self._pending_voice_requests.pop(conversation_id, None)
                return {"text": "", "source": "ai-decision", "decision": content.strip()[1:-1].lower(),
                        "error": "", "model_calls": str(model_calls), "total_tokens": str(total_tokens)}
            return None

        try:
            import httpx

            generation_source = "ai"
            async with httpx.AsyncClient(
                timeout=_core._chat_http_timeout(self.config)
            ) as client:
                data = await completion(client, payload)
                message = data["choices"][0]["message"]
                tool_calls = _core.tool_calls_from_message(message)
                if tool_calls:
                    await _core.append_tool_results(
                        messages,
                        message,
                        tool_calls,
                        self.config,
                        executor=lambda name, arguments, config: self._execute_context_tool(
                            conversation_id, name, arguments, config
                        ),
                        context_id=conversation_id,
                    )
                    followup_payload = dict(payload)
                    followup_payload["messages"] = messages
                    data = await completion(client, followup_payload)
                    message = data["choices"][0]["message"]
            content = _core._normalize_reply(str(message.get("content") or ""))
            if decision := abstention(content):
                return decision
            has_voice = not text_only and conversation_id in self._pending_voice_requests
            if not has_voice and human_pipeline:
                review_messages = list(messages)
                review_messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "发送前自然复核一次这条主动消息。"
                                "如果它已经自然、具体且有依据，保持原意只做必要润色；"
                                "如果它把亚托莉自己的旧话当成用户事实、猜测用户当前现实状态、"
                                "重复最近主动消息的标签或话题角度，改成不预设用户状态的自然说法。"
                                "不要解释复核过程，只输出最终要发送的一条消息。"
                                "如果没有新内容或不适合打扰，可只输出 [DROP] 或 [DEFER]。"
                            ),
                        },
                    ]
                )
                review_payload = dict(payload)
                review_payload["messages"] = review_messages
                review_payload.pop("tools", None)
                review_payload.pop("tool_choice", None)
                async with httpx.AsyncClient(
                    timeout=_core._chat_http_timeout(self.config)
                ) as client:
                    reviewed = await completion(client, review_payload)
                reviewed_content = _core._normalize_reply(
                    str(reviewed["choices"][0]["message"].get("content") or "")
                ).strip()
                if decision := abstention(reviewed_content):
                    return decision
                if reviewed_content:
                    content = reviewed_content
                    generation_source = "ai-reviewed"
            elif not has_voice and (
                _core._needs_proactive_grounding_repair(content) or _core._needs_topic_guidance_repair(
                content,
                event_type,
                bool(policy.get("guided_topics", True)),
                )
            ):
                repair_messages = list(messages)
                repair_messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "重写这条消息。你刚才声称自己点开、看过、试过或搜索过某个内容，"
                                "或者编造了自己做过、玩过、用过的经历，但这些动作并未发生。"
                                "也可能没有真正提供可回应的话题。保留具体切入点，只能基于已有文字上下文，"
                                "需要提问时只留一个具体、低门槛的问题，也可以只表达一个完整观点或感受。"
                                "不要解释为什么重写，只输出最终消息。"
                            ),
                        },
                    ]
                )
                repair_payload = dict(payload)
                repair_payload["messages"] = repair_messages
                async with httpx.AsyncClient(
                    timeout=_core._chat_http_timeout(self.config)
                ) as client:
                    repaired = await completion(client, repair_payload)
                content = _core._normalize_reply(
                    str(repaired["choices"][0]["message"].get("content") or "")
                )
                if decision := abstention(content):
                    return decision
                if _core._needs_proactive_grounding_repair(content) or _core._needs_topic_guidance_repair(
                    content,
                    event_type,
                    bool(policy.get("guided_topics", True)),
                ):
                    return {
                        "text": "",
                        "source": "skipped-quality",
                        "error": "主动消息连续未通过真实性或话题质量检查",
                        "model_calls": str(model_calls),
                        "total_tokens": str(total_tokens),
                    }
            if not has_voice and human_pipeline and (
                _core._needs_proactive_grounding_repair(content)
                or _core._needs_topic_guidance_repair(
                    content,
                    event_type,
                    bool(policy.get("guided_topics", True)),
                )
            ):
                return {
                    "text": "",
                    "source": "skipped-quality",
                    "error": "主动消息复核后仍缺少可靠依据或自然话题",
                    "model_calls": str(model_calls),
                    "total_tokens": str(total_tokens),
                }
            voice_request = None if text_only else self._pending_voice_requests.get(conversation_id)
            if voice_request is not None and _core._needs_proactive_grounding_repair(voice_request.text):
                self._pending_voice_requests.pop(conversation_id, None)
                return {"text": "", "source": "content-decision", "decision": "drop",
                        "reason": "ungrounded-voice-content", "error": "", "model_calls": str(model_calls),
                        "total_tokens": str(total_tokens)}
            rejection = proactive_content_rejection(content, bot_texts, sources)
            content = content.strip()[: int(policy.get("max_chars", 90))].strip()
            if not rejection:
                rejection = proactive_content_rejection(content, bot_texts, sources)
            if not rejection and voice_request is not None:
                rejection = proactive_content_rejection(voice_request.text, bot_texts, sources)
            if rejection:
                if not text_only:
                    self._pending_voice_requests.pop(conversation_id, None)
                return {"text": "", "source": "content-decision", "decision": "drop",
                        "reason": rejection, "error": "", "model_calls": str(model_calls),
                        "total_tokens": str(total_tokens)}
            if not content and not has_voice:
                raise RuntimeError("模型返回空消息")
            return {
                "text": content,
                "source": "ai-voice" if has_voice else generation_source,
                "decision": "send",
                "model_calls": str(model_calls),
                "total_tokens": str(total_tokens),
                "error": "",
            }
        except Exception as exc:
            return {
                "text": "",
                "source": "skipped-error",
                "model_calls": str(model_calls),
                "total_tokens": str(total_tokens),
                "error": str(exc),
            }

    def due_group_targets(self) -> list[tuple[str, dict[str, _core.Any]]]:
        return self.memory.due_group_targets(
            self.config.group_proactive_idle_minutes,
            self.config.group_proactive_cooldown_minutes,
            self.config.group_proactive_daily_limit,
            self.config.group_proactive_max_silence_days,
        )

    def mark_group_proactive(self, conversation_id: str) -> None:
        self.memory.mark_group_proactive(conversation_id)

    def group_nudge_text(self, conversation_id: str) -> str:
        return _core.group_nudge_text(self.memory.profile(conversation_id))

    def _activate_serious_mode(self, *conversation_ids: str | None) -> None:
        until = _core.time.time() + _core.SERIOUS_MODE_SECONDS
        for conversation_id in conversation_ids:
            if conversation_id:
                self._serious_until[conversation_id] = until

    def _serious_mode_active(self, conversation_id: str) -> bool:
        return _core.time.time() < float(self._serious_until.get(conversation_id, 0.0))


