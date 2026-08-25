from __future__ import annotations

from .server_support import OneBotServerMixin, _sync_server_globals


class OneBotDeliveryMixin(OneBotServerMixin):
    async def send_group_summary(self, group_id: str, image_path: str) -> None:
        """将总结 PNG 作为 QQ 图片消息发送到对应群聊。"""
        websocket = self._first_active_websocket()
        if websocket is None:
            raise RuntimeError("NapCat 当前未连接，无法发送群聊总结")
        path = Path(str(image_path)).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"群聊总结图片不存在：{path}")
        result = await self.call_action_and_wait(
            websocket,
            "send_group_msg",
            {
                "group_id": str(group_id),
                "message": [{"type": "image", "data": {"file": str(path), "cache": 0}}],
            },
            15.0,
        )
        self._require_message_delivery(result)

    def _singing_outgoing(
        self,
        event: dict[str, Any],
        user_text: str,
        decision: SingingDecision,
        *,
        request: VoiceRequest | None = None,
    ) -> tuple[list[OutgoingMessage], str]:
        """将点歌决策转换为唯一一种 OneBot 输出，并记录可诊断事件。"""

        voice_request = request or VoiceRequest(
            text=str(user_text or "")[: max(20, int(self.config.voice_max_chars))],
            reason="explicit_request",
            mode="singing",
            song_title=decision.song.title if decision.song else "",
            segment_index=None,
        )
        if decision.song is not None and decision.segment is not None:
            fallback_text = f"《{decision.song.title}》完整歌曲"
            message = OutgoingMessage("record", str(decision.segment.path))
            self._log_voice_event(
                event,
                "complete_song_selected",
                request=voice_request,
                message=message,
                error=decision.reason,
            )
            return [message], fallback_text

        reply_text = decision.reply_text or "这首歌我还没学会哦。"
        self._log_voice_event(
            event,
            "song_unavailable" if decision.reason not in {"catalog", "stopped"} else "singing_guidance",
            request=voice_request,
            error=decision.reason,
        )
        return [OutgoingMessage("text", reply_text)], ""

    async def _resolve_quoted_message(
        self,
        websocket: Any,
        event: dict[str, Any],
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """解析用户引用的消息，供本轮模型和多模态工具共同使用。

        QQ/OneBot 的 reply 消息段通常只携带目标消息 ID；若事件没有直接
        附带原文，就按需调用 ``get_msg``。读取失败时保留“存在引用”的
        明确信息，但绝不根据 ID 猜测原文。
        """

        message_id = extract_reply_message_id(event.get("message"))
        if not message_id:
            reply_payload = event.get("reply")
            if isinstance(reply_payload, dict):
                value = reply_payload.get("id") or reply_payload.get("message_id")
                if value not in (None, ""):
                    message_id = str(value)
        if not message_id:
            return "", "", []

        inline_message = extract_reply_inline_message(event)
        if inline_message is not None:
            return (
                message_id,
                extract_plain_text(inline_message),
                _message_to_segments(inline_message),
            )

        request_id: int | str = int(message_id) if message_id.isdigit() else message_id
        try:
            result = await self.call_action_and_wait(
                websocket,
                "get_msg",
                {"message_id": request_id},
                3.0,
            )
            data = result.get("data") if isinstance(result, dict) else None
            quoted_message = data.get("message") if isinstance(data, dict) else None
            if quoted_message is not None:
                return (
                    message_id,
                    extract_plain_text(quoted_message),
                    _message_to_segments(quoted_message),
                )
        except Exception as exc:
            LOGGER.warning("引用消息读取失败：message_id=%s error=%s", message_id, exc)

        return message_id, "[引用消息原文暂时无法读取]", []

    def _event_with_quoted_message(
        self,
        event: dict[str, Any],
        quoted_segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把引用消息的媒体段合并到本轮分析事件，不改变原始事件。"""

        if not quoted_segments:
            return event
        merged = dict(event)
        current_segments = _message_to_segments(event.get("message"))
        merged["message"] = (
            [{"type": "text", "data": {"text": "[引用消息]"}}]
            + quoted_segments
            + [{"type": "text", "data": {"text": "\n[当前消息]"}}]
            + current_segments
        )
        return merged

    def _allow_poke_reply(self, event: dict[str, Any]) -> bool:
        """对戳一戳做会话级冷却，防止重复通知触发刷屏。"""

        key = _message_queue_id(event)
        now = time.time()
        last = getattr(self, "_last_poke_reply_at", {}).get(key, 0.0)
        if now - last < POKE_REPLY_COOLDOWN_SECONDS:
            return False
        if not hasattr(self, "_last_poke_reply_at"):
            self._last_poke_reply_at = {}
        self._last_poke_reply_at[key] = now
        return True

    def _remember_pending_group_visual(self, event: dict[str, Any]) -> None:
        key = _pending_visual_key(event)
        if not key or not _event_has_visual_material(event):
            return
        self._pending_group_visual_events[key] = (time.time(), event)
        if len(self._pending_group_visual_events) <= 256:
            return
        oldest_key = min(
            self._pending_group_visual_events,
            key=lambda item: self._pending_group_visual_events[item][0],
        )
        self._pending_group_visual_events.pop(oldest_key, None)

    def _event_with_pending_group_visual(
        self,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        key = _pending_visual_key(event)
        if not key:
            return event
        if _event_has_visual_material(event):
            self._pending_group_visual_events.pop(key, None)
            return event
        pending = self._pending_group_visual_events.pop(key, None)
        if (
            not pending
            or time.time() - pending[0] > PENDING_GROUP_VISUAL_TTL_SECONDS
        ):
            return event
        return _merge_pending_visual_event(pending[1], event)

    async def _send_streamed_speech_reply(
        self,
        websocket: Any,
        event: dict[str, Any],
        conversation_id: str,
        request: Any,
    ) -> str:
        segments = split_spoken_text(
            request.text,
            maximum_units=int(
                getattr(self.config, "voice_segment_max_chars", 34) or 34
            ),
        )
        if not segments:
            return ""

        delivered_segments: list[str] = []
        for index, text in enumerate(segments):
            segment_started_at = time.monotonic()
            segment_request = replace(request, text=text)
            try:
                synthesis = await self._synthesize_voice_segment(
                    conversation_id,
                    segment_request,
                    enforce_cooldown=index == 0,
                )
                self._log_voice_event(
                    event,
                    "synthesized",
                    request=segment_request,
                    result=synthesis,
                    elapsed_ms=(time.monotonic() - segment_started_at) * 1000,
                )
                delivered = await self.send_reply(
                    websocket,
                    event,
                    [OutgoingMessage("record", str(synthesis.audio_path))],
                    fallback_text=text,
                    model_type="voice",
                    model_name=self._delivery_model_name("voice"),
                )
                if not delivered:
                    # 音频文件已经生成，但 NapCat 可能拒绝了 record 上传。
                    # 不能因为语音通道失败而吞掉已经生成好的回复文本。
                    remaining_text = _voice_remaining_text(
                        request.text,
                        segments,
                        delivered_segments,
                        index,
                    )
                    text_delivered = await self.send_reply(
                        websocket,
                        event,
                        [OutgoingMessage("text", remaining_text)],
                        model_type="voice",
                        model_name=self._delivery_model_name("voice"),
                    )
                    if text_delivered:
                        return "".join(delivered_segments) + text_delivered
                    return ""
                delivered_segments.append(text)
            except Exception as exc:
                LOGGER.error(
                    "语音分段合成失败：conversation=%s segment=%s error=%s",
                    conversation_id,
                    index + 1,
                    exc,
                )
                self._log_voice_event(
                    event,
                    "synthesis_failed",
                    request=segment_request,
                    error=exc,
                    elapsed_ms=(time.monotonic() - segment_started_at) * 1000,
                )
                # TTS 是可选的呈现方式，不应成为回复链路的单点故障。
                # 已成功发送的语音不再重复；只把尚未发送的部分转成文本。
                remaining_text = _voice_remaining_text(
                    request.text,
                    segments,
                    delivered_segments,
                    index,
                )
                text_delivered = await self.send_reply(
                    websocket,
                    event,
                    [OutgoingMessage("text", remaining_text)],
                    model_type="voice",
                    model_name=self._delivery_model_name("voice"),
                )
                if text_delivered:
                    return "".join(delivered_segments) + text_delivered
                return ""
            if index < len(segments) - 1:
                await asyncio.sleep(_send_delay(self.config))
        return str(request.text or "").strip()

    async def _synthesize_voice_segment(
        self,
        conversation_id: str,
        request: VoiceRequest,
        *,
        enforce_cooldown: bool,
    ) -> Any:
        """One guarded seam for all conversational TTS segments."""

        if enforce_cooldown:
            return await self.voice.synthesize(conversation_id, request)
        return await self.voice.synthesize(
                conversation_id,
                request,
                enforce_cooldown=False,
            )

    def _delivery_model_name(self, model_type: str) -> str:
        if model_type == "vision":
            return str(
                getattr(self.config, "toolbox_vision_model", "")
                or getattr(self.config, "toolbox_vision_fallback_model", "")
                or ""
            )[:160]
        if model_type == "voice":
            return str(
                getattr(self.config, "voice_zh_profile", "")
                or getattr(self.config, "voice_profile", "")
                or ""
            )[:160]
        return str(getattr(self.config, "openai_model", "") or "")[:160]

    async def send_reply(
        self,
        websocket: Any,
        event: dict[str, Any],
        messages: str | list[OutgoingMessage],
        fallback_text: str | None = None,
        model_type: str = "",
        model_name: str = "",
    ) -> str:
        outgoing = [OutgoingMessage("text", messages)] if isinstance(messages, str) else messages
        normalized_model_type = str(model_type or "").strip().lower()
        if normalized_model_type not in {"chat", "vision", "voice"}:
            normalized_model_type = "voice" if any(item.kind == "record" for item in outgoing) else "chat"
        delivered_parts: list[str] = []
        for index, message in enumerate(outgoing):
            try:
                await self._send_one_reply(websocket, event, message)
                self._record_delivery_event(event, message=message, model_type=normalized_model_type, model_name=model_name, status="success")
            except Exception as exc:
                self._record_delivery_event(event, message=message, model_type=normalized_model_type, model_name=model_name, status="failed", error=str(exc))
                LOGGER.error(
                    "OneBot 发送失败：message_type=%s user=%s group=%s kind=%s error=%s",
                    event.get("message_type"),
                    event.get("user_id"),
                    event.get("group_id"),
                    message.kind,
                    exc,
                )
                if message.kind == "record" and fallback_text:
                    # 语音是可选的传输形式。record 上传失败时，直接在同一
                    # 个发送边界改发文本，避免上层把一次语音失败误判成整条
                    # 回复失败。这里不递归调用 send_reply，防止二次异常扩大。
                    text_fallback = OutgoingMessage("text", str(fallback_text).strip())
                    try:
                        await self._send_one_reply(websocket, event, text_fallback)
                        self._record_delivery_event(event, message=text_fallback, model_type=normalized_model_type, model_name=model_name, status="success")
                    except Exception as fallback_exc:
                        self._record_delivery_event(event, message=text_fallback, model_type=normalized_model_type, model_name=model_name, status="failed", error=str(fallback_exc))
                        LOGGER.error(
                            "语音失败后的文本兜底也发送失败：user=%s group=%s error=%s",
                            event.get("user_id"),
                            event.get("group_id"),
                            fallback_exc,
                        )
                        await self._mark_napcat_manual_login_required()
                        return ""
                    return str(fallback_text).strip()
                await self._mark_napcat_manual_login_required()
                return ""

            if message.kind == "text":
                delivered_parts.append(message.content)
            elif message.kind == "record" and fallback_text:
                delivered_parts.append(fallback_text)

            if index < len(outgoing) - 1:
                await asyncio.sleep(_send_delay(self.config))
        return "\n".join(part for part in delivered_parts if part).strip()

    def _record_delivery_event(
        self,
        event: dict[str, Any],
        *,
        message: OutgoingMessage,
        model_type: str,
        model_name: str = "",
        status: str,
        error: str = "",
    ) -> None:
        if self.insights is None:
            return
        recorder = getattr(self.insights, "record_delivery", None)
        if not callable(recorder):
            return
        message_id = str(event.get("message_id") or uuid.uuid4().hex)
        recorder(
            event_id=f"{message_id}:{uuid.uuid4().hex[:8]}",
            conversation_id=_conversation_id(event),
            group_id=str(event.get("group_id") or ""),
            message_type=str(event.get("message_type") or ""),
            message_kind=str(message.kind or "text"),
            model_type=model_type,
            model_name=model_name,
            status=status,
            error=str(error or "")[:500],
        )

    def _smart_group_reply_allowed(
        self,
        event: dict[str, Any],
        conversation_id: str,
        plain_text: str,
    ) -> bool:
        if event.get("message_type") != "group":
            return True
        if self.config.reply_mode != "smart":
            return True
        if is_bot_mentioned(event, self.config.bot_qq, plain_text):
            return True

        now = datetime.now().timestamp()
        last_at = float(self._last_smart_group_reply_at.get(conversation_id, 0.0))
        return now - last_at >= SMART_GROUP_REPLY_COOLDOWN_SECONDS

    def _mark_smart_group_reply(
        self,
        event: dict[str, Any],
        conversation_id: str,
        plain_text: str,
    ) -> None:
        if event.get("message_type") != "group":
            return
        if self.config.reply_mode != "smart":
            return
        if is_bot_mentioned(event, self.config.bot_qq, plain_text):
            return
        self._last_smart_group_reply_at[conversation_id] = datetime.now().timestamp()

    async def _send_one_reply(
        self,
        websocket: Any,
        event: dict[str, Any],
        message: OutgoingMessage,
    ) -> None:
        message_type = event.get("message_type")
        onebot_message = outgoing_to_onebot_message(message)
        if message.kind == "record":
            if message_type == "private":
                result = await self.call_action_and_wait(
                    websocket,
                    "send_private_msg",
                    {"user_id": event["user_id"], "message": onebot_message},
                    12.0,
                )
                try:
                    self._require_message_delivery(result)
                except RuntimeError as exc:
                    self._log_voice_event(event, "delivery_failed", error=str(exc))
                    raise
                self._log_voice_event(event, "delivered", message=message, result=result)
                return
            if message_type == "group":
                result = await self.call_action_and_wait(
                    websocket,
                    "send_group_msg",
                    {"group_id": event["group_id"], "message": onebot_message},
                    12.0,
                )
                try:
                    self._require_message_delivery(result)
                except RuntimeError as exc:
                    self._log_voice_event(event, "delivery_failed", error=str(exc))
                    raise
                self._log_voice_event(event, "delivered", message=message, result=result)
                return
        if message_type == "private":
            result = await self.call_action_and_wait(
                websocket,
                "send_private_msg",
                {"user_id": event["user_id"], "message": onebot_message},
                12.0,
            )
            self._require_message_delivery(result)
            return

        if message_type == "group":
            result = await self.call_action_and_wait(
                websocket,
                "send_group_msg",
                {"group_id": event["group_id"], "message": onebot_message},
                12.0,
            )
            self._require_message_delivery(result)

    def _require_message_delivery(self, result: dict[str, Any] | None) -> None:
        try:
            _require_onebot_action_success(result)
        except RuntimeError:
            detail = _onebot_action_error_detail(result, default="QQ 消息发送失败")
            publish_onebot_probe_result(False, detail=detail, self_id=self.config.bot_qq)
            self._onebot_probe_failures += 1
            raise
        self._onebot_probe_failures = 0
        publish_onebot_probe_result(
            True,
            detail="QQ 消息发送成功",
            self_id=self.config.bot_qq,
        )

    async def call_action(
        self, websocket: Any, action: str, params: dict[str, Any]
    ) -> None:
        payload = {
            "action": action,
            "params": params,
            "echo": f"atri-{uuid.uuid4().hex}",
        }
        LOGGER.debug("调用 OneBot action=%s", action)
        await websocket.send(json.dumps(payload, ensure_ascii=False))

    async def fetch_group_list(self) -> list[dict[str, Any]]:
        """从当前 NapCat 连接读取群列表，供 WebUI 显示群名；失败时返回空列表。"""
        for websocket in tuple(self._active_websockets):
            try:
                result = await self.call_action_and_wait(websocket, "get_group_list", {}, 4.0)
            except Exception as exc:
                LOGGER.debug("读取 QQ 群列表失败：%s", exc)
                continue
            data = result.get("data") if isinstance(result, dict) else None
            if not isinstance(data, list):
                continue
            groups: list[dict[str, Any]] = []
            for item in data:
                if not isinstance(item, dict) or not item.get("group_id"):
                    continue
                groups.append(
                    {
                        "group_id": str(item.get("group_id")),
                        "group_name": str(item.get("group_name") or "").strip()[:200],
                    }
                )
            return groups
        return []

    async def call_action_and_wait(
        self,
        websocket: Any,
        action: str,
        params: dict[str, Any],
        timeout_seconds: float = 8.0,
    ) -> dict[str, Any] | None:
        echo = f"atri-tool-{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_actions[echo] = future
        payload = {
            "action": action,
            "params": params,
            "echo": echo,
        }
        try:
            LOGGER.debug("调用并等待 OneBot action=%s timeout=%.1fs", action, timeout_seconds)
            await websocket.send(json.dumps(payload, ensure_ascii=False))
            return await asyncio.wait_for(future, timeout=max(1.0, float(timeout_seconds)))
        finally:
            self._pending_actions.pop(echo, None)

    def _resolve_pending_action(self, event: dict[str, Any]) -> None:
        echo = str(event.get("echo") or "")
        future = self._pending_actions.pop(echo, None)
        if future is not None and not future.done():
            future.set_result(event)

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc is not None:
                LOGGER.error(
                    "消息任务异常：%s",
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )


