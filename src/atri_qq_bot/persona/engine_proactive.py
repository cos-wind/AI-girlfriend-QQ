from __future__ import annotations

from .engine_support import PersonaEngineMixin


class EngineProactiveMixin(PersonaEngineMixin):
    async def generate_proactive_message(
        self,
        conversation_id: str,
        event_type: str,
        policy: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, str]:
        self._pending_voice_requests.pop(conversation_id, None)
        timezone = safe_zoneinfo(str(policy.get("timezone") or "Asia/Shanghai"))
        local_now = now.astimezone(timezone) if now else datetime.now(timezone)
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
            limit=int(policy.get("history_limit", 8)),
        )
        state = self.memory.proactive_state(conversation_id)
        human_pipeline = bool(getattr(self.config, "human_reply_pipeline_enabled", True))
        history_text = "\n".join(
            f"{(entry.get('nickname') or '群友') if is_group and entry.get('role') == 'user' else ('用户' if entry.get('role') == 'user' else '亚托莉')}：{str(entry.get('text') or '')[:160]}"
            for entry in history
            if entry.get("text")
        )
        recent_proactive = "；".join(
            str(item.get("text") or "")[:90]
            for item in state.get("recent_messages", [])[-4:]
            if isinstance(item, dict)
        )
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
            topic_rule = load_prompt("proactive_topic_rule")
        prompt = render_prompt(
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
        messages = [
            {"role": "system", "content": PERSONA_PROMPT},
            {"role": "system", "content": LANGUAGE_GUARD_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_schemas = [
            item
            for item in available_tool_schemas(self.config)
            if item.get("function", {}).get("name") == "speak_as_atri"
        ]
        if tool_schemas:
            messages.insert(
                2,
                {"role": "system", "content": AUTOMATIC_TOOL_INSTRUCTION_PROMPT},
            )
            messages.insert(
                3,
                {
                    "role": "system",
                    "content": (
                        voice_policy_prompt(conversation_id, profile)
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
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        try:
            import httpx

            generation_source = "ai"
            async with httpx.AsyncClient(
                timeout=_chat_http_timeout(self.config)
            ) as client:
                data = await self._post_chat_completion(client, headers, payload)
                message = data["choices"][0]["message"]
                tool_calls = tool_calls_from_message(message)
                if tool_calls:
                    await append_tool_results(
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
                    data = await self._post_chat_completion(client, headers, followup_payload)
                    message = data["choices"][0]["message"]
            content = _normalize_reply(str(message.get("content") or ""))
            has_voice = conversation_id in self._pending_voice_requests
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
                            ),
                        },
                    ]
                )
                review_payload = dict(payload)
                review_payload["messages"] = review_messages
                review_payload.pop("tools", None)
                review_payload.pop("tool_choice", None)
                async with httpx.AsyncClient(
                    timeout=_chat_http_timeout(self.config)
                ) as client:
                    reviewed = await self._post_chat_completion(
                        client,
                        headers,
                        review_payload,
                    )
                reviewed_content = _normalize_reply(
                    str(reviewed["choices"][0]["message"].get("content") or "")
                ).strip()
                if reviewed_content:
                    content = reviewed_content
                    generation_source = "ai-reviewed"
            elif not has_voice and (
                _needs_proactive_grounding_repair(content) or _needs_topic_guidance_repair(
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
                                "并补上一个具体、低门槛的问题，让人可以从观点、选择或经历中选一个方向回答。"
                                "不要解释为什么重写，只输出最终消息。"
                            ),
                        },
                    ]
                )
                repair_payload = dict(payload)
                repair_payload["messages"] = repair_messages
                async with httpx.AsyncClient(
                    timeout=_chat_http_timeout(self.config)
                ) as client:
                    repaired = await self._post_chat_completion(
                        client,
                        headers,
                        repair_payload,
                    )
                content = _normalize_reply(
                    str(repaired["choices"][0]["message"].get("content") or "")
                )
                if _needs_proactive_grounding_repair(content) or _needs_topic_guidance_repair(
                    content,
                    event_type,
                    bool(policy.get("guided_topics", True)),
                ):
                    return {
                        "text": "",
                        "source": "skipped-quality",
                        "error": "主动消息连续未通过真实性或话题质量检查",
                    }
            if not has_voice and human_pipeline and (
                _needs_proactive_grounding_repair(content)
                or _needs_topic_guidance_repair(
                    content,
                    event_type,
                    bool(policy.get("guided_topics", True)),
                )
            ):
                return {
                    "text": "",
                    "source": "skipped-quality",
                    "error": "主动消息复核后仍缺少可靠依据或自然话题",
                }
            content = content.strip()[: int(policy.get("max_chars", 90))].strip()
            if not content and not has_voice:
                raise RuntimeError("模型返回空消息")
            return {
                "text": content,
                "source": "ai-voice" if has_voice else generation_source,
                "error": "",
            }
        except Exception as exc:
            return {
                "text": "",
                "source": "skipped-error",
                "error": str(exc),
            }

    def due_group_targets(self) -> list[tuple[str, dict[str, Any]]]:
        return self.memory.due_group_targets(
            self.config.group_proactive_idle_minutes,
            self.config.group_proactive_cooldown_minutes,
            self.config.group_proactive_daily_limit,
            self.config.group_proactive_max_silence_days,
        )

    def mark_group_proactive(self, conversation_id: str) -> None:
        self.memory.mark_group_proactive(conversation_id)

    def group_nudge_text(self, conversation_id: str) -> str:
        return group_nudge_text(self.memory.profile(conversation_id))

    def _activate_serious_mode(self, *conversation_ids: str | None) -> None:
        until = time.time() + SERIOUS_MODE_SECONDS
        for conversation_id in conversation_ids:
            if conversation_id:
                self._serious_until[conversation_id] = until

    def _serious_mode_active(self, conversation_id: str) -> bool:
        return time.time() < float(self._serious_until.get(conversation_id, 0.0))

    def _can_use_abstract_reply(self, conversation_id: str, user_text: str) -> bool:
        if not conversation_id.startswith("group:"):
            return False
        if self._serious_mode_active(conversation_id):
            return False
        if not _has_abstract_trigger(_intent_text(user_text)):
            return False
        last_at = float(self._last_abstract_reply_at.get(conversation_id, 0.0))
        if time.time() - last_at < ABSTRACT_REPLY_COOLDOWN_SECONDS:
            return False
        return random.random() < ABSTRACT_REPLY_CHANCE

    def _mark_abstract_reply(self, conversation_id: str) -> None:
        self._last_abstract_reply_at[conversation_id] = time.time()


