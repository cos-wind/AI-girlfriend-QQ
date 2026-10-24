from __future__ import annotations

import asyncio
import logging
import time

from .server_support import OneBotServerMixin, _sync_server_globals

# 显式导入而不是依赖 _sync_server_globals 的全局注入：账号路径是安全关键路径，
# 不应该依赖那个 __getattribute__ 钩子在运行时把名字塞进来。
# 这几个模块本身不 import onebot，所以不会形成循环依赖。
from ...accounts import (  # type: ignore[import-not-found]
    AccountContext,
    AccountSwitchCoordinator,
    bootstrap_from_config,
    build_runtime_resources,
    current_account,
    registry_for_config,
)

# 运行时会由 _sync_server_globals 注入 server.py 的同名 logger；这里显式声明一份，
# 保证模块在被单独导入（例如单元测试）时也能正常记录账号/连接类告警。
LOGGER = logging.getLogger("atri.onebot")

# 账号切换时要整体替换的 server 属性。**每一项都必须换成新值或 None**，
# 绝不能保留上一个账号的对象——那会把 A 账号的数据写进 B 账号的库。
ACCOUNT_SCOPED_ATTRIBUTES = (
    "reply_engine",
    "insights",
    "cognition_shadow",
    "stickers",
    "tools",
    "voice",
)

# 账号切换前等待在途消息处理的超时。宁可超时继续（generation 会兜底），
# 也不能让一个卡住的任务把换账号永久挂死。
ACCOUNT_DRAIN_TIMEOUT_SECONDS = 5.0
ACCOUNT_DRAIN_POLL_SECONDS = 0.05


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
            # 总结可选发送；人工生成时则按需向当前登录的 QQ 内核读取历史消息。
            self.insights.summaries.set_group_sender(self.send_group_summary)
            self.insights.summaries.set_group_history_fetcher(self.fetch_group_history)
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
        # NapCat 实际登录号与 BOT_QQ 不一致时，事件会被整体忽略；这种"完全没反应"
        # 必须能在日志里看到原因，所以两条告警各自限频。
        self._account_mismatch_notice_at = 0.0
        self._foreign_account_event_notice_at = 0.0
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
        # 账号系统（ACCOUNT_SYSTEM_ENABLED，默认关闭）。
        # 关闭时 coordinator 为 None，下面所有账号相关方法都是空操作，
        # 整条链路与账号化之前逐条一致。
        self._account_base_config = config
        self.account_coordinator = None
        if bool(getattr(config, "account_system_enabled", False)):
            self.account_coordinator = self._build_account_coordinator(config)

    def _build_account_coordinator(
        self,
        config: Any,
        *,
        builders: dict[str, Any] | None = None,
        required: Any = None,
    ) -> Any:
        """按配置建立账号协调器；BOT_QQ 在这里被引导成默认账号。

        排空用的是 ``self.drain_account_work``，所以协调器必须在 server 实例上构造。

        ``builders`` / ``required`` 只是给测试注入轻量资源的接缝——生产路径不传，
        走 ``build_runtime_resources`` 的默认表。
        """
        account = bootstrap_from_config(config)
        if account is not None:
            LOGGER.info(
                "账号系统已启用：默认账号 %s（确认状态 %s）",
                account.account_id,
                "已确认" if account.confirmed else "待确认",
            )
        else:
            LOGGER.warning("账号系统已启用，但 BOT_QQ 未设置，无法引导默认账号")
        return AccountSwitchCoordinator(
            config,
            build=lambda target, previous: build_runtime_resources(
                config,
                target,
                builders=builders,
                required=(
                    required
                    if required is not None
                    else frozenset({"reply_engine"})
                ),
            ),
            async_drain=self.drain_account_work,
        )

    async def drain_account_work(self) -> None:
        """账号切换前排空在途的消息处理。

        不能复用 ``shutdown()``——那个是 ``cancel``，会把正在处理的消息直接丢掉。
        这里等它们跑完，并设上限避免被一个卡住的任务永久挂死。
        """
        deadline = time.monotonic() + ACCOUNT_DRAIN_TIMEOUT_SECONDS
        pending: set[Any] = set()
        while True:
            pending = {
                task
                for task in (
                    set(self._message_tasks)
                    | set(self._conversation_workers.values())
                )
                if not task.done()
            }
            if not pending:
                return
            if time.monotonic() >= deadline:
                # 超时不阻断切换：每条任务都持有自己那份上下文快照，
                # 写的是它自己账号的库；generation 兜底会处理延迟解析路径的调用点。
                LOGGER.warning(
                    "账号切换排空超时：仍有 %s 个任务在跑，继续切换", len(pending)
                )
                return
            await asyncio.sleep(ACCOUNT_DRAIN_POLL_SECONDS)

    def apply_account_context(self, context: Any) -> None:
        """把账号上下文里的资源换到 server 上。调用方必须已完成排空。

        **每一项账号作用域资源都换成新值或 None**，绝不保留上一个账号的对象——
        否则新账号的记忆会写进旧账号的库，而且不会报错。
        """
        self.config = context.config
        for name in ACCOUNT_SCOPED_ATTRIBUTES:
            setattr(self, name, context.resources.get(name))

        # 下面这几个跟着 config / reply_engine 走，必须一起重建。
        # 重建失败时**置空而不是保留旧对象**：旧对象绑定的是上一个账号的记忆，
        # 留着它比没有它更危险（会把新账号的数据写进旧账号的库）。
        try:
            self._group_reply_focus = GroupReplyFocusStore(bot_qq=self.config.bot_qq)
        except Exception as exc:
            LOGGER.error("重建群聊焦点存储失败，已置空：%s", exc)
            self._group_reply_focus = None
        if self.reply_engine is not None:
            try:
                self.proactive_planner = ProactivePlanner(
                    self.reply_engine.memory,
                    getattr(self.config, "owner_qqs", ()),
                )
            except Exception as exc:
                LOGGER.error("重建主动消息规划器失败，已置空：%s", exc)
                self.proactive_planner = None
        else:
            self.proactive_planner = None
        if self.insights is not None:
            # 新账号的 insights 是全新实例，发送器与历史读取器要重新挂上。
            self.insights.summaries.set_group_sender(self.send_group_summary)
            self.insights.summaries.set_group_history_fetcher(self.fetch_group_history)

    async def follow_napcat_account(self, peer_uin: int | None) -> None:
        """按 NapCat 实际登录号切换账号。

        仅在账号系统开启时生效。三条边界：

        * ``ACCOUNT_FOLLOW_NAPCAT`` 关闭时，当前账号就是注册表里的默认账号
          （BOT_QQ），所以 NapCat 登录了别的号也只会继续用默认账号——
          这正是今天的"账号不一致就忽略消息"行为。
        * 跟随开启但该号**未在 WebUI 确认过**时 ``current_account`` 返回 None，
          于是不切换，行为同样回落到今天。
        * 目标与当前相同则什么都不做。
        """
        coordinator = self.account_coordinator
        if coordinator is None:
            return

        base = self._account_base_config
        if peer_uin is not None and bool(getattr(base, "account_follow_napcat", False)):
            try:
                _account, discovered = registry_for_config(base).observe_from_napcat(
                    peer_uin
                )
            except Exception as exc:
                LOGGER.warning("记录 NapCat 登录账号失败：%s", exc)
            else:
                if discovered:
                    LOGGER.warning(
                        "发现新账号 QQ %s（未确认）：确认前不建数据区，"
                        "行为与今天的账号不一致一致",
                        peer_uin,
                    )

        target = current_account(base, napcat_uin=peer_uin)
        if target is None:
            return
        if coordinator.context.account_id == target.account_id:
            return

        try:
            context = await coordinator.aswitch(
                target, reason=f"NapCat 登录 {peer_uin}"
            )
        except Exception as exc:
            # 失败原子性保证旧上下文仍然有效，所以这里只记日志、继续用旧账号。
            LOGGER.error("账号切换失败，继续使用当前账号：%s", exc)
            return
        self.apply_account_context(context)

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
        peer_uin = await self._napcat_login_uin(websocket)
        if healthy:
            self_id = self.config.bot_qq if isinstance(data, dict) else None
            detail = "QQ 登录与消息服务正常"
            if peer_uin is not None and int(peer_uin) != int(self.config.bot_qq or 0):
                # 账号不一致时机器人会忽略所有消息（事件 self_id 不匹配），
                # 用户看到的现象就是"发消息完全没反应"。
                detail = (
                    f"NapCat 登录 {peer_uin}，项目 BOT_QQ={self.config.bot_qq}；"
                    "账号不一致，机器人会忽略所有消息"
                )
                self._warn_account_mismatch(peer_uin)
            publish_onebot_probe_result(
                True,
                detail=detail,
                self_id=self_id,
                peer_uin=peer_uin,
            )
            # 账号系统开启时按 NapCat 实际登录号切换；未开启时是空操作。
            await self.follow_napcat_account(peer_uin)
            return True
        detail = _onebot_action_error_detail(result, default="QQ 内核报告离线或异常")
        publish_onebot_probe_result(
            False,
            detail=detail,
            self_id=self.config.bot_qq if isinstance(data, dict) else None,
            peer_uin=peer_uin,
        )
        LOGGER.warning("QQ 状态异常：%s", detail)
        return False

    async def _napcat_login_uin(self, websocket: Any) -> int | None:
        """读取 NapCat 实际登录的 QQ 号；失败返回 None（不影响健康判断）。"""

        try:
            result = await self.call_action_and_wait(websocket, "get_login_info", {}, 5.0)
        except Exception:
            return None
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            return None
        try:
            value = int(data.get("user_id") or 0)
        except (TypeError, ValueError):
            return None
        return value or None

    def _warn_account_mismatch(self, peer_uin: int) -> None:
        now = time.monotonic()
        if now - self._account_mismatch_notice_at < 600:
            return
        self._account_mismatch_notice_at = now
        LOGGER.warning(
            "账号不一致：NapCat 登录的是 %s，但项目 BOT_QQ=%s。"
            "这种情况下所有 QQ 消息都会被忽略（既没有回复，也不会有消息决策日志）。"
            "请二选一：把 .env 的 BOT_QQ 改成 %s，或在 NapCat 里换回 %s 后重启项目。",
            peer_uin,
            self.config.bot_qq,
            peer_uin,
            self.config.bot_qq,
        )

    def _warn_foreign_account_event(self, event_self_id: int | None) -> None:
        now = time.monotonic()
        if now - self._foreign_account_event_notice_at < 600:
            return
        self._foreign_account_event_notice_at = now
        LOGGER.warning(
            "忽略其它账号的事件：事件 self_id=%s，配置 BOT_QQ=%s（账号不一致时不会回复）",
            event_self_id,
            self.config.bot_qq,
        )

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

        # 新人入群同样是 notice。归一化成普通群消息后走同一条回复链路，
        # 由它来触发入群欢迎；亚托莉自己进群返回 None，直接忽略。
        if is_group_increase_event(event):
            event = normalize_group_increase_event(event, self.config.bot_qq)
            if event is None:
                return

        if event.get("post_type") == "message":
            event_self_id = _as_int(event.get("self_id"))
            if event_self_id not in {None, self.config.bot_qq}:
                # 事件是别的 QQ 号的（NapCat 登录号与 BOT_QQ 不一致）：旧代码会
                # 静默忽略，用户只看到"发了消息没反应"。这里留下可排查的告警。
                self._warn_foreign_account_event(event_self_id)
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

