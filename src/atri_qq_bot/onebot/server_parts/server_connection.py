from __future__ import annotations

from .server_support import OneBotServerMixin, _sync_server_globals


class OneBotConnectionMixin(OneBotServerMixin):
    def __init__(
        self,
        config: Any,
        reply_engine: AtriReplyEngine,
        insights_runtime: InsightsRuntime | None = None,
    ) -> None:
        _sync_server_globals(self)
        self.config = config
        self.reply_engine = reply_engine
        # 由生命周期入口注入旁路；单元测试和独立适配器构造不会隐式创建数据库。
        self.insights = insights_runtime
        if self.insights is not None:
            # 总结旁路只依赖一个可选发送回调；未连接 NapCat 时仍可正常生成并保存报告。
            self.insights.summaries.set_group_sender(self.send_group_summary)
        self.cognition_shadow = None
        if bool(getattr(config, "cognition_shadow_enabled", False)):
            try:
                if CognitionShadowRunner is None:
                    raise RuntimeError(f"认知依赖不可用：{_COGNITION_IMPORT_ERROR}")
                self.cognition_shadow = CognitionShadowRunner.from_config(config)
            except Exception as exc:
                # 扩展架构必须可降级：认知内核不可用时仍保留原有 QQ 回复能力。
                LOGGER.warning("认知影子内核未启用，继续使用稳定回复链路：%s", exc)
        self.stickers = StickerManager(
            config.sticker_dir,
            config.sticker_trigger_file,
            config.sticker_capture_dir,
        )
        self.tools = ToolAnalyzer(config)
        self.voice = VoiceManager(config)
        self.voice_calls = VoiceCallStore()
        self._active_websockets: set[Any] = set()
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._onebot_probe_failures = 0
        self._last_napcat_manual_login_notice_at = 0.0
        self._message_tasks: set[asyncio.Task[Any]] = set()
        self._conversation_queues: dict[str, asyncio.Queue[tuple[Any, dict[str, Any]]]] = {}
        self._conversation_workers: dict[str, asyncio.Task[Any]] = {}
        # 戳一戳不应因重复通知触发连续大模型请求；按会话做轻量冷却。
        self._last_poke_reply_at: dict[str, float] = {}
        self._last_smart_group_reply_at: dict[str, float] = {}
        self._recent_visual_contexts: dict[str, tuple[float, Any]] = {}
        # 唱歌使用独立的确定性会话控制器；群聊按“群 + 点歌用户”隔离状态。
        self.singing = SingingConversationController()
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
        # NapCat 是反向 WebSocket 客户端：连接建立后持续接收事件，并主动探测
        # get_status。连接存在不等于 QQ 已登录，健康状态还要参考 online/good 回执。
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

    async def shutdown(self) -> None:
        """停止消息调度并释放等待中的 OneBot action。"""
        # 先清空待处理事件，避免取消 worker 时其 finally 分支重新拉起 worker。
        for queue in tuple(self._conversation_queues.values()):
            get_nowait = getattr(queue, "get_nowait", None)
            if not callable(get_nowait):
                continue
            while True:
                try:
                    get_nowait()
                except asyncio.QueueEmpty:
                    break

        tasks = {
            task
            for task in (
                set(self._message_tasks)
                | set(self._conversation_workers.values())
            )
            if not task.done()
        }
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for future in tuple(self._pending_actions.values()):
            if not future.done():
                future.cancel()
        self._pending_actions.clear()
        self._message_tasks.clear()
        self._conversation_workers.clear()
        self._conversation_queues.clear()
        LOGGER.info("OneBot 消息调度已清理：tasks=%s", len(tasks))

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
                await self._mark_napcat_manual_login_required()
            await asyncio.sleep(ONEBOT_HEALTH_INTERVAL_SECONDS)

    async def _mark_napcat_manual_login_required(self) -> None:
        if self._onebot_probe_failures < ONEBOT_HEALTH_FAILURES_BEFORE_MANUAL_LOGIN_NOTICE:
            return
        now = time.monotonic()
        if (
            now - self._last_napcat_manual_login_notice_at
            < NAPCAT_MANUAL_LOGIN_NOTICE_COOLDOWN_SECONDS
        ):
            return
        self._last_napcat_manual_login_notice_at = now
        detail = "NapCat/QQ 状态连续异常，请打开 NapCat WebUI 手动扫码登录"
        publish_napcat_runtime_state("login_required", detail=detail)
        LOGGER.warning("%s；项目不自动重启或弹出二维码", detail)

    async def handle_payload(self, websocket: Any, raw_message: str) -> None:
        try:
            event = json.loads(raw_message)
        except json.JSONDecodeError:
            LOGGER.warning("忽略非 JSON OneBot 负载：bytes=%s", len(raw_message))
            return
        if not isinstance(event, dict):
            LOGGER.warning(
                "忽略非对象 OneBot 负载：type=%s",
                type(event).__name__,
            )
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
            if getattr(self, "insights", None) is not None and event.get("message_type") == "group":
                # 在 1.2 秒防抖合并前归档，避免连续群消息被合并后丢失统计粒度。
                self.insights.archive_group_message(
                    event,
                    extract_plain_text(event.get("message")),
                )
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
            queue = asyncio.Queue(maxsize=CONVERSATION_QUEUE_MAXSIZE)
            self._conversation_queues[queue_id] = queue

        if queue.full():
            try:
                _, dropped_event = queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                LOGGER.warning(
                    "会话队列已满，丢弃较旧消息：conversation=%s dropped_message=%s queue_limit=%s",
                    queue_id,
                    dropped_event.get("message_id"),
                    CONVERSATION_QUEUE_MAXSIZE,
                )
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


