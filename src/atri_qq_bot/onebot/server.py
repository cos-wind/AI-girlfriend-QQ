from __future__ import annotations

import asyncio
import contextlib
import json
import random
import uuid
from datetime import datetime
from typing import Any

from ..message_plan import OutgoingMessage, build_outgoing_messages, outgoing_to_onebot_message
from ..persona import AtriReplyEngine
from ..runtime.paths import PROJECT_ROOT
from ..stickers import StickerManager
from ..toolbox import ToolAnalyzer
from atri_webui import bind_loop, start_webui, stop_webui
from .message_batch import _merge_message_batch
from .message_parser import extract_plain_text
from .reply_policy import _as_int, is_bot_mentioned, should_reply

SMART_GROUP_REPLY_COOLDOWN_SECONDS = 75.0
MESSAGE_DEBOUNCE_SECONDS = 1.2
QUEUE_IDLE_TIMEOUT_SECONDS = 20.0


class OneBotServer:
    def __init__(self, config: Any, reply_engine: AtriReplyEngine) -> None:
        self.config = config
        self.reply_engine = reply_engine
        self.stickers = StickerManager(config.sticker_dir, config.sticker_trigger_file)
        self.tools = ToolAnalyzer(config)
        self._active_websockets: set[Any] = set()
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._message_tasks: set[asyncio.Task[Any]] = set()
        self._conversation_queues: dict[str, asyncio.Queue[tuple[Any, dict[str, Any]]]] = {}
        self._conversation_workers: dict[str, asyncio.Task[Any]] = {}
        self._last_smart_group_reply_at: dict[str, float] = {}
        self._event_log = PROJECT_ROOT / "logs" / "onebot-events.log"

    async def handle_connection(self, websocket: Any, path: str | None = None) -> None:
        print(f"[onebot] NapCat connected: {getattr(websocket, 'remote_address', 'unknown')}")
        self._active_websockets.add(websocket)
        try:
            async for raw_message in websocket:
                await self.handle_payload(websocket, raw_message)
        except Exception as exc:
            print(f"[onebot] NapCat connection closed or failed: {exc}")
        finally:
            self._active_websockets.discard(websocket)
            print("[onebot] NapCat disconnected; waiting for reconnect.")

    async def handle_payload(self, websocket: Any, raw_message: str) -> None:
        try:
            event = json.loads(raw_message)
        except json.JSONDecodeError:
            print(f"[onebot] Ignored non-json payload: {raw_message[:120]}")
            return

        if "echo" in event and "retcode" in event:
            self._resolve_pending_action(event)
            return

        if event.get("post_type") == "message":
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

        plain_text = extract_plain_text(event.get("message"))
        is_message = (
            event.get("post_type") == "message"
            and _as_int(event.get("user_id")) != self.config.bot_qq
            and _as_int(event.get("self_id")) in {None, self.config.bot_qq}
        )

        if is_message:
            with contextlib.suppress(Exception):
                await self.stickers.capture_from_event(
                    event,
                    plain_text,
                    self.config.sticker_capture_enabled,
                    self.config.sticker_capture_max_bytes,
                )

        should_send_reply = should_reply(
            event,
            self.config.bot_qq,
            self.config.reply_mode,
            self.config.owner_qqs,
        )
        conversation_id = _conversation_id(event)
        if should_send_reply and not self._smart_group_reply_allowed(
            event,
            conversation_id,
            plain_text,
        ):
            should_send_reply = False
        profile_id = _profile_id(event)
        nickname = _nickname(event)
        is_owner = _as_int(event.get("user_id")) in set(self.config.owner_qqs)
        addressed_to_bot = (
            event.get("message_type") == "private"
            or (
                event.get("message_type") == "group"
                and (should_send_reply or is_bot_mentioned(event, self.config.bot_qq, plain_text))
            )
        )

        if is_message:
            self._log_message_decision(event, plain_text, should_send_reply)

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

        tool_context = None
        try:
            tool_context = await self.tools.analyze(
                event,
                plain_text,
                lambda action, params: self.call_action_and_wait(
                    websocket,
                    action,
                    params,
                    self.config.toolbox_timeout_seconds,
                ),
            )
        except Exception as exc:
            print(f"[onebot] Tool analysis skipped: {exc}")

        reply_text = await self.reply_engine.reply(
            conversation_id,
            plain_text,
            nickname,
            profile_id=profile_id,
            observed=True,
            tool_context=tool_context,
        )
        profile = self.reply_engine.profile_for(profile_id)
        outgoing = build_outgoing_messages(
            reply_text,
            plain_text,
            self.stickers,
            self.config,
            profile,
        )
        sent_sticker = any(message.kind in {"image", "face"} for message in outgoing)
        await self.send_reply(websocket, event, outgoing)
        self._mark_smart_group_reply(event, conversation_id, plain_text)
        self.reply_engine.record_bot_reply(
            conversation_id,
            reply_text,
            sent_sticker,
            profile_id=profile_id,
        )

    async def send_reply(
        self,
        websocket: Any,
        event: dict[str, Any],
        messages: str | list[OutgoingMessage],
    ) -> None:
        outgoing = [OutgoingMessage("text", messages)] if isinstance(messages, str) else messages
        for index, message in enumerate(outgoing):
            try:
                await self._send_one_reply(websocket, event, message)
            except Exception as exc:
                print(f"[onebot] Send failed, trying fallback once: {exc}")
                with contextlib.suppress(Exception):
                    await self._send_one_reply(
                        websocket,
                        event,
                        OutgoingMessage("text", "刚刚连接有点不稳，我还在。你上一句我收到了。"),
                    )
                return

            if index < len(outgoing) - 1:
                await asyncio.sleep(_send_delay(self.config))

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
        if message_type == "private":
            await self.call_action(
                websocket,
                "send_private_msg",
                {"user_id": event["user_id"], "message": onebot_message},
            )
            return

        if message_type == "group":
            await self.call_action(
                websocket,
                "send_group_msg",
                {"group_id": event["group_id"], "message": onebot_message},
            )

    async def call_action(
        self, websocket: Any, action: str, params: dict[str, Any]
    ) -> None:
        payload = {
            "action": action,
            "params": params,
            "echo": f"atri-{uuid.uuid4().hex}",
        }
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
                print(f"[onebot] Message task failed: {exc}")

    async def idle_nudge_loop(self) -> None:
        while True:
            await asyncio.sleep(max(10, int(self.config.idle_check_seconds)))
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

    async def group_proactive_loop(self) -> None:
        while True:
            await asyncio.sleep(max(30, int(self.config.group_proactive_check_seconds)))
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
        group_task = asyncio.create_task(server.group_proactive_loop())
        webui_server = await start_webui(config, server)
        try:
            await asyncio.Future()
        finally:
            await stop_webui(webui_server)
            idle_task.cancel()
            morning_task.cancel()
            group_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await idle_task
            with contextlib.suppress(asyncio.CancelledError):
                await morning_task
            with contextlib.suppress(asyncio.CancelledError):
                await group_task


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


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
