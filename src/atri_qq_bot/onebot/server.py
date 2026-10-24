from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from ..application import ConversationTurnRequest
try:
    from ..cognition import CognitionShadowRunner, evidence_from_tool_context
except Exception as cognition_import_error:  # pragma: no cover - 仅用于缺依赖部署兜底
    CognitionShadowRunner = None  # type: ignore[assignment,misc]

    def evidence_from_tool_context(tool_context: Any | None) -> tuple[Any, ...]:
        return ()

    _COGNITION_IMPORT_ERROR = cognition_import_error
else:
    _COGNITION_IMPORT_ERROR = None
from ..group_reply_focus import GroupReplyFocusStore
from ..insights import (
    EvaluationSample,
    InsightsRuntime,
    context_from_tool_context,
)
from ..message_plan import OutgoingMessage, build_outgoing_messages, outgoing_to_onebot_message
from ..music import SingingConversationController, SingingDecision
from ..persona import AtriReplyEngine
from ..proactive import ProactivePlanner, load_proactive_policy, safe_zoneinfo
from ..runtime.control import (
    publish_napcat_runtime_state,
    publish_onebot_event_activity,
    publish_onebot_probe_result,
)
from ..runtime.paths import PROJECT_ROOT
from ..runtime.modality_access import is_event_modality_allowed
from ..runtime.reply_strategy import (
    ReplyDecision,
    evaluate_reply,
    load_reply_strategy,
    record_reply,
)
from ..stickers import StickerManager
from ..toolbox import ToolAnalyzer
from ..voice import (
    VoiceCallStore,
    VoiceManager,
    VoicePromptContext,
    VoiceRequest,
    SpeechServiceError,
    build_autonomous_voice_fallback,
    build_explicit_voice_fallback,
    detect_explicit_delivery_intent,
    evaluate_voice_request,
    find_record_segments,
    load_voice_behavior,
    sanitize_voice_request,
    split_spoken_text,
    stabilize_explicit_voice_request,
)
from atri_webui import bind_loop, start_webui, stop_webui

from .message_batch import _merge_message_batch, _message_to_segments
from .message_parser import (
    extract_plain_text,
    extract_reply_inline_message,
    extract_reply_message_id,
    group_increase_text,
    is_group_increase_event,
    is_poke_event,
    normalize_group_increase_event,
    normalize_poke_event,
)
from .reply_policy import _as_int, is_bot_mentioned, should_reply

SMART_GROUP_REPLY_COOLDOWN_SECONDS = 75.0
MESSAGE_DEBOUNCE_SECONDS = 1.2
QUEUE_IDLE_TIMEOUT_SECONDS = 20.0
CONVERSATION_QUEUE_MAXSIZE = 64
VISUAL_CONTEXT_TTL_SECONDS = 15 * 60
PENDING_GROUP_VISUAL_TTL_SECONDS = 60
POKE_REPLY_COOLDOWN_SECONDS = 60.0
ONEBOT_HEALTH_INTERVAL_SECONDS = 30.0
ONEBOT_HEALTH_FAILURES_BEFORE_MANUAL_LOGIN_NOTICE = 2
NAPCAT_MANUAL_LOGIN_NOTICE_COOLDOWN_SECONDS = 10 * 60
LOGGER = logging.getLogger("atri.onebot")


from .server_parts.helpers import (
    _compose_model_input,
    _conversation_id,
    _event_has_visual_material,
    _first_reply_delay,
    _is_visual_followup,
    _merge_pending_visual_event,
    _message_queue_id,
    _nickname,
    _now_text,
    _onebot_action_error_detail,
    _onebot_status_is_healthy,
    _pending_visual_key,
    _personal_event_message,
    _profile_id,
    _require_onebot_action_success,
    _send_delay,
    _should_reuse_cached_visual,
    _typing_delay,
    _voice_remaining_text,
)

from .server_parts.server_connection import OneBotConnectionMixin
from .server_parts.server_delivery import OneBotDeliveryMixin
from .server_parts.server_events import OneBotEventMixin
from .server_parts.server_proactive import OneBotProactiveMixin


class OneBotServer(
    OneBotConnectionMixin,
    OneBotEventMixin,
    OneBotDeliveryMixin,
    OneBotProactiveMixin,
):
    """OneBot v11 的接入适配器。

    消息流转为：NapCat 反向 WebSocket -> ``handle_payload`` -> 按会话队列
    防抖合并 -> ``_handle_event``（回复策略、ASR、多模态）-> 人格引擎 ->
    ``send_reply`` -> OneBot action。每个会话独占队列，避免慢模型请求导致
    同一用户的消息乱序。
    """


async def run_server(config: Any) -> None:
    import websockets

    bind_loop(asyncio.get_running_loop())
    reply_engine = AtriReplyEngine(config)
    insights_runtime: InsightsRuntime | None = None
    try:
        insights_runtime = InsightsRuntime()
    except Exception as exc:
        # 评测/总结是纯旁路：初始化失败时只关闭扩展，不影响 OneBot 回复能力。
        LOGGER.warning("评测与群聊总结旁路未启用，继续运行核心回复链路：%s", exc)
    server = OneBotServer(config, reply_engine, insights_runtime)
    if server.insights is not None:
        await server.insights.start()

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
            await server.shutdown()
            if server.insights is not None:
                await server.insights.close()
            if server.cognition_shadow is not None:
                await server.cognition_shadow.close()
