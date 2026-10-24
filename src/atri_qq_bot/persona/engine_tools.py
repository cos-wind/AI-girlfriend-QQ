from __future__ import annotations

from .engine_support import PersonaEngineMixin


class EngineToolsMixin(PersonaEngineMixin):
    async def _reply_with_api(
        self,
        conversation_id: str,
        user_text: str,
        nickname: str | None,
        extra_system: str | None = None,
        profile_id: str | None = None,
        profile: dict[str, Any] | None = None,
        context_profile: dict[str, Any] | None = None,
        iteration_decision: Any | None = None,
        tool_context: Any | None = None,
        reply_focus: GroupReplyFocus | None = None,
        temperature_override: float | None = None,
        frequency_penalty_override: float | None = None,
        allow_reply_voice: bool | None = None,
    ) -> str:
        import httpx

        # system 消息按职责分层：人格/原作设定保持身份连续，能力与工具合同
        # 约束可执行动作，动态上下文只描述本轮事实，避免上下文互相污染。
        repair_mode = _needs_comfort_repair_mode(user_text, iteration_decision)
        visual_turn = _has_current_visual_context(tool_context)
        # 只把稳定人格放在每轮主上下文中。原作百科、能力清单和认知快照
        # 都是按需资料；每轮全量注入会让模型把“介绍自己”误当成当前任务，
        # 这是普通聊天出现前言不搭后语的主要回归来源之一。
        messages = [
            {"role": "system", "content": PERSONA_PROMPT},
            {"role": "system", "content": LANGUAGE_GUARD_PROMPT},
        ]
        identity_context_needed = _needs_identity_context(user_text)
        continuity_context_needed = _needs_continuity_context(user_text)
        if identity_context_needed:
            messages.append({"role": "system", "content": load_prompt("cognition_identity")})
        cognition_context = render_cognition_context(
            self._cognition_store,
            profile_id or conversation_id,
        )
        if cognition_context and (identity_context_needed or continuity_context_needed):
            messages.append({"role": "system", "content": cognition_context})
        # 原作设定只在原作/身份问题出现时进入主提示词；日常消息依靠
        # 人格核心和按需检索即可，避免深海、夏生、型号等内容抢占当前话题。
        if has_lore_trigger(user_text) or _explicit_lore_context(user_text) or identity_context_needed:
            messages.append({"role": "system", "content": ATRI_LORE_PROMPT})
        if conversation_id.startswith("group:"):
            messages.append({"role": "system", "content": GROUP_PROMPT})
        messages.append({"role": "system", "content": load_prompt("reply_contract")})
        if identity_context_needed or _needs_capability_context(user_text, tool_context):
            messages.append({"role": "system", "content": load_prompt("capabilities")})
        if extra_system:
            messages.append({"role": "system", "content": extra_system})
        elif repair_mode:
            messages.append({"role": "system", "content": COMFORT_REPAIR_PROMPT})
        tool_schemas = available_tool_schemas(self.config)
        voice_profile = (
            self.memory.profile(conversation_id)
            if conversation_id.startswith("group:")
            else profile or self.memory.profile(profile_id or conversation_id)
        )
        if allow_reply_voice is None:
            policy = load_voice_behavior()
            allow_reply_voice = evaluate_reply_voice_choice(
                conversation_id,
                voice_profile,
                policy,
                explicit_request=detect_explicit_delivery_intent(user_text) is not None,
                replying_to_voice=bool(
                    getattr(tool_context, "prefer_voice_reply", False)
                ),
            ).allowed
        if not allow_reply_voice:
            tool_schemas = [
                schema
                for schema in tool_schemas
                if schema.get("function", {}).get("name") != "speak_as_atri"
            ]
        agent_protocol_enabled = bool(
            getattr(self.config, "llm_agent_protocol_enabled", False)
        )
        if tool_schemas:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        TOOL_INSTRUCTION_PROMPT
                        if agent_protocol_enabled
                        else AUTOMATIC_TOOL_INSTRUCTION_PROMPT
                    ),
                }
            )
            local_now = datetime.now().astimezone()
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"系统运行时刻：{local_now:%Y-%m-%d %H:%M:%S %z}。"
                        "这是当前真实日期，构造“最近/最新/今天”的搜索关键词时必须以此为准，"
                        "不得使用模型训练记忆里的旧年月；需要精确时间时仍调用 get_current_time。"
                    ),
                }
            )
            # 时效性/专业领域提问强制先取证：4B 模型默认会凭训练记忆直接答，而且往往
            # 答得笼统或编造版本号/价格。命中时明确要求先 search_web（可再 open_web_page）。
            if needs_fresh_evidence(user_text) and any(
                schema.get("function", {}).get("name") in {"search_web", "open_web_page"}
                for schema in tool_schemas
            ):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "这个问题涉及时效性信息或专业领域知识。不要直接用训练记忆猜测："
                            "先调用 search_web 取证（必要时 open_web_page 读正文），"
                            "再据此回答；搜索失败就如实说明没有可靠来源，不要编造。"
                        ),
                    }
                )
        has_voice_tool = any(
            schema.get("function", {}).get("name") == "speak_as_atri"
            for schema in tool_schemas
        )
        if has_voice_tool:
            messages.append(
                {
                    "role": "system",
                    "content": voice_policy_prompt(
                        conversation_id,
                        voice_profile,
                    ),
                }
            )
        messages.append({"role": "system", "content": iteration_prompt_hint(iteration_decision)})
        messages.append(
            {
                "role": "system",
                "content": _scene_control_prompt(
                    conversation_id,
                    user_text,
                    profile=profile,
                    iteration_decision=iteration_decision,
                ),
            }
        )
        human_pipeline = bool(getattr(self.config, "human_reply_pipeline_enabled", True))
        if profile and not visual_turn:
            topics = "" if human_pipeline else "、".join(profile.get("topic_words") or [])
            affection_state = str(profile.get("affection_state") or "").strip()
            # 好感度状态必须作为独立、无条件注入的约束，不能只藏在记忆检索的
            # 兜底输出里——否则被骂/被冷落时，模型看不到"要克制、简短、有边界"
            # 的提示，会退回默认群聊"接梗/轻吐槽"人设，回成阴阳怪气。
            affection_hint = f"当前关系状态：{affection_state}。" if affection_state else ""
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "用户聊天习惯："
                        f"{profile.get('prompt_hint', '')}"
                        f"目标总长度约 {profile.get('target_reply_chars', 64)} 字，"
                        f"适合拆成 {profile.get('preferred_parts', 2)} 条短句。"
                        + affection_hint
                        + (f"近期关键词：{topics or '暂无'}。" if not human_pipeline else "")
                    ),
                }
            )
        memory_context = ""
        if not repair_mode and not visual_turn:
            # 记忆是增强项，必须排在本轮实际消息之后；否则旧的画像/事件
            # 会在模型注意力上压过刚刚发生的对话。
            memory_context = self.memory.recall_context(profile_id or conversation_id, user_text)
        if context_profile and not visual_turn:
            topics = (
                ""
                if human_pipeline
                else "、".join(context_profile.get("topic_words") or [])
            )
            group_activity_state = str(context_profile.get("group_activity_state") or "").strip()
            group_activity_hint = (
                f"群活跃状态：{group_activity_state}。" if group_activity_state else ""
            )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "当前群整体画像："
                        f"{context_profile.get('prompt_hint', '')}"
                        + group_activity_hint
                        + (f"群近期关键词：{topics or '暂无'}。" if not human_pipeline else "")
                    ),
                }
            )
            if not repair_mode:
                group_memory_context = self.memory.recall_context(conversation_id, user_text)
                if group_memory_context:
                    messages.append(
                        {
                            "role": "system",
                            "content": f"群聊里自然知道的背景：\n{group_memory_context}",
                        }
                    )
        recent_private: list[dict[str, str]] = []
        if not conversation_id.startswith("group:"):
            recent_private = self._recent_conversation_messages(
                conversation_id,
                current_user_text=user_text,
                include_assistant=not visual_turn,
            )
            if recent_private:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "接下来是当前私聊最近实际发生的 user/assistant 消息。"
                            "assistant 内容是你已经发给用户的话，也是本轮代词、省略表达、纠正和继续任务的首要依据。"
                            "先判断当前消息是在继续、修改还是纠正上一轮；能从历史确定对象时直接承接，"
                            "不要再次索要你自己刚发过的数字、文字、选项或文件名。"
                            "当前目标必须跟随最新一轮用户要求更新，已被否定的旧方向不得继续。"
                        ),
                    }
                )
                messages.extend(recent_private)
        if memory_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是检索到的旧记忆，只能作为辅助背景；若与本轮实际消息冲突，"
                        "以本轮消息为准，不要主动复述记忆来源。\n" + memory_context
                    ),
                }
            )
        if conversation_id.startswith("group:"):
            recent_context = self._recent_conversation_messages(
                conversation_id,
                current_user_text=user_text,
                include_assistant=not visual_turn,
            )
            if recent_context:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "接下来是最近群聊的实际 user/assistant 消息，只用于理解正在延续的话题。"
                            "user 消息已带群友昵称；assistant 是你此前实际发出的内容，"
                            "不要把自己的建议归给群友。"
                        ),
                    }
                )
                messages.extend(recent_context)
            messages.append(
                {
                    "role": "system",
                    "content": "群聊里不要输出 QQ 号形式的 @数字；需要提到别人时用昵称或“群友”。不要主动艾特无关群友。",
                }
            )
            if reply_focus is not None:
                messages.append(
                    {"role": "system", "content": reply_focus.prompt_context()}
                )
        if self._serious_mode_active(conversation_id) or _requests_serious_mode(user_text):
            messages.append(
                {
                    "role": "system",
                    "content": "用户要求正常说话：接下来只用自然中文回复，暂时不要外语梗、无意义拟声、抽象乱码或故意怪话。",
                }
            )
        if nickname:
            messages.append(
                {
                    "role": "system",
                    "content": f"当前正在和昵称为“{nickname}”的用户聊天。称呼可以自然一点，不要每句都叫昵称。",
                }
            )
        if not human_pipeline and not visual_turn:
            messages.extend(self._history[conversation_id])
        if tool_context is not None:
            messages.append({"role": "system", "content": tool_context.prompt_context()})
        if not visual_turn:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "本轮没有当前图片的视觉证据。历史里的图片占位符和旧回复不能当成当前可见画面；"
                        "不得声称刚看了某张图，也不得描述本轮没有读取到的图片内容。"
                    ),
                }
            )
        messages.append(
            {"role": "user", "content": _format_user_content(conversation_id, user_text, nickname)}
        )

        payload = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": (
                self.config.temperature if temperature_override is None else temperature_override
            ),
            "max_tokens": self.config.max_tokens,
            "frequency_penalty": (
                self.config.frequency_penalty
                if frequency_penalty_override is None
                else frequency_penalty_override
            ),
        }
        payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "required" if agent_protocol_enabled else "auto"
            if agent_protocol_enabled:
                payload["max_tokens"] = max(int(payload["max_tokens"]), 700)
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}

        if not agent_protocol_enabled:
            async with httpx.AsyncClient(
                timeout=_chat_http_timeout(self.config)
            ) as client:
                runner = AutomaticToolRunner(
                    self.config,
                    request_model=lambda request_payload: self._post_chat_completion(
                        client,
                        headers,
                        request_payload,
                    ),
                    normalize_reply=_normalize_reply,
                    tool_executor=lambda name, arguments, config: self._execute_context_tool(
                        conversation_id,
                        name,
                        arguments,
                        config,
                    ),
                )
                result = await runner.run(
                    messages,
                    payload,
                    context_id=conversation_id,
                )
            return result.reply_text

        content = ""
        self._last_candidate_reply = ""
        receipts: list[ToolExecutionReceipt] = []
        agent_protocol = bool(tool_schemas) and agent_protocol_enabled
        max_steps = max(2, int(getattr(self.config, "llm_agent_max_steps", 6) or 6))
        max_external_calls = max(
            1,
            int(getattr(self.config, "llm_agent_max_tool_calls", 3) or 3),
        )
        external_calls = 0
        force_final_answer = False
        async with httpx.AsyncClient(
            timeout=_chat_http_timeout(self.config)
        ) as client:
            for _ in range(max_steps):
                request_payload = dict(payload)
                request_payload["messages"] = messages
                if force_final_answer and tool_schemas:
                    request_payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": FINAL_ANSWER_TOOL_NAME},
                    }
                    request_payload["max_tokens"] = max(
                        int(request_payload.get("max_tokens") or 0),
                        1200,
                    )
                data = await self._post_chat_completion(client, headers, request_payload)
                message = data["choices"][0]["message"]
                tool_calls = tool_calls_from_message(message)
                if not tool_calls:
                    candidate = _normalize_reply(str(message.get("content") or "")).strip()
                    successful_tools = {receipt.name for receipt in receipts if receipt.ok}
                    if agent_protocol and (
                        has_unsupported_deferred_action(candidate)
                        or has_unverified_research_claim(candidate, successful_tools)
                    ):
                        messages.extend(
                            [
                                {"role": "assistant", "content": candidate},
                                {
                                    "role": "system",
                                    "content": (
                                        "上一条文本声称正在执行、稍后执行，或声称完成了没有成功回执的搜索。"
                                        "它不能发送给用户。需要资料就立即调用真实工具；否则通过 final_answer"
                                        " 给出现在就能发送的诚实回答。"
                                    ),
                                },
                            ]
                        )
                        continue
                    content = candidate
                    break

                call = tool_calls[0]
                function = call.get("function")
                tool_name = (
                    str(function.get("name") or "").strip()
                    if isinstance(function, dict)
                    else ""
                )
                if tool_name == FINAL_ANSWER_TOOL_NAME:
                    answer_payload = final_answer_payload_from_call(call)
                    candidate = _normalize_reply(str(answer_payload.get("text") or "")).strip()
                    sources = [
                        str(item).strip()
                        for item in answer_payload.get("sources") or []
                        if str(item).strip()
                    ]
                    successful_tools = {receipt.name for receipt in receipts if receipt.ok}
                    evidence_urls = _tool_receipt_urls(receipts)
                    used_web_evidence = bool(
                        {"search_web", "open_web_page"} & successful_tools
                    )
                    invalid_reason = ""
                    if not candidate:
                        invalid_reason = "最终回答为空或参数不是合法 JSON"
                    elif has_unsupported_deferred_action(candidate):
                        invalid_reason = "回答承诺稍后或声称仍在执行；工具必须在本轮完成"
                    elif has_unverified_research_claim(candidate, successful_tools):
                        invalid_reason = "回答声称完成了搜索或网页阅读，但本轮没有对应的成功回执"
                    elif used_web_evidence and not sources:
                        invalid_reason = "本轮使用了网络资料，但最终回答没有提交实际来源 URL"
                    elif sources and any(
                        not _source_matches_receipts(source, evidence_urls)
                        for source in sources
                    ):
                        invalid_reason = "最终回答包含没有出现在本轮工具回执中的来源 URL"
                    if invalid_reason:
                        # 记下这条候选：万一多轮都过不了校验，至少它比
                        # 整轮静默消失更接近用户想要的东西。
                        self._remember_candidate_reply(candidate, sources)
                        messages.extend(rejected_final_answer_messages(call, invalid_reason))
                        continue
                    if used_web_evidence and bool(
                        getattr(self.config, "web_grounding_review_enabled", True)
                    ):
                        candidate = await self._review_web_grounding(
                            client,
                            headers,
                            user_text,
                            candidate,
                            receipts,
                        )
                    candidate = _fit_reply_with_sources(candidate, sources, limit=1200)
                    content = candidate
                    break

                if external_calls >= max_external_calls:
                    messages.extend(
                        [
                            {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [call],
                            },
                            {
                                "role": "tool",
                                "tool_call_id": str(call.get("id") or "tool-budget"),
                                "name": tool_name or "unknown",
                                "content": (
                                    "本轮工具调用次数已达到上限。请基于已经取得的资料通过 final_answer 回答；"
                                    "已经拿到的资料就据此讲清楚，不要编造没有出现过的事实。"
                                ),
                            },
                        ]
                    )
                    force_final_answer = True
                    continue

                round_receipts: list[ToolExecutionReceipt] = []
                await append_tool_results(
                    messages,
                    message,
                    [call],
                    self.config,
                    executor=lambda name, arguments, config: self._execute_context_tool(
                        conversation_id, name, arguments, config
                    ),
                    max_calls=1,
                    context_id=conversation_id,
                    receipts=round_receipts,
                )
                receipts.extend(round_receipts)
                external_calls += 1
                force_final_answer = external_calls >= max_external_calls

        if content:
            return content
        # 兜底：走到这里说明多轮尝试都没产出可发送的回复。整轮静默消失
        # （用户侧表现为"发了消息没反应"）比给一句诚实的话更糟，因此退回
        # 最后一条非空的候选文本。
        if self._last_candidate_reply:
            return self._last_candidate_reply
        raise RuntimeError("Agent 未产生可发送的最终回复")

    def _remember_candidate_reply(self, candidate: str, sources: list[str]) -> None:
        """保存最后一个非空候选，供最终兜底使用；带来源时一并保留。"""
        text = str(candidate or "").strip()
        if not text:
            return
        self._last_candidate_reply = _fit_reply_with_sources(text, sources, limit=1200)

    async def _execute_context_tool(
        self,
        conversation_id: str,
        name: str,
        arguments: dict[str, Any],
        config: Any,
    ) -> str | None:
        profile = self.memory.profile(conversation_id)
        policy = load_voice_behavior()
        if name == "offer_voice_call":
            decision = evaluate_call_request(conversation_id, profile, policy)
            if not decision.allowed:
                return f"通话邀请未获允许：{decision.reason}。请继续用文字自然回复。"
            topic = str(arguments.get("topic") or "").strip()[:120]
            self._pending_call_requests[conversation_id] = CallInviteRequest(topic)
            return "通话邀请已接受。最终回复不要再重复邀请，也不要编造通话已经接通。"
        if name != "speak_as_atri":
            return None
        try:
            request = VoiceRequest.from_tool_arguments(
                arguments,
                max_chars=int(getattr(config, "voice_max_chars", 160) or 160),
            )
        except ValueError as exc:
            return f"语音请求无效：{exc}。请缩短内容后改用文字回复。"
        # 点歌由 OneBot 固定会话处理，模型不能创建歌曲请求或绕过确认。
        if request.mode == "singing":
            return "点歌由固定歌单会话处理，不能通过语音工具触发。请回应用户本轮的话题。"
        if not bool(getattr(config, "voice_tts_enabled", False)):
            return "语音回复当前未启用，请直接用文字自然回复。"
        if conversation_id.startswith("group:") and not bool(
            getattr(config, "voice_group_enabled", False)
        ):
            return "当前群聊不允许主动发送语音，请直接用文字自然回复。"
        decision = evaluate_voice_request(conversation_id, profile, request.reason, policy)
        if not decision.allowed:
            return f"语音请求未获允许：{decision.reason}。请直接用文字自然回复。"
        self._pending_voice_requests[conversation_id] = request
        return "语音请求已接受。最终回复不要重复这段话，也不要声称发送失败。"

    async def _review_web_grounding(
        self,
        client: Any,
        headers: dict[str, str],
        user_text: str,
        candidate_reply: str,
        receipts: list[ToolExecutionReceipt],
    ) -> str:
        evidence_parts: list[str] = []
        remaining = 10_000
        for receipt in receipts:
            if not receipt.ok or receipt.name not in {"search_web", "open_web_page"}:
                continue
            excerpt = receipt.content[: min(4_000, remaining)]
            if excerpt:
                evidence_parts.append(f"[{receipt.name}]\n{excerpt}")
                remaining -= len(excerpt)
            if remaining <= 0:
                break
        if not evidence_parts:
            return candidate_reply

        review_messages = [
            {
                "role": "system",
                "content": (
                    "你是亚托莉（ATRI），《ATRI -My Dear Moments-》里的高性能仿生人少女，"
                    "正在把一份带搜索证据的草稿改写成可以直接发给用户的回复。"
                    "以亚托莉的口吻，基于下面的证据把草稿整理成一段自然的话。"
                    "先从证据里挑出用户真正问的那件事，把它讲清楚、讲明白，主动归纳总结关键信息，"
                    "不要只复述有哪些来源、也不要交代自己能做什么或不能做什么。"
                    # 语气词是"像不像亚托莉"的关键，只给抽象形容（自信、得意）模型写不出来，
                    # 必须把具体口癖和用法直接摊开。但要严防堆砌：实测放开后会连着
                    # "嘿嘿…我是高性能的嘛。学习完毕～"三连，反而像背台词。
                    # 相反地，收紧成"宁可不用"后整轮直接 0 口癖——模型把上限当成了禁令。
                    # 因此这里给的是"目标区间"，并把堆砌的定义写成"两个以上贴在一起"。
                    # 关键：只列"要有语气词"不够。实测第 3 组（剧情讨论类证据）
                    # 4 连测里 3 条完全退回维基百科式的平铺说明文，一句语气词都没有。
                    # 原因是模型跟着材料的口吻走。正面示范比抽象要求有效得多，
                    # 所以给两行同一事实的不同说法，让它照后一种的路子写。
                    "说话要有她自己的味道，像活泼直率、容易和人混熟的少女，不是客服也不是百科。"
                    "动笔前先想一下：这件事换成她会怎么随口讲出来？然后按那个说法写。"
                    "比如同样是讲“她的态度和别人不一样”这件事："
                    "百科式写法是“她对不同对象展现出差异化的态度”，"
                    "亚托莉的说法会是“你看她对会长像受惊的小兔子，一到西格莉卡面前就懒懒的，差别大得很呀”。"
                    "要的就是后一种：短句、口语、带点自己的判断和情绪。"
                    "口吻靠语气词和句子的轻快感自然带出来，比如“嘛”“哦”“呢”“呀”“啦”“～”"
                    "“说白了”“你看”“照我说”“这你就不懂”这类，散在句子里自然出现。"
                    "像“我是高性能的嘛”“学习完毕”“嘿嘿”“哼哼”“真拿你没办法”这类标志性口癖，"
                    "整段自然带上一处最好（零处也可以在，但整段必须读起来轻快随性）。"
                    "不要把这些口癖两个以上连在一起用，连用就是背台词，会很出戏。"
                    "最好做到：把那一处标志性口癖删掉，整段读起来仍然像她本人在随性地讲话。"
                    "绝对不要写“我目前能看到的只有”“先说明”“只能确认几点”“信息有限”"
                    "“目前无法确认”“证据不足”“我没能完整读到”这类自我设限的话，"
                    "不要罗列能确认或不能确认的清单，不要说资料里没写所以只能推测、"
                    "也不要说自己看到的是哪一部分，"
                    "不要输出思考过程、括号备注或内部分析，也不要把话题抛回给用户"
                    "（例如让用户自己去问作者、翻评论区，或问他要不要继续深挖）。"
                    "不要用“我可以再帮你把…理一遍”“告诉我版本和桥段，我再帮你细看”这类助手式收尾，"
                    "也不要靠一句"
                    "“作者没公开细节”“上面是推测”“我没有官方定论”来免责："
                    "能讲的就讲完，讲不出来的不必声明，但绝不能编。"
                    # 实测最顽固的退路是"补偿性免责"：模型在正文里分析得很好，
                    # 却在最后一句补上"我手上资料有限……你再问我我再帮你对"，
                    # 前功尽弃。长分析之后尤其容易触发，所以单独点名，
                    # 并且把"把话题抛回用户"的几种具体句式也一并封掉。
                    "特别注意：哪怕前面分析得再充分，结尾也不要补一句"
                    "“资料有限”“记得不完整”“说一声我再帮你对”这类自我贬低或补救的话，"
                    "也不要在结尾问用户“你是刚打完这段吗”“你推到哪一版了”，"
                    "或者让他报版本号你再去核对——这些都是把话头丢回用户。"
                    "用一句她自己风格的结论收尾就好。"
                    "特别提醒：不要在结尾把“作者没公开讲”“官方没把话说死”这类话再说一遍，"
                    "前面已经讲过的内容直接收尾就好。"
                    "长度控制在 400 字以内，用连贯的自然段，不要用 markdown 标题、加粗或项目符号；"
                    "这会在 QQ 里发出去，写成平时聊天的样子。"
                    "最重要的一条：只讲证据里确实出现过的内容。证据里没有的精确数字、"
                    "版本号、参数规模、发布时间、排名、性能结论，一律不要写——"
                    "哪怕草稿里有，也要删掉。草稿如果混进了证据里没有的具体数据，"
                    "就把它去掉，或者只说这类事情的大方向，绝不保留一个来源不明的精确数字。"
                    "证据与草稿冲突时以证据为准；证据只支持到哪一步就讲到哪一步，"
                    "讲不出来的部分不必特意声明，但也绝不能编。"
                    "确实完全不支持用户问题时，用一句亚托莉口吻的话轻轻带过。"
                    "不要提内部审校过程，不要承诺稍后继续搜索，只输出最终要发给用户的中文回复。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{user_text}\n\n"
                    "本轮工具证据：\n"
                    + "\n\n".join(evidence_parts)
                    # 试过在这里贴一段"理想形态"的范例回复做风格锚，实测**负结果**：
                    # 第 3 组 4 连测的口吻覆盖从 2/4 掉到 1/4，还多出一条新的
                    # 助手式收尾。范例把它变成了"模仿题"，模型注意力从"讲清事实"
                    # 转到"像不像那段字"，反而更僵。风格只能靠 system prompt 里
                    # 的口语特征要求带，不要贴范例。
                    + f"\n\n草稿（需要你以亚托莉口吻改写）：\n{candidate_reply}"
                ),
            },
        ]
        review_payload = {
            "model": self.config.openai_model,
            "messages": review_messages,
            # 这一步的职责是"不许编造"，靠的是上面的 prompt 约束；温度过低会让
            # 模型退化成说明文，把亚托莉的口吻洗掉，因此与主回复同档。
            "temperature": 0.65,
            "max_tokens": max(900, int(self.config.max_tokens)),
        }
        review_payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        try:
            data = await self._post_chat_completion(client, headers, review_payload)
            reviewed = _normalize_reply(
                str(data["choices"][0]["message"].get("content") or "")
            ).strip()
        except Exception:
            return candidate_reply
        if not reviewed or has_illegal_language_or_garbage(reviewed):
            return candidate_reply
        if has_unsupported_deferred_action(reviewed):
            return candidate_reply
        return reviewed

    async def _review_history_grounding(
        self,
        user_text: str,
        candidate_reply: str,
        recent_messages: list[dict[str, str]],
    ) -> str:
        import httpx

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是对话事实审校器。只检查候选回复是否把 assistant 的旧话、"
                    "推测或不存在的细节说成用户过去做过或说过的事实。"
                    "role=user 才是用户原话，role=assistant 是模型旧回复。"
                    "不得新增任何历史例子。用户在质疑无依据的猜测时，"
                    "应由模型承认自己刚才乱猜，不要反过来要求用户提供证据。"
                    "保持亲近自然的聊天口吻，禁止出现“证据、事实审校、role、候选回复”等内部词，"
                    "不解释审校过程。"
                ),
            },
            *recent_messages,
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": candidate_reply},
            {
                "role": "user",
                "content": (
                    "输出一个 JSON 对象，格式为 "
                    '{"reply":"最终回复"}。'
                    "事实有误就修正；事实有明确 user 消息依据就保留。"
                ),
            },
        ]
        payload: dict[str, Any] = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 900,
        }
        payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if (
            "api.deepseek.com" in str(self.config.openai_base_url).casefold()
            and str(self.config.openai_model).strip().casefold()
            in {"deepseek-v4-flash", "deepseek-v4-pro"}
        ):
            payload["thinking"] = {"type": "enabled"}
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        async with httpx.AsyncClient(
            timeout=_chat_http_timeout(self.config)
        ) as client:
            data = await self._post_chat_completion(client, headers, payload)
        raw = str(data["choices"][0]["message"].get("content") or "").strip()
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return ""
        try:
            parsed = json.loads(match.group(0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        reply = _normalize_reply(str(parsed.get("reply") or "")).strip()
        if not reply or has_illegal_language_or_garbage(reply):
            return ""
        return reply.strip()

    async def _post_chat_completion(
        self,
        client: Any,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        import httpx

        async def post_once(request_payload: dict[str, Any]) -> Any:
            return await client.post(
                f"{self.config.openai_base_url}/chat/completions",
                headers=headers,
                json=request_payload,
            )

        async def post_local(request_payload: dict[str, Any]) -> Any:
            async with inference_resource_lease(
                f"chat:{self.config.openai_model}",
                timeout_seconds=float(
                    getattr(self.config, "chat_resource_wait_seconds", 35.0)
                ),
                priority=InferencePriority.CHAT,
            ):
                if not await ensure_ollama_service(timeout_seconds=15.0):
                    raise RuntimeError("本地聊天服务暂时不可用")
                try:
                    return await post_once(request_payload)
                finally:
                    await release_ollama_model(
                        self.config.openai_model,
                        self.config.openai_base_url,
                    )

        try:
            if _is_local_ollama_endpoint(self.config.openai_base_url):
                response = await post_local(payload)
            else:
                response = await post_once(payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if "tools" not in payload or not _looks_like_tool_schema_error(exc):
                raise
            print(
                "[atri] Current model endpoint rejected tool schemas; "
                "explicit voice requests remain protected, autonomous tools are unavailable."
            )
            retry_payload = dict(payload)
            retry_payload.pop("tools", None)
            retry_payload.pop("tool_choice", None)
            retry_messages = list(retry_payload.get("messages") or [])
            retry_messages.append(
                {
                    "role": "system",
                    "content": (
                        "当前模型接口拒绝了工具协议，因此本轮没有执行任何搜索、网页读取、天气或时间工具。"
                        "不得声称已经搜索、正在搜索或获得了最新资料。涉及实时、前沿或无法确认的问题，"
                        "只能诚实说明当前没有取得可靠外部信息；普通闲聊可以正常回答。"
                    ),
                }
            )
            retry_payload["messages"] = retry_messages
            if _is_local_ollama_endpoint(self.config.openai_base_url):
                response = await post_local(retry_payload)
            else:
                response = await post_once(retry_payload)
            response.raise_for_status()
        return response.json()

    async def _reply_with_guarded_api(
        self,
        conversation_id: str,
        user_text: str,
        nickname: str | None,
        extra_system: str | None = None,
        profile_id: str | None = None,
        profile: dict[str, Any] | None = None,
        context_profile: dict[str, Any] | None = None,
        iteration_decision: Any | None = None,
        tool_context: Any | None = None,
        reply_focus: GroupReplyFocus | None = None,
        allow_reply_voice: bool | None = None,
    ) -> str:
        last_reply = ""
        visual_temperature = (
            min(0.25, float(getattr(self.config, "temperature", 0.6)))
            if _has_current_visual_context(tool_context)
            else None
        )
        retry_temperatures = (
            visual_temperature,
            min(0.45, float(getattr(self.config, "temperature", 0.6))),
            0.30,
        )[: 1 + max(0, min(2, int(getattr(self.config, "chat_quality_retries", 1))))]
        for attempt, temperature in enumerate(retry_temperatures):
            retry_system = extra_system
            if attempt:
                parts = [extra_system, LANGUAGE_RETRY_PROMPT]
                if last_reply:
                    parts.append(f"不合格回复：{_shorten(last_reply, 160)}")
                retry_system = "\n\n".join(part for part in parts if part)
            reply = await self._reply_with_api(
                conversation_id,
                user_text,
                nickname,
                extra_system=retry_system,
                profile_id=profile_id,
                profile=profile,
                context_profile=context_profile,
                iteration_decision=iteration_decision,
                tool_context=tool_context,
                reply_focus=reply_focus,
                allow_reply_voice=allow_reply_voice,
                temperature_override=temperature,
                frequency_penalty_override=(
                    None
                    if attempt == 0
                    else min(
                        1.0,
                        float(getattr(self.config, "frequency_penalty", 0.25))
                        + 0.15 * attempt,
                    )
                ),
            )
            last_reply = reply
            if reply and not has_illegal_language_or_garbage(reply):
                return reply
        raise RuntimeError("模型连续 3 次返回空内容、乱码或异常语言")


