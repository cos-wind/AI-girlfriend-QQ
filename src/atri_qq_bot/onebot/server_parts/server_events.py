from __future__ import annotations

import logging
import time

from .server_support import OneBotServerMixin, _sync_server_globals

# 显式导入而不是依赖 _sync_server_globals 的全局注入：注入只在**实例**属性访问时
# 才把 server.py 的名字塞进本模块，直接以类方法调用（测试、脚本）时会 NameError。
from ..message_parser import group_increase_text  # type: ignore[import-not-found]
from ...runtime.reply_strategy import (  # type: ignore[import-not-found]
    forced_event_block_reason,
    object_requires_mention,
)

# 运行时会由 _sync_server_globals 注入 server.py 的同名 logger；这里显式声明一份，
# 便于模块被单独导入（单元测试）时也能正常记录。
LOGGER = logging.getLogger("atri.onebot")


class OneBotEventMixin(OneBotServerMixin):
    async def _resolve_group_increase_name(
        self, websocket: Any, event: dict[str, Any]
    ) -> dict[str, Any]:
        """入群通知不带昵称，额外问一次 QQ 内核；失败就退回 QQ 号。

        纯增益步骤：拿不到昵称也必须照常欢迎，所以这里把所有异常都吞掉。
        群名片优先于昵称——群里显示的就是群名片。
        """
        info = dict(event.get("_atri_group_increase_member") or {})
        group_id = info.get("group_id") or event.get("group_id")
        user_id = info.get("user_id") or event.get("user_id")
        name = str(info.get("nickname") or "").strip()

        if not name and group_id is not None and user_id is not None:
            try:
                result = await self.call_action_and_wait(
                    websocket,
                    "get_group_member_info",
                    {
                        "group_id": int(group_id),
                        "user_id": int(user_id),
                        "no_cache": False,
                    },
                    5.0,
                )
                data = result.get("data") if isinstance(result, dict) else None
                if isinstance(data, dict):
                    name = str(data.get("card") or data.get("nickname") or "").strip()
            except Exception as exc:
                LOGGER.debug("读取新成员昵称失败，改用 QQ 号：%s", exc)

        # 无论名字来自通知还是刚查到的，都用**同一个格式函数**重写文本。
        # 不这样做的话，"通知自带昵称"这条路径会依赖归一化阶段生成的文本，
        # 形成一处看不见的耦合（测试抓到过）。
        text = group_increase_text(name, user_id)
        enriched = dict(event)
        enriched["message"] = [{"type": "text", "data": {"text": text}}]
        enriched["raw_message"] = text
        enriched["_atri_group_increase_member"] = {**info, "nickname": name}
        return enriched

    async def _handle_event(self, websocket: Any, event: dict[str, Any]) -> None:
        """执行一次完整的入站消息决策和回复流程。"""
        # 补昵称要在抽取纯文本之前——否则回复链路拿到的还是"QQ 号"版本。
        if event.get("_atri_group_increase_event"):
            event = await self._resolve_group_increase_name(websocket, event)

        plain_text = extract_plain_text(event.get("message"))
        poke_event = bool(event.get("_atri_poke_event"))
        # 入群通知归一化后也是普通群消息，但和戳一戳一样**强制回复**——
        # 否则群聊默认策略不会理一条没有 @ 的消息，欢迎就发不出去。
        join_event = bool(event.get("_atri_group_increase_event"))
        push_event = poke_event or join_event
        is_message = (
            event.get("post_type") == "message"
            and _as_int(event.get("user_id")) != self.config.bot_qq
            and _as_int(event.get("self_id")) in {None, self.config.bot_qq}
        )

        if poke_event and not self._allow_poke_reply(event):
            LOGGER.info(
                "戳一戳回复进入冷却：conversation=%s user=%s",
                _conversation_id(event),
                event.get("user_id"),
            )
            return

        preliminary_reply = push_event or should_reply(
            event,
            self.config.bot_qq,
            self.config.reply_mode,
            self.config.owner_qqs,
        )
        active_group_continuation = False
        explicit_group_mention = bool(
            is_message
            and event.get("message_type") == "group"
            and not push_event
            and is_bot_mentioned(event, self.config.bot_qq, plain_text)
        )
        if explicit_group_mention:
            # 「仅 @ 回复」的群不存在"续聊"：会话一旦打开，该成员之后的表情和插话
            # 都会被当成续聊（is_continuation）绕过 @ 检查，而且每次命中还会滑动续期。
            # 这里直接不打开会话，让"每轮都要 @ "的语义从源头成立。
            if not object_requires_mention(
                scope="group",
                user_id=str(event.get("user_id") or ""),
                group_id=str(event.get("group_id") or ""),
            ):
                self._group_reply_focus.open_session(
                    event,
                    nickname=_nickname(event) or "",
                )
        elif is_message and event.get("message_type") == "group" and not push_event:
            active_group_continuation = self._group_reply_focus.is_active_continuation(
                event,
                plain_text,
            )
            preliminary_reply = preliminary_reply or active_group_continuation
        voice_transcript = None
        voice_error: Exception | None = None
        if is_message and (event.get("message_type") == "private" or preliminary_reply):
            try:
                voice_transcript = await self.voice.transcribe_event(
                    event,
                    lambda action, params: self.call_action_and_wait(
                        websocket,
                        action,
                        params,
                        self.config.voice_service_timeout_seconds,
                    ),
                )
            except Exception as exc:
                voice_error = exc
                print(f"[onebot] Voice transcription skipped: {exc}")
        if voice_transcript is not None:
            plain_text = voice_transcript.text

        if is_message:
            with contextlib.suppress(Exception):
                await self.stickers.capture_from_event(
                    event,
                    plain_text,
                    self.config.sticker_capture_enabled,
                    self.config.sticker_capture_max_bytes,
                )

        should_send_reply = preliminary_reply
        conversation_id = _conversation_id(event)
        if is_message:
            self._remember_pending_group_visual(event)
        # 入群事件**刻意绕开下面三道限流**（用户明确要求"入群必回"）：
        # 群内 75 秒冷却、blocked 档案、回复策略的**频率**门控。语义上它是一次"事件"
        # 而不是一次群聊插话——同一批人陆续进群时不该因为刚回过话就漏掉欢迎。
        # 唯一的例外是对象级模式（禁止回复 / 只记录 / 仅 @ 回复）：那表达的是"这个对象
        # 不该被主动搭话"，优先级高于"入群必回"，在下面单独判定。
        if (
            should_send_reply
            and not active_group_continuation
            and not join_event
            and not self._smart_group_reply_allowed(
                event,
                conversation_id,
                plain_text,
            )
        ):
            should_send_reply = False
        profile_id = _profile_id(event)
        nickname = _nickname(event)
        is_owner = _as_int(event.get("user_id")) in set(self.config.owner_qqs)
        trust_tier = getattr(self.reply_engine.memory, "trust_tier", None)
        if (
            is_message
            and not join_event
            and not is_owner
            and callable(trust_tier)
            and trust_tier(profile_id) == "blocked"
        ):
            should_send_reply = False
        if should_send_reply and join_event:
            # 入群欢迎没有 @、也不构成续聊，因此不会被下面的策略门控拦住。对象级模式
            # 必须在这里单独生效，否则"只记录"和"仅 @ 回复"的群会继续收到入群欢迎
            # ——实测 19:16 的那条欢迎就是在 quiet（只记录）模式下发出去的。
            # （戳一戳不需要在这里判：它没被排除在下面的门控之外，已经受对象策略约束。）
            forced_block = forced_event_block_reason(
                scope="group" if event.get("message_type") == "group" else "private",
                user_id=str(event.get("user_id") or ""),
                group_id=str(event.get("group_id") or ""),
                is_owner=is_owner,
            )
            if forced_block:
                LOGGER.info(
                    "强制事件被对象策略拦截：conversation=%s user=%s group=%s reason=%s",
                    conversation_id,
                    event.get("user_id"),
                    event.get("group_id"),
                    forced_block,
                )
                should_send_reply = False
        # 回复策略（按对象/好感度/活跃度的门控与频率上限）在策略启用时才生效；
        # strategy_limits 同时承载本轮的长度策略，None 表示策略未启用。
        strategy_limits: dict[str, Any] | None = None
        if is_message and should_send_reply and not join_event:
            decision = self._evaluate_reply_strategy(
                event,
                profile_id=profile_id,
                plain_text=plain_text,
                is_owner=is_owner,
                is_continuation=active_group_continuation,
            )
            if not decision.allowed:
                LOGGER.info(
                    "回复策略拦截：conversation=%s user=%s group=%s reason=%s",
                    conversation_id,
                    event.get("user_id"),
                    event.get("group_id"),
                    decision.reason,
                )
                should_send_reply = False
            elif decision.strategy:
                strategy_limits = decision.strategy
        addressed_to_bot = (
            event.get("message_type") == "private"
            or push_event
            or (
                event.get("message_type") == "group"
                and (should_send_reply or is_bot_mentioned(event, self.config.bot_qq, plain_text))
            )
        )
        group_reply_focus = None
        if is_message and event.get("message_type") == "group" and not push_event:
            group_reply_focus = self._group_reply_focus.resolve(
                event,
                plain_text,
                nickname=nickname or "",
                addressed_to_bot=addressed_to_bot,
            )
            if active_group_continuation and group_reply_focus is not None:
                group_reply_focus = replace(group_reply_focus, source="active_session")
            if not addressed_to_bot:
                self._group_reply_focus.remember(
                    event,
                    plain_text,
                    nickname=nickname or "",
                    addressed_to_bot=False,
                )

        if is_message:
            self._log_message_decision(event, plain_text, should_send_reply)
            LOGGER.info(
                "消息决策：conversation=%s reply=%s mode=%s",
                conversation_id,
                should_send_reply,
                self.config.reply_mode,
            )

        if is_message:
            self.reply_engine.remember_target(conversation_id, event)
            if profile_id != conversation_id:
                self.reply_engine.remember_target(profile_id, event)

            if event.get("message_type") == "group":
                self.reply_engine.observe_group_incoming(
                    event.get("group_id"),
                    event.get("user_id"),
                    plain_text,
                    nickname,
                    runtime_context=(
                        self.config.group_context_enabled and not should_send_reply
                    ),
                    addressed_to_bot=addressed_to_bot,
                    is_owner=is_owner,
                )
            else:
                self.reply_engine.observe_incoming(
                    conversation_id,
                    plain_text,
                    nickname,
                    actor_id=event.get("user_id"),
                    runtime_context=False,
                    profile_id=profile_id,
                    event_id=str(event.get("message_id") or "") or None,
                )

        if not should_send_reply:
            return

        # 常见点歌表达在聊天模型之前处理。它们只读取 data/music 直属的成品，
        # 不受模型工具调用、TTS 开关或群聊提示词影响，也不会用文字假装唱歌。
        turn_id = str(event.get("message_id") or uuid.uuid4().hex)
        singing_decision = self.singing.resolve(profile_id, plain_text)
        if singing_decision.handled and not is_event_modality_allowed(event, "voice"):
            # 点歌属于语音模型能力；未授权时回到普通文本回复，不读取或发送音频。
            LOGGER.info("语音白名单拒绝点歌：user=%s group=%s", event.get("user_id"), event.get("group_id"))
            singing_decision = replace(singing_decision, handled=False)
        if singing_decision.handled:
            if self.cognition_shadow is not None:
                self.cognition_shadow.submit(
                    ConversationTurnRequest(
                        turn_id=turn_id,
                        conversation_id=conversation_id,
                        profile_id=profile_id,
                        kind="group" if event.get("message_type") == "group" else "private",
                        user_text=plain_text,
                        nickname=nickname,
                        actor_id=str(event.get("user_id") or "") or None,
                        addressed_to_bot=addressed_to_bot,
                    ),
                    profile=self.reply_engine.profile_for(profile_id),
                )
            outgoing, fallback_text = self._singing_outgoing(
                event,
                plain_text,
                singing_decision,
            )
            delivered_text = await self.send_reply(
                websocket,
                event,
                outgoing,
                fallback_text=fallback_text or None,
                first_delay=False,
                model_type="voice",
                model_name=self._delivery_model_name("voice"),
            )
            if outgoing and not delivered_text:
                self._record_reply_failure(
                    event,
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    user_text=plain_text,
                    model_reply=singing_decision.reply_text,
                    reason="歌曲语音或文本发送失败",
                    model_type="voice",
                    model_name=self._delivery_model_name("voice"),
                )
                return
            recorded_reply = delivered_text
            if self.cognition_shadow is not None:
                self.cognition_shadow.record_live_outcome(
                    turn_id,
                    reply_text=singing_decision.reply_text,
                    delivered_text=recorded_reply,
                    voice_mode="singing" if singing_decision.song else "",
                )
            self._mark_smart_group_reply(event, conversation_id, plain_text)
            self.reply_engine.record_bot_reply(
                conversation_id,
                recorded_reply,
                False,
                profile_id=profile_id,
            )
            self._log_reply_event(
                event,
                conversation_id=conversation_id,
                user_text=plain_text,
                model_reply="",
                delivered_reply=recorded_reply,
                voice_mode="singing" if singing_decision.song else "",
                reply_focus_source=str(getattr(group_reply_focus, "source", "") or ""),
                reply_focus_text=str(getattr(group_reply_focus, "focus_text", "") or ""),
            )
            return

        if group_reply_focus is not None and group_reply_focus.source == "previous_same_sender":
            analysis_event = group_reply_focus.analysis_event
            self._pending_group_visual_events.pop(_pending_visual_key(event), None)
        else:
            analysis_event = self._event_with_pending_group_visual(event)

        quoted_message_id, quoted_text, quoted_segments = await self._resolve_quoted_message(
            websocket,
            event,
        )
        if quoted_segments:
            analysis_event = self._event_with_quoted_message(
                analysis_event,
                quoted_segments,
            )
        model_input_text = _compose_model_input(plain_text, quoted_text)
        voice_only_text = plain_text.replace("@群友", "").strip()
        if (
            voice_error is not None
            and find_record_segments(event.get("message"))
            and voice_only_text == "[语音]"
        ):
            self._record_reply_failure(
                event,
                turn_id=turn_id,
                conversation_id=conversation_id,
                user_text=model_input_text,
                model_reply="",
                reason=f"语音识别失败：{voice_error}",
                model_type="voice",
                model_name=self._delivery_model_name("voice"),
            )
            return

        has_current_visual = _event_has_visual_material(analysis_event)
        if has_current_visual:
            self._recent_visual_contexts.pop(conversation_id, None)

        tool_context = None
        vision_allowed = is_event_modality_allowed(event, "vision")
        try:
            tool_context = await self.tools.analyze(
                analysis_event,
                model_input_text,
                lambda action, params: self.call_action_and_wait(
                    websocket,
                    action,
                    params,
                    self.config.toolbox_timeout_seconds,
                ),
                allow_vision=vision_allowed,
            )
        except Exception as exc:
            LOGGER.warning("多模态/工具分析跳过：conversation=%s error=%s", conversation_id, exc)
        if tool_context is not None and conversation_id.startswith("private:"):
            try:
                from ...knowledge.ingestion import archive_analysis

                knowledge = getattr(self.reply_engine.memory, "knowledge", None)
                if knowledge is not None:
                    archive_analysis(knowledge, conversation_id, tool_context,
                                     event_id=str(event.get("message_id") or ""), occurred_at=event.get("time"))
            except Exception as exc:
                LOGGER.warning("资料存档失败：conversation=%s error=%s", conversation_id, exc)
        if vision_allowed and tool_context is None and _should_reuse_cached_visual(
            analysis_event,
            model_input_text,
        ):
            cached = self._recent_visual_contexts.get(conversation_id)
            if cached and time.time() - cached[0] <= VISUAL_CONTEXT_TTL_SECONDS:
                try:
                    if getattr(cached[1], "visual_data", None):
                        tool_context = await self.tools.analyze_visual_followup(
                            cached[1],
                            model_input_text,
                            allow_vision=vision_allowed,
                        )
                except Exception as exc:
                    LOGGER.warning("图片追问分析失败：conversation=%s error=%s", conversation_id, exc)
                if tool_context is None:
                    tool_context = cached[1]
            elif cached:
                self._recent_visual_contexts.pop(conversation_id, None)
        if tool_context is not None and (
            has_current_visual or getattr(tool_context, "visual_data", None)
        ):
            self._recent_visual_contexts[conversation_id] = (time.time(), tool_context)
            if len(self._recent_visual_contexts) > 256:
                oldest = min(
                    self._recent_visual_contexts,
                    key=lambda key: self._recent_visual_contexts[key][0],
                )
                self._recent_visual_contexts.pop(oldest, None)
        if voice_transcript is not None:
            tool_context = VoicePromptContext(
                voice_transcript,
                material_context=tool_context,
                prefer_voice_reply=bool(self.config.voice_reply_to_voice),
            )

        if self.cognition_shadow is not None:
            request = ConversationTurnRequest(
                turn_id=turn_id,
                conversation_id=conversation_id,
                profile_id=profile_id,
                kind="group" if event.get("message_type") == "group" else "private",
                user_text=model_input_text,
                nickname=nickname,
                actor_id=str(event.get("user_id") or "") or None,
                quoted_text=quoted_text,
                reply_focus_source=str(getattr(group_reply_focus, "source", "") or ""),
                reply_focus_text=str(getattr(group_reply_focus, "focus_text", "") or ""),
                addressed_to_bot=addressed_to_bot,
            )
            profile_snapshot = self.reply_engine.profile_for(profile_id)
            self.cognition_shadow.submit(
                request,
                evidence_from_tool_context(tool_context),
                profile=profile_snapshot,
            )

        try:
            reply_text = await self.reply_engine.reply(
                conversation_id,
                model_input_text,
                nickname,
                profile_id=profile_id,
                observed=True,
                tool_context=tool_context,
                reply_focus=group_reply_focus,
                extra_system=self._reply_strategy_system_prompt(strategy_limits),
            )
        except Exception as exc:
            LOGGER.exception("回复引擎异常：conversation=%s", conversation_id)
            reply_text = ""
            failure_reason = f"{type(exc).__name__}: {exc}"
        else:
            consume_failure = getattr(self.reply_engine, "consume_reply_failure", None)
            failure_reason = (
                str(consume_failure(conversation_id) or "").strip()
                if callable(consume_failure)
                else ""
            )
        if not str(reply_text or "").strip():
            reason = failure_reason or "回复引擎返回空结果"
            self._record_reply_failure(
                event,
                turn_id=turn_id,
                conversation_id=conversation_id,
                user_text=model_input_text,
                model_reply="",
                reason=reason,
                tool_context=tool_context,
                reply_focus=group_reply_focus,
                quoted_message_id=quoted_message_id,
                model_type=("vision" if has_current_visual or getattr(tool_context, "visual_data", None) else "chat"),
                model_name=self._delivery_model_name("vision" if has_current_visual or getattr(tool_context, "visual_data", None) else "chat"),
            )
            if self.cognition_shadow is not None:
                self.cognition_shadow.record_live_outcome(
                    turn_id,
                    reply_text="",
                    delivered_text="",
                    voice_mode="",
                )
            return
        voice_request = self.reply_engine.consume_voice_request(conversation_id)
        consume_reply_voice_choice = getattr(
            self.reply_engine,
            "consume_reply_voice_choice",
            None,
        )
        autonomous_voice_selected = bool(
            consume_reply_voice_choice(conversation_id)
            if callable(consume_reply_voice_choice)
            else False
        )
        if voice_request is not None:
            voice_request = stabilize_explicit_voice_request(
                plain_text,
                voice_request,
                max_chars=int(self.config.voice_max_chars),
            )
            voice_request = sanitize_voice_request(
                voice_request,
                max_chars=int(self.config.voice_max_chars),
            )
            if voice_request.mode == "speech" and not voice_request.text:
                # 只有动作/思考、没有可朗读正文时，宁可回普通文本也不把空内容送进 TTS。
                voice_request = None
        if voice_request is None and bool(self.config.voice_tts_enabled):
            policy = load_voice_behavior()
            profile = self.reply_engine.profile_for(profile_id)
            guarded_request = build_explicit_voice_fallback(
                plain_text,
                reply_text,
                max_chars=int(self.config.voice_max_chars),
            )
            if (
                guarded_request is not None
                and bool(policy.get("explicit_delivery_guard_enabled", True))
                and (
                    event.get("message_type") != "group"
                    or bool(self.config.voice_group_enabled)
                )
                and evaluate_voice_request(
                    conversation_id,
                    profile,
                    guarded_request.reason,
                    policy,
                ).allowed
            ):
                voice_request = guarded_request
            if voice_request is None and autonomous_voice_selected:
                autonomous_request = build_autonomous_voice_fallback(
                    plain_text,
                    reply_text,
                    max_chars=int(self.config.voice_max_chars),
                    reason="voice_reply" if voice_transcript is not None else "autonomous",
                )
                if (
                    autonomous_request is not None
                    and (
                        event.get("message_type") != "group"
                        or bool(self.config.voice_group_enabled)
                    )
                    and evaluate_voice_request(
                        conversation_id,
                        profile,
                        autonomous_request.reason,
                        policy,
                    ).allowed
                ):
                    voice_request = autonomous_request
        # 点歌只允许上面的固定会话入口；模型工具和旧请求不能绕过歌单确认。
        if voice_request is not None and voice_request.mode != "speech":
            voice_request = None
        if voice_request is not None and not is_event_modality_allowed(event, "voice"):
            # 保留本轮文字回复，但不进入 TTS，避免未授权用户消耗语音服务资源。
            LOGGER.info("语音白名单拒绝 TTS：user=%s group=%s", event.get("user_id"), event.get("group_id"))
            voice_request = None
        consume_call = getattr(self.reply_engine, "consume_call_request", None)
        call_request = consume_call(conversation_id) if callable(consume_call) else None
        if call_request is not None and not is_event_modality_allowed(event, "voice"):
            LOGGER.info("语音白名单拒绝通话邀请：user=%s group=%s", event.get("user_id"), event.get("group_id"))
            call_request = None
        spoken_text = ""
        voice_streamed = False
        delivered_text = ""
        if call_request is not None:
            policy = load_voice_behavior()
            session = self.voice_calls.create(
                conversation_id,
                call_request.topic,
                int(policy["call_expiry_minutes"]),
                int(policy["call_max_minutes"]),
            )
            call_url = f"{str(policy['call_base_url']).rstrip('/')}/voice-call?token={session.token}"
            topic_text = f"想继续聊聊“{call_request.topic}”。" if call_request.topic else "想和你继续说说话。"
            outgoing = [
                OutgoingMessage(
                    "text",
                    f"{topic_text}点这里接通语音：{call_url}\n邀请 {policy['call_expiry_minutes']} 分钟内有效。",
                )
            ]
        elif voice_request is not None:
            spoken_text = voice_request.text
            delivered_text = await self._send_streamed_speech_reply(
                websocket,
                event,
                conversation_id,
                voice_request,
            )
            outgoing = []
            voice_streamed = True
        else:
            profile = self.reply_engine.profile_for(profile_id)
            outgoing = build_outgoing_messages(
                reply_text,
                plain_text,
                self.stickers,
                self.config,
                profile,
            )
        delivery_model_type = (
            "voice"
            if voice_transcript is not None or voice_request is not None or voice_streamed
            else "vision"
            if has_current_visual or getattr(tool_context, "visual_data", None)
            else "chat"
        )
        delivery_model_name = self._delivery_model_name(delivery_model_type)
        sent_sticker = any(message.kind in {"image", "sticker", "face"} for message in outgoing)
        if not voice_streamed:
            delivered_text = await self.send_reply(
                websocket,
                event,
                outgoing,
                fallback_text=spoken_text or None,
                model_type=delivery_model_type,
                model_name=delivery_model_name,
            )
        if (voice_streamed or outgoing) and not delivered_text:
            self._record_reply_failure(
                event,
                turn_id=turn_id,
                conversation_id=conversation_id,
                user_text=model_input_text,
                model_reply=reply_text,
                reason="OneBot 未确认消息发送成功",
                tool_context=tool_context,
                reply_focus=group_reply_focus,
                quoted_message_id=quoted_message_id,
                model_type=delivery_model_type,
                model_name=delivery_model_name,
            )
            if self.cognition_shadow is not None:
                self.cognition_shadow.record_live_outcome(
                    turn_id,
                    reply_text=reply_text,
                    delivered_text="",
                    voice_mode=getattr(voice_request, "mode", "") if voice_request else "",
                )
            return
        self._mark_smart_group_reply(event, conversation_id, plain_text)
        if strategy_limits is not None:
            # 只在真正把消息发出去之后才计数，失败/空回复不消耗配额。
            record_reply(
                scope="group" if event.get("message_type") == "group" else "private",
                user_id=str(event.get("user_id") or ""),
                group_id=str(event.get("group_id") or ""),
            )
        recorded_reply = delivered_text
        if self.cognition_shadow is not None:
            self.cognition_shadow.record_live_outcome(
                turn_id,
                reply_text=reply_text,
                delivered_text=recorded_reply,
                voice_mode=getattr(voice_request, "mode", "") if voice_request else "",
            )
        self.reply_engine.record_bot_reply(
            conversation_id,
            recorded_reply,
            sent_sticker,
            profile_id=profile_id,
        )
        self._log_reply_event(
            event,
            conversation_id=conversation_id,
            user_text=plain_text,
            model_reply=reply_text,
            delivered_reply=recorded_reply,
            voice_mode=getattr(voice_request, "mode", "") if voice_request else "",
            material_read_level=str(getattr(tool_context, "read_level", "") or ""),
            reply_focus_source=str(getattr(group_reply_focus, "source", "") or ""),
            reply_focus_text=str(getattr(group_reply_focus, "focus_text", "") or ""),
            quoted_message_id=quoted_message_id,
        )
        if self.insights is not None:
            # submit 只创建一个后台持久化任务；SQLite、向量模型和 DeepSeek
            # 都在独立 worker 中执行，不延长本轮 QQ 回复耗时。
            self.insights.submit_evaluation(
                EvaluationSample(
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    group_id=str(event.get("group_id") or ""),
                    question=model_input_text,
                    answer=reply_text,
                    context=context_from_tool_context(tool_context),
                    model_type=delivery_model_type,
                    model_name=delivery_model_name,
                )
            )

    def _evaluate_reply_strategy(
        self,
        event: dict[str, Any],
        *,
        profile_id: str,
        plain_text: str,
        is_owner: bool,
        is_continuation: bool,
    ) -> ReplyDecision:
        """读取好感度/群活跃度后交给回复策略判定。

        策略文件由 WebUI 写入；策略未启用、或记忆层读不到数据时一律放行，
        保证"策略坏了也不会让亚托莉突然不理人"。
        """

        policy = load_reply_strategy()
        if not policy.get("enabled"):
            return ReplyDecision(True, "策略未启用", {})
        scope = "group" if event.get("message_type") == "group" else "private"
        group_id = str(event.get("group_id") or "") if scope == "group" else ""
        user_id = str(event.get("user_id") or "")
        affection: float | None = None
        activity: float | None = None
        active_days: float | None = None
        message_count: int | None = None
        memory = getattr(self.reply_engine, "memory", None)
        now = time.time()
        try:
            if memory is not None:
                user_state = memory.proactive_state(profile_id, is_owner)
                affection = float(user_state.get("affection_score") or 0.0)
                message_count = int(user_state.get("message_count") or 0)
                last_user_at = float(user_state.get("last_user_at") or 0.0)
                if scope == "private" and last_user_at:
                    active_days = max(0.0, (now - last_user_at) / 86400.0)
                if scope == "group":
                    # 群门槛看群自己的活跃度/消息量/沉默天数，而不是某个成员的。
                    group_state = memory.proactive_state(f"group:{group_id}")
                    activity = float(group_state.get("group_activity_score") or 0.0)
                    message_count = int(group_state.get("message_count") or 0)
                    group_last_at = float(group_state.get("last_user_at") or 0.0)
                    if group_last_at:
                        active_days = max(0.0, (now - group_last_at) / 86400.0)
        except Exception as exc:  # 记忆读取失败只降级为"不作门槛判断"
            LOGGER.debug("回复策略读取记忆失败：%s", exc)
        return evaluate_reply(
            scope=scope,
            user_id=user_id,
            group_id=group_id,
            affection=affection,
            activity=activity,
            active_days=active_days,
            message_count=message_count,
            is_mention=is_bot_mentioned(event, self.config.bot_qq, plain_text),
            is_owner=is_owner,
            is_continuation=is_continuation,
            policy=policy,
            now=now,
        )

    def _reply_strategy_system_prompt(
        self, strategy_limits: dict[str, Any] | None
    ) -> str | None:
        """把对象策略里的长度要求转成一条系统提示。

        已回退：不再把「总长 X 字 / 最多 Y 条」作为**死命令**注入系统提示词——那会
        与人设的长回复风格冲突，导致内容偏移、截断、甚至把工具调用 JSON 当正文发出。
        长度与详略交给人格系统提示词 + 模型的"约 N 字"软引导，投递层再用拆分上限兜底。
        """

        return None


