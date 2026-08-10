from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from ..group_reply_focus import GroupReplyFocusStore
from ..message_plan import OutgoingMessage, build_outgoing_messages, outgoing_to_onebot_message
from ..persona import AtriReplyEngine
from ..proactive import ProactivePlanner, load_proactive_policy, safe_zoneinfo
from ..runtime.control import (
    publish_napcat_runtime_state,
    publish_onebot_event_activity,
    publish_onebot_probe_result,
    restart_background_services,
)
from ..runtime.paths import PROJECT_ROOT
from ..stickers import StickerManager
from ..toolbox import ToolAnalyzer
from ..voice import (
    VoiceCallStore,
    VoiceManager,
    VoicePromptContext,
    SpeechServiceError,
    build_autonomous_voice_fallback,
    build_explicit_voice_fallback,
    evaluate_voice_request,
    find_record_segments,
    load_voice_behavior,
    split_spoken_text,
    stabilize_explicit_voice_request,
)
from atri_webui import bind_loop, start_webui, stop_webui
from .message_batch import _merge_message_batch, _message_to_segments
from .message_parser import (
    extract_plain_text,
    extract_reply_inline_message,
    extract_reply_message_id,
    is_poke_event,
    normalize_poke_event,
)
from .reply_policy import _as_int, is_bot_mentioned, should_reply

SMART_GROUP_REPLY_COOLDOWN_SECONDS = 75.0
MESSAGE_DEBOUNCE_SECONDS = 1.2
QUEUE_IDLE_TIMEOUT_SECONDS = 20.0
VISUAL_CONTEXT_TTL_SECONDS = 15 * 60
PENDING_GROUP_VISUAL_TTL_SECONDS = 60
POKE_REPLY_COOLDOWN_SECONDS = 60.0
ONEBOT_HEALTH_INTERVAL_SECONDS = 30.0
ONEBOT_HEALTH_FAILURES_BEFORE_RECOVERY = 2
NAPCAT_RECOVERY_COOLDOWN_SECONDS = 10 * 60
LOGGER = logging.getLogger("atri.onebot")


def _onebot_status_is_healthy(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        retcode = int(result.get("retcode", -1))
    except (TypeError, ValueError):
        return False
    data = result.get("data")
    return bool(
        retcode == 0
        and str(result.get("status") or "ok").lower() in {"ok", "async"}
        and isinstance(data, dict)
        and data.get("online") is True
        and data.get("good") is True
    )


def _is_visual_followup(text: str) -> bool:
    normalized = "".join(str(text or "").split()).lower()
    return any(
        phrase in normalized
        for phrase in (
            "这是谁",
            "这个是谁",
            "图里是谁",
            "图片里是谁",
            "什么角色",
            "哪个角色",
            "出自哪里",
            "哪部作品",
            "图上写",
            "图片写",
            "写了什么",
            "什么文字",
            "图片内容",
            "图里内容",
            "这个表情",
            "刚才那张",
            "上一张图",
            "这张图",
            "这张图片",
        )
    )


def _event_has_visual_material(event: dict[str, Any]) -> bool:
    message = event.get("message")
    if not isinstance(message, list):
        return False
    return any(
        isinstance(segment, dict)
        and str(segment.get("type") or "").lower() in {"image", "mface", "marketface"}
        for segment in message
    )


def _should_reuse_cached_visual(event: dict[str, Any], text: str) -> bool:
    return not _event_has_visual_material(event) and _is_visual_followup(text)


def _personal_event_message(event: dict[str, Any]) -> str:
    title = str(event.get("title") or "今天的重要安排").strip()
    if event.get("kind") == "birthday":
        return "生日快乐！今天是你的重要日子。高性能亚托莉记得，也希望你今天能被认真地祝福。"
    if len(title) > 72:
        title = title[:72].rstrip("，,：:；;")
    return f"提醒你一下：你之前提到“{title}”。时间到了，先确认要带的东西和下一步，别让重要安排被忙乱挤掉。"


def _pending_visual_key(event: dict[str, Any]) -> str:
    if event.get("message_type") != "group":
        return ""
    group_id = event.get("group_id")
    user_id = event.get("user_id")
    if group_id is None or user_id is None:
        return ""
    return f"group:{group_id}:user:{user_id}"


def _merge_pending_visual_event(
    visual_event: dict[str, Any],
    current_event: dict[str, Any],
) -> dict[str, Any]:
    visual_segments = [
        dict(segment)
        for segment in _message_to_segments(visual_event.get("message"))
        if str(segment.get("type") or "").lower() in {"image", "mface", "marketface"}
    ]
    if not visual_segments:
        return current_event
    merged = dict(current_event)
    merged["message"] = visual_segments + _message_to_segments(current_event.get("message"))
    return merged


class OneBotServer:
    """OneBot v11 的接入适配器。

    消息流转为：NapCat 反向 WebSocket -> ``handle_payload`` -> 按会话队列
    防抖合并 -> ``_handle_event``（回复策略、ASR、多模态）-> 人格引擎 ->
    ``send_reply`` -> OneBot action。每个会话独占队列，避免慢模型请求导致
    同一用户的消息乱序。
    """
    def __init__(self, config: Any, reply_engine: AtriReplyEngine) -> None:
        self.config = config
        self.reply_engine = reply_engine
        self.stickers = StickerManager(config.sticker_dir, config.sticker_trigger_file)
        self.tools = ToolAnalyzer(config)
        self.voice = VoiceManager(config)
        self.voice_calls = VoiceCallStore()
        self._active_websockets: set[Any] = set()
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._onebot_probe_failures = 0
        self._last_napcat_recovery_at = 0.0
        self._message_tasks: set[asyncio.Task[Any]] = set()
        self._conversation_queues: dict[str, asyncio.Queue[tuple[Any, dict[str, Any]]]] = {}
        self._conversation_workers: dict[str, asyncio.Task[Any]] = {}
        # 戳一戳不应因重复通知触发连续大模型请求；按会话做轻量冷却。
        self._last_poke_reply_at: dict[str, float] = {}
        self._last_smart_group_reply_at: dict[str, float] = {}
        self._recent_visual_contexts: dict[str, tuple[float, Any]] = {}
        self._group_reply_focus = GroupReplyFocusStore(bot_qq=config.bot_qq)
        self._pending_group_visual_events: dict[
            str,
            tuple[float, dict[str, Any]],
        ] = {}
        self._event_log = PROJECT_ROOT / "logs" / "onebot-events.log"
        self._reply_event_log = PROJECT_ROOT / "logs" / "reply-events.jsonl"
        self._voice_event_log = PROJECT_ROOT / "logs" / "voice-events.log"
        self.proactive_planner = ProactivePlanner(
            reply_engine.memory,
            getattr(config, "owner_qqs", ()),
        )

    async def handle_connection(self, websocket: Any, path: str | None = None) -> None:
        LOGGER.info("NapCat 已连接：remote=%s", getattr(websocket, "remote_address", "unknown"))
        self._active_websockets.add(websocket)
        publish_napcat_runtime_state("probing", detail="NapCat 已连接，正在确认 QQ 登录状态")
        health_task = asyncio.create_task(self.onebot_health_loop(websocket))
        try:
            async for raw_message in websocket:
                await self.handle_payload(websocket, raw_message)
        except Exception as exc:
            LOGGER.warning("NapCat 连接关闭或异常：%s", exc)
        finally:
            health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await health_task
            self._active_websockets.discard(websocket)
            if not self._active_websockets:
                publish_napcat_runtime_state(
                    "disconnected",
                    detail="NapCat 连接已断开，正在等待重连",
                )
            LOGGER.warning("NapCat 已断开，服务继续监听并等待其自动重连")

    async def probe_onebot_status(self, websocket: Any) -> bool:
        """主动询问 QQ 内核状态；NapCat 心跳本身不能证明 QQ 仍在线。"""
        try:
            result = await self.call_action_and_wait(
                websocket,
                "get_status",
                {},
                5.0,
            )
        except Exception as exc:
            publish_onebot_probe_result(False, detail=f"QQ 状态探测失败：{exc}")
            LOGGER.warning("QQ 状态探测失败：%s", exc)
            return False
        healthy = _onebot_status_is_healthy(result)
        data = result.get("data") if isinstance(result, dict) else None
        self_id = self.config.bot_qq if isinstance(data, dict) else None
        if healthy:
            publish_onebot_probe_result(
                True,
                detail="QQ 登录与消息服务正常",
                self_id=self_id,
            )
            return True
        detail = _onebot_action_error_detail(result, default="QQ 内核报告离线或异常")
        publish_onebot_probe_result(False, detail=detail, self_id=self_id)
        LOGGER.warning("QQ 状态异常：%s", detail)
        return False

    async def onebot_health_loop(self, websocket: Any) -> None:
        await asyncio.sleep(1.0)
        while websocket in self._active_websockets:
            healthy = await self.probe_onebot_status(websocket)
            if healthy:
                self._onebot_probe_failures = 0
            else:
                self._onebot_probe_failures += 1
                await self._recover_napcat_after_repeated_probe_failures()
            await asyncio.sleep(ONEBOT_HEALTH_INTERVAL_SECONDS)

    async def _recover_napcat_after_repeated_probe_failures(self) -> None:
        if self._onebot_probe_failures < ONEBOT_HEALTH_FAILURES_BEFORE_RECOVERY:
            return
        now = time.monotonic()
        if now - self._last_napcat_recovery_at < NAPCAT_RECOVERY_COOLDOWN_SECONDS:
            return
        self._last_napcat_recovery_at = now
        result = restart_background_services()
        if result.get("ok"):
            LOGGER.warning("QQ 状态连续异常，已请求受控恢复 NapCat 专用进程")
        else:
            LOGGER.error("请求恢复 NapCat 失败：%s", result.get("error"))

    async def handle_payload(self, websocket: Any, raw_message: str) -> None:
        try:
            event = json.loads(raw_message)
        except json.JSONDecodeError:
            LOGGER.warning("忽略非 JSON OneBot 负载：bytes=%s", len(raw_message))
            return

        # OneBot 心跳是验证 QQ/NapCat 事件流仍活着的唯一低成本信号；仅有
        # WebSocket TCP 连接并不足以说明机器人还能接收 QQ 消息。
        publish_onebot_event_activity(is_message=event.get("post_type") == "message")

        if "echo" in event and "retcode" in event:
            self._resolve_pending_action(event)
            return

        # OneBot 的戳一戳是 notice 事件。只把“目标是亚托莉”的事件归一化，
        # 戳其他人的通知直接忽略，避免误触发正常对话链路。
        if is_poke_event(event):
            event = normalize_poke_event(event, self.config.bot_qq)
            if event is None:
                return

        if event.get("post_type") == "message":
            # 不记录原始聊天文本，日志只保留类型和会话标识以保护隐私。
            LOGGER.debug(
                "收到消息事件：type=%s conversation=%s user=%s",
                event.get("message_type"),
                _conversation_id(event),
                event.get("user_id"),
            )
            self._enqueue_message_event(websocket, event)
            return

        task = asyncio.create_task(self._handle_event(websocket, event))
        self._message_tasks.add(task)
        task.add_done_callback(self._message_tasks.discard)
        task.add_done_callback(self._log_task_exception)

    def _enqueue_message_event(self, websocket: Any, event: dict[str, Any]) -> None:
        queue_id = _message_queue_id(event)
        queue = self._conversation_queues.get(queue_id)
        if queue is None:
            queue = asyncio.Queue()
            self._conversation_queues[queue_id] = queue
        queue.put_nowait((websocket, event))

        worker = self._conversation_workers.get(queue_id)
        if worker is not None and not worker.done():
            return

        self._start_conversation_worker(queue_id)

    def _start_conversation_worker(self, queue_id: str) -> None:
        task = asyncio.create_task(self._conversation_worker(queue_id))
        self._conversation_workers[queue_id] = task
        self._message_tasks.add(task)
        task.add_done_callback(self._message_tasks.discard)
        task.add_done_callback(self._log_task_exception)
        task.add_done_callback(
            lambda done, key=queue_id: (
                self._conversation_workers.pop(key, None)
                if self._conversation_workers.get(key) is done
                else None
            )
        )

    async def _conversation_worker(self, queue_id: str) -> None:
        """在 1.2 秒窗口内合并同一会话的连续输入，再串行处理。"""
        queue = self._conversation_queues[queue_id]
        try:
            while True:
                try:
                    websocket, event = await asyncio.wait_for(
                        queue.get(),
                        timeout=QUEUE_IDLE_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    if queue.empty():
                        break
                    continue

                batch = [(websocket, event)]
                await asyncio.sleep(MESSAGE_DEBOUNCE_SECONDS)
                while True:
                    try:
                        batch.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                merged_websocket, merged_event = _merge_message_batch(batch)
                await self._handle_event(merged_websocket, merged_event)
        finally:
            if queue.empty():
                self._conversation_queues.pop(queue_id, None)
            else:
                self._conversation_workers.pop(queue_id, None)
                self._start_conversation_worker(queue_id)

    async def _handle_event(self, websocket: Any, event: dict[str, Any]) -> None:
        """执行一次完整的入站消息决策和回复流程。"""
        plain_text = extract_plain_text(event.get("message"))
        poke_event = bool(event.get("_atri_poke_event"))
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

        preliminary_reply = poke_event or should_reply(
            event,
            self.config.bot_qq,
            self.config.reply_mode,
            self.config.owner_qqs,
        )
        active_group_continuation = False
        explicit_group_mention = bool(
            is_message
            and event.get("message_type") == "group"
            and not poke_event
            and is_bot_mentioned(event, self.config.bot_qq, plain_text)
        )
        if explicit_group_mention:
            self._group_reply_focus.open_session(
                event,
                nickname=_nickname(event) or "",
            )
        elif is_message and event.get("message_type") == "group" and not poke_event:
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
        if should_send_reply and not active_group_continuation and not self._smart_group_reply_allowed(
            event,
            conversation_id,
            plain_text,
        ):
            should_send_reply = False
        profile_id = _profile_id(event)
        nickname = _nickname(event)
        is_owner = _as_int(event.get("user_id")) in set(self.config.owner_qqs)
        trust_tier = getattr(self.reply_engine.memory, "trust_tier", None)
        if (
            is_message
            and not is_owner
            and callable(trust_tier)
            and trust_tier(profile_id) == "blocked"
        ):
            should_send_reply = False
        addressed_to_bot = (
            event.get("message_type") == "private"
            or poke_event
            or (
                event.get("message_type") == "group"
                and (should_send_reply or is_bot_mentioned(event, self.config.bot_qq, plain_text))
            )
        )
        group_reply_focus = None
        if is_message and event.get("message_type") == "group" and not poke_event:
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
                )

        if not should_send_reply:
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
            await self.send_reply(
                websocket,
                event,
                "这条语音我现在没听清。你可以再发一次，或者打字告诉我刚才说了什么。",
            )
            return

        has_current_visual = _event_has_visual_material(analysis_event)
        if has_current_visual:
            self._recent_visual_contexts.pop(conversation_id, None)

        tool_context = None
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
            )
        except Exception as exc:
            LOGGER.warning("多模态/工具分析跳过：conversation=%s error=%s", conversation_id, exc)
        if tool_context is None and _should_reuse_cached_visual(
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

        reply_text = await self.reply_engine.reply(
            conversation_id,
            model_input_text,
            nickname,
            profile_id=profile_id,
            observed=True,
            tool_context=tool_context,
            reply_focus=group_reply_focus,
        )
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
        consume_call = getattr(self.reply_engine, "consume_call_request", None)
        call_request = consume_call(conversation_id) if callable(consume_call) else None
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
            if voice_request.mode == "speech":
                delivered_text = await self._send_streamed_speech_reply(
                    websocket,
                    event,
                    conversation_id,
                    voice_request,
                )
                outgoing = []
                voice_streamed = True
            else:
                try:
                    synthesis = await self.voice.synthesize(conversation_id, voice_request)
                    self._log_voice_event(
                        event,
                        "synthesized",
                        request=voice_request,
                        result=synthesis,
                    )
                    outgoing = [OutgoingMessage("record", str(synthesis.audio_path))]
                except Exception as exc:
                    print(f"[onebot] Voice synthesis fell back to text: {exc}")
                    self._log_voice_event(
                        event,
                        "synthesis_failed",
                        request=voice_request,
                        error=exc,
                    )
                    failure_text = "这次歌声没有生成成功。"
                    outgoing = [OutgoingMessage("text", failure_text)]
        else:
            profile = self.reply_engine.profile_for(profile_id)
            outgoing = build_outgoing_messages(
                reply_text,
                plain_text,
                self.stickers,
                self.config,
                profile,
            )
        sent_sticker = any(message.kind in {"image", "face"} for message in outgoing)
        if not voice_streamed:
            delivered_text = await self.send_reply(
                websocket,
                event,
                outgoing,
                fallback_text=spoken_text or None,
            )
        self._mark_smart_group_reply(event, conversation_id, plain_text)
        recorded_reply = delivered_text or spoken_text or reply_text
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

        failure_notice_sent = False
        for index, text in enumerate(segments):
            segment_request = replace(request, text=text)
            try:
                if index == 0:
                    synthesis = await self.voice.synthesize(
                        conversation_id,
                        segment_request,
                    )
                else:
                    synthesis = await self.voice.synthesize(
                        conversation_id,
                        segment_request,
                        enforce_cooldown=False,
                    )
                self._log_voice_event(
                    event,
                    "synthesized",
                    request=segment_request,
                    result=synthesis,
                )
                await self.send_reply(
                    websocket,
                    event,
                    [OutgoingMessage("record", str(synthesis.audio_path))],
                    fallback_text=text,
                )
            except Exception as exc:
                print(f"[onebot] Voice segment {index + 1} failed: {exc}")
                self._log_voice_event(
                    event,
                    "synthesis_failed",
                    request=segment_request,
                    error=exc,
                )
                remaining = _join_unsent_speech(segments[index:])
                segment_local = isinstance(exc, SpeechServiceError) and isinstance(
                    exc.quality,
                    dict,
                )
                fallback = text if segment_local else remaining
                if not failure_notice_sent:
                    notice = (
                        "有一小段语音没合成好，改用文字。"
                        if len(segments) > 1
                        else "这次语音没合成好，改用文字。"
                    )
                    await self.send_reply(websocket, event, notice)
                    failure_notice_sent = True
                await self.send_reply(websocket, event, fallback)
                if not segment_local:
                    break
            if index < len(segments) - 1:
                await asyncio.sleep(_send_delay(self.config))
        return str(request.text or "").strip()

    async def send_reply(
        self,
        websocket: Any,
        event: dict[str, Any],
        messages: str | list[OutgoingMessage],
        fallback_text: str | None = None,
    ) -> str:
        outgoing = [OutgoingMessage("text", messages)] if isinstance(messages, str) else messages
        delivered_parts: list[str] = []
        for index, message in enumerate(outgoing):
            try:
                await self._send_one_reply(websocket, event, message)
            except Exception as exc:
                print(f"[onebot] Send failed, trying fallback once: {exc}")
                if message.kind == "record":
                    notice = "语音没有发送成功。"
                    with contextlib.suppress(Exception):
                        await self._send_one_reply(
                            websocket,
                            event,
                            OutgoingMessage("text", notice),
                        )
                    if fallback_text:
                        with contextlib.suppress(Exception):
                            await self._send_one_reply(
                                websocket,
                                event,
                                OutgoingMessage("text", fallback_text),
                            )
                    await self._recover_napcat_after_repeated_probe_failures()
                    return fallback_text or notice
                error_text = "消息没有发送成功。"
                with contextlib.suppress(Exception):
                    await self._send_one_reply(
                        websocket,
                        event,
                        OutgoingMessage("text", error_text),
                    )
                await self._recover_napcat_after_repeated_probe_failures()
                return error_text

            if message.kind == "text":
                delivered_parts.append(message.content)
            elif message.kind == "record" and fallback_text:
                delivered_parts.append(fallback_text)

            if index < len(outgoing) - 1:
                await asyncio.sleep(_send_delay(self.config))
        return "\n".join(part for part in delivered_parts if part).strip()

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

    async def idle_nudge_loop(self) -> None:
        while True:
            await asyncio.sleep(max(10, int(self.config.idle_check_seconds)))
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
            self.proactive_planner.update_owner_qqs(getattr(self.config, "owner_qqs", ()))
            try:
                due_plans = self.proactive_planner.due_plans(policy)
            except Exception as exc:
                print(f"[onebot] Proactive V2 scheduler skipped: {exc}")
                continue

            for plan in due_plans:
                message_type = str(plan.target.get("message_type") or "private")
                user_id = plan.target.get("user_id")
                group_id = plan.target.get("group_id")
                if message_type == "group" and not group_id:
                    continue
                if message_type != "group" and not user_id:
                    continue
                result = await self.reply_engine.generate_proactive_message(
                    plan.conversation_id,
                    plan.event_type,
                    policy,
                )
                text = str(result.get("text") or "").strip()
                voice_request = self.reply_engine.consume_voice_request(plan.conversation_id)
                if not text and voice_request is None:
                    if result.get("error"):
                        print(
                            f"[onebot] Proactive V2 skipped for {plan.conversation_id}: "
                            f"{result['error']}"
                        )
                    continue
                try:
                    message: str | list[dict[str, Any]] = text
                    sent_text = text
                    if voice_request is not None:
                        sent_text = voice_request.text
                        try:
                            synthesis = await self.voice.synthesize(
                                plan.conversation_id,
                                voice_request,
                            )
                            message = outgoing_to_onebot_message(
                                OutgoingMessage("record", str(synthesis.audio_path))
                            )
                        except Exception as exc:
                            print(f"[onebot] Proactive voice fell back to text: {exc}")
                            message = voice_request.text
                    if message_type == "group":
                        await self.call_action(
                            websocket,
                            "send_group_msg",
                            {"group_id": group_id, "message": message},
                        )
                    else:
                        await self.call_action(
                            websocket,
                            "send_private_msg",
                            {"user_id": user_id, "message": message},
                        )
                    self.reply_engine.record_bot_reply(plan.conversation_id, sent_text)
                    timezone = safe_zoneinfo(str(policy.get("timezone") or "Asia/Shanghai"))
                    local_now = datetime.now(timezone)
                    self.reply_engine.memory.mark_proactive_sent(
                        plan.conversation_id,
                        plan.event_type,
                        sent_text,
                        str(result.get("source") or "unknown"),
                        local_now.date().isoformat(),
                        now=local_now.timestamp(),
                    )
                    print(
                        f"[onebot] Proactive V2 sent to "
                        f"{message_type}:{group_id or user_id}; "
                        f"type={plan.event_type} source={result.get('source')}."
                    )
                    if result.get("error"):
                        print(f"[onebot] Proactive V2 generation fallback: {result['error']}")
                except Exception as exc:
                    print(f"[onebot] Proactive V2 send failed: {exc}")
                    break

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
        result = await self.reply_engine.generate_proactive_message(
            conversation_id,
            event_type,
            policy,
        )
        return {"conversation_id": conversation_id, "event_type": event_type, **result}

    async def group_proactive_loop(self) -> None:
        while True:
            await asyncio.sleep(max(30, int(self.config.group_proactive_check_seconds)))
            if (
                getattr(self.config, "proactive_v2_enabled", False)
                and load_proactive_policy().get("group_enabled", False)
            ):
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
    ) -> None:
        with contextlib.suppress(Exception):
            quality = getattr(result, "quality", None)
            if not isinstance(quality, dict):
                quality = getattr(error, "quality", None)
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
                "error": str(error or "")[:500],
            }
            self._voice_event_log.parent.mkdir(parents=True, exist_ok=True)
            with self._voice_event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")

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
            }
            self._reply_event_log.parent.mkdir(parents=True, exist_ok=True)
            with self._reply_event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def run_server(config: Any) -> None:
    import websockets

    bind_loop(asyncio.get_running_loop())
    reply_engine = AtriReplyEngine(config)
    server = OneBotServer(config, reply_engine)

    async with websockets.serve(server.handle_connection, config.host, config.port):
        print(
            f"[onebot] Listening on ws://{config.host}:{config.port}/onebot "
            f"for QQ {config.bot_qq}; reply_mode={config.reply_mode}"
        )
        idle_task = asyncio.create_task(server.idle_nudge_loop())
        morning_task = asyncio.create_task(server.morning_greeting_loop())
        proactive_v2_task = asyncio.create_task(server.proactive_v2_loop())
        group_task = asyncio.create_task(server.group_proactive_loop())
        webui_server = await start_webui(config, server)
        try:
            await asyncio.Future()
        finally:
            await stop_webui(webui_server)
            idle_task.cancel()
            morning_task.cancel()
            proactive_v2_task.cancel()
            group_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await idle_task
            with contextlib.suppress(asyncio.CancelledError):
                await morning_task
            with contextlib.suppress(asyncio.CancelledError):
                await proactive_v2_task
            with contextlib.suppress(asyncio.CancelledError):
                await group_task


def _compose_model_input(current_text: str, quoted_text: str) -> str:
    """将引用内容和用户当前输入放入明确边界，避免模型混淆说话人。"""

    current = str(current_text or "").strip() or "[用户未附加文字]"
    quoted = str(quoted_text or "").strip()
    if not quoted:
        return current
    return f"【引用消息】\n{quoted[:800]}\n【用户当前消息】\n{current}"


def _message_queue_id(event: dict[str, Any]) -> str:
    if event.get("message_type") == "group":
        return f"group:{event.get('group_id')}:user:{event.get('user_id')}"
    return _conversation_id(event)


def _conversation_id(event: dict[str, Any]) -> str:
    if event.get("message_type") == "group":
        return f"group:{event.get('group_id')}"
    return f"private:{event.get('user_id')}"


def _profile_id(event: dict[str, Any]) -> str:
    if event.get("message_type") == "group":
        return f"group:{event.get('group_id')}:user:{event.get('user_id')}"
    return f"private:{event.get('user_id')}"


def _nickname(event: dict[str, Any]) -> str | None:
    sender = event.get("sender")
    if not isinstance(sender, dict):
        return None
    return sender.get("card") or sender.get("nickname")


def _send_delay(config: Any) -> float:
    delay_min = max(0.0, float(config.message_send_delay_min))
    delay_max = max(delay_min, float(config.message_send_delay_max))
    return random.uniform(delay_min, delay_max)


def _join_unsent_speech(segments: list[str]) -> str:
    parts = [str(segment or "").strip() for segment in segments]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    joined = parts[0]
    boundary_punctuation = "。！？!?；;，,、：:"
    for part in parts[1:]:
        if joined[-1] in boundary_punctuation or part[0] in boundary_punctuation:
            joined += part
        else:
            joined += f"，{part}"
    return joined


def _require_onebot_action_success(result: dict[str, Any] | None) -> None:
    if not isinstance(result, dict):
        raise RuntimeError("NapCat 没有返回语音发送结果")
    try:
        retcode = int(result.get("retcode", -1))
    except (TypeError, ValueError):
        retcode = -1
    if retcode == 0 and str(result.get("status") or "ok").lower() in {"ok", "async"}:
        return
    detail = _onebot_action_error_detail(result, default=f"retcode={retcode}")
    raise RuntimeError(f"NapCat 消息发送失败：{detail}")


def _onebot_action_error_detail(
    result: dict[str, Any] | None,
    *,
    default: str,
) -> str:
    if not isinstance(result, dict):
        return default
    return str(
        result.get("message")
        or result.get("wording")
        or result.get("msg")
        or default
    ).strip()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
