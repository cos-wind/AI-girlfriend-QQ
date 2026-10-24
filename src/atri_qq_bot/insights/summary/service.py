from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from . import *  # noqa: F403
from ..history_import import normalize_group_history

class GroupSummaryService:
    def __init__(self, store: InsightsStore, config: InsightsConfig) -> None:
        self.store = store
        self.config = config
        self._encoder = SemanticEncoder(config.embedding_model, local_only=config.embedding_local_only)
        self._jobs: set[asyncio.Task[Any]] = set()
        self._scheduler: asyncio.Task[None] | None = None
        self._group_sender: Callable[[str, str], Awaitable[None]] | None = None
        self._group_history_fetcher: Callable[..., Awaitable[list[dict[str, Any]]]] | None = None
        self._active_groups: dict[str, str] = {}

    def set_group_sender(self, sender: Callable[[str, str], Awaitable[None]] | None) -> None:
        """注入可选的 OneBot 图片发送器；未注入时仍只生成报告，不影响旁路。"""
        self._group_sender = sender

    def set_group_history_fetcher(
        self,
        fetcher: Callable[..., Awaitable[list[dict[str, Any]]]] | None,
    ) -> None:
        """注入按需读取 QQ 客户端历史的适配器。

        该适配器只在人工点击“生成并保存/发送”时调用；实时归档和定时计划
        均不会触发它，因此总结不再依赖亚托莉此前是否在线。
        """
        self._group_history_fetcher = fetcher

    async def start(self) -> None:
        interrupted = await asyncio.to_thread(self.store.recover_interrupted_summaries)
        if interrupted:
            LOGGER.warning("已标记 %s 个因 ATRI 重启中断的群聊总结任务", interrupted)
        if self._scheduler is None:
            self._scheduler = asyncio.create_task(self._schedule_loop(), name="atri-summary-scheduler")

    async def submit(
        self,
        group_id: str,
        start: str | None = None,
        end: str | None = None,
        trigger_type: str = "manual",
        *,
        period_type: str | None = None,
        anchor: str | date | datetime | None = None,
    ) -> str:
        if not self.config.summary_enabled:
            raise RuntimeError("群聊总结功能未启用")
        normalized_group_id = str(group_id).strip()
        if not normalized_group_id:
            raise ValueError("群号不能为空")
        if normalized_group_id in self._active_groups:
            raise RuntimeError("该群已有总结正在生成，请等待当前任务完成后再试")
        period_key = ""
        period_label = ""
        if period_type:
            start_at, end_at, period_key, period_label = _resolve_period(period_type, anchor)
        else:
            # 兼容旧调用方；WebUI 新入口只传周期类型和日期。
            start_at = datetime.fromisoformat(str(start))
            end_at = datetime.fromisoformat(str(end))
        if start_at >= end_at:
            raise ValueError("开始时间必须早于结束时间")
        summary_id = await asyncio.to_thread(
            self.store.create_summary,
            normalized_group_id, start_at.isoformat(), end_at.isoformat(), trigger_type,
            period_type or "custom", period_key, period_label,
        )
        task = asyncio.create_task(self._generate(summary_id), name=f"atri-summary-{summary_id[:8]}")
        self._active_groups[normalized_group_id] = summary_id
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)
        task.add_done_callback(self._log_task_error)
        task.add_done_callback(lambda _task, key=normalized_group_id: self._active_groups.pop(key, None))
        return summary_id

    async def _generate(self, summary_id: str) -> None:
        detail = await asyncio.to_thread(self.store.summary_detail, summary_id)
        if not detail:
            return
        await asyncio.to_thread(self.store.mark_summary_running, summary_id)
        history_snapshot: dict[str, Any] | None = None
        messages: list[dict[str, Any]] | None = None
        try:
            if (
                str(detail.get("trigger_type") or "") in {"manual", "manual_save", "manual_send"}
                and str(detail.get("period_type") or "").lower() in {"daily", "weekly", "monthly"}
            ):
                if self._group_history_fetcher is None:
                    raise RuntimeError("QQ 客户端历史读取器未连接；请确认 NapCat 已登录并连接")
                start_at = datetime.fromisoformat(str(detail["period_start"]))
                end_at = datetime.fromisoformat(str(detail["period_end"]))
                await asyncio.to_thread(
                    self.store.update_summary_progress, summary_id, 12, "读取 QQ 历史", "正在读取最新一页消息"
                )

                async def history_progress(page: int, scanned: int) -> None:
                    # 总页数只有抵达时间起点后才能确定；进度条在采集阶段保持 12–58%，
                    # 文案展示已读取页数和消息数，避免把未知总量伪装成精确百分比。
                    percent = min(58, 12 + min(46, int(page) // 2))
                    await asyncio.to_thread(
                        self.store.update_summary_progress,
                        summary_id,
                        percent,
                        "读取 QQ 历史",
                        f"已读取第 {page} 页，已扫描 {scanned} 条消息",
                    )

                raw_history = await self._group_history_fetcher(
                    str(detail["group_id"]), start_at, end_at, self.config.summary_max_messages, history_progress
                )
                await asyncio.to_thread(
                    self.store.update_summary_progress, summary_id, 60, "整理聊天快照", f"已读取 {len(raw_history)} 条 QQ 历史消息"
                )
                messages, history_snapshot = await asyncio.to_thread(
                    normalize_group_history, str(detail["group_id"]), raw_history
                )
            if messages is None:
                await asyncio.to_thread(self.store.update_summary_progress, summary_id, 35, "读取已归档消息", "正在读取本地归档")
                messages = await asyncio.to_thread(
                    self.store.group_messages,
                    detail["group_id"],
                    detail["period_start"],
                    detail["period_end"],
                    self.config.summary_max_messages,
                )
            if len(messages) < self.config.summary_min_messages:
                raise ValueError(
                    f"时间范围内只有 {len(messages)} 条消息，少于最低要求 {self.config.summary_min_messages} 条"
                )
            await asyncio.to_thread(self.store.update_summary_progress, summary_id, 68, "统计与聚类", f"正在分析 {len(messages)} 条消息")
            period_type = str(detail.get("period_type") or "custom")
            statistics = _statistics(messages, period_type=period_type, period_start=detail.get("period_start"))
            statistics["period_start"] = detail.get("period_start")
            statistics["period_end"] = detail.get("period_end")
            statistics["period_label"] = detail.get("period_label") or ""
            if history_snapshot is not None:
                statistics["history_import"] = history_snapshot
            profile = _activity_profile(statistics)
            statistics["activity_profile"] = profile
            timeline = _activity_segments(
                messages, max(8, profile["detail_level"] * 4), period_type, detail.get("period_start")
            )
            # 即使模型改写时间线，也保留本地按周期聚合的昵称和原话，供图文报告补回发言人。
            statistics["period_timeline"] = timeline
            important_messages = _important_messages(messages, max(15, profile["detail_level"] * 10))
            history: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                history = await asyncio.to_thread(self.store.list_summaries, detail["group_id"], 4)
                history = [item for item in history if item.get("id") != summary_id and item.get("status") == "completed"]
            chunks = _message_chunks(messages, size=profile["chunk_size"])
            # 主题展示数与候选簇数分开：先保留更多互不相似的候选，再由话题层
            # 合并重复主题、筛掉低信息片段。旧版直接把上限设为展示数，溢出片段
            # 会被硬塞进无关簇，导致日报出现多个相似又不相关的标题。
            candidate_cluster_limit = min(30, max(12, profile["max_topics"] * 3))
            try:
                vectors = await asyncio.to_thread(
                    self._encoder.encode, [chunk["text"] for chunk in chunks]
                )
                clusters = _cluster_vectors(
                    chunks,
                    vectors,
                    self.config.topic_cluster_threshold,
                    candidate_cluster_limit,
                )
                statistics["clustering"] = "sentence-transformers"
            except Exception as exc:
                LOGGER.warning("话题向量聚类不可用，改用关键词聚类：%s", exc)
                clusters = _fallback_clusters(chunks, candidate_cluster_limit)
                statistics["clustering"] = "keyword-fallback"
            topics = _topic_payload(
                chunks,
                clusters,
                max_topics=min(self.config.topic_max_clusters, profile["max_topics"]),
            )
            statistics["topic_candidate_clusters"] = len(clusters)
            statistics["topic_count"] = len(topics)
            report = _fallback_report(
                detail["group_id"], topics, statistics, profile=profile, messages=messages, period_type=period_type
            )
            if self.config.judge_ready:
                await asyncio.to_thread(self.store.update_summary_progress, summary_id, 78, "模型润色", "正在生成结构化日报")
                try:
                    client = StructuredLLMClient(
                        base_url=self.config.judge_base_url,
                        api_key=self.config.judge_api_key,
                        model=self.config.judge_model,
                        timeout=self.config.judge_timeout_seconds,
                    )
                    system, prompt = _summary_prompt(
                        detail["group_id"], detail["period_start"], detail["period_end"], topics, statistics,
                        profile=profile, timeline=timeline, important_messages=important_messages, history=history,
                        period_type=period_type,
                    )
                    payload = await client.complete_json(system=system, prompt=prompt, max_tokens=profile["max_tokens"])
                    model_summary = str(payload.get("summary") or "").strip()
                    minimum_chars = {1: 120, 2: 220, 3: 420, 4: 700}[profile["detail_level"]]
                    if len(model_summary) >= minimum_chars:
                        model_topics = payload.get("topics")
                        report = {
                            "title": str(payload.get("title") or report["title"])[:300],
                            "topics": _normalize_topics(model_topics, topics),
                            "key_points": [
                                str(item)[:500] for item in payload.get("key_points", [])
                            ] if isinstance(payload.get("key_points"), list) and payload.get("key_points") else report["key_points"],
                            "summary": model_summary,
                        }
                        for field in (
                            "atri_intro", "overview", "activity_assessment", "timeline", "decisions",
                            "action_items", "open_questions", "notable_quotes", "member_highlights", "mood", "atri_closing",
                        ):
                            if field in payload:
                                report[field] = payload[field]
                        report["topics"] = _normalize_topics(report.get("topics"), topics)
                        report["member_highlights"] = _normalize_member_highlights(
                            report.get("member_highlights"), statistics
                        )
                        report["timeline"] = _merge_timeline_speakers(report.get("timeline"), timeline)
                        # 模型总结若完全没有提到任何已识别主题，说明输出很可能只是泛泛
                        # 的口号；保留确定性证据报告，并把模型文字作为补充，避免整体失真。
                        topic_terms = [
                            str(item.get("title") or "").split("、", 1)[0][:8]
                            for item in report["topics"][:5]
                        ]
                        if topic_terms and not any(term and term in model_summary for term in topic_terms):
                            report["summary"] = report["summary"] + "\n\n## 模型补充观察\n" + model_summary
                        # 某些模型会忽略口吻约束，兜底补上亚托莉的开场和结语。
                        if "亚托莉" not in report["summary"][:160]:
                            report["summary"] = "嗯嗯，我把这段群聊整理好了。\n\n" + report["summary"]
                        if "亚托莉" not in report["summary"][-180:]:
                            report["summary"] += "\n\n以上是亚托莉的观察报告。"
                    elif model_summary:
                        statistics["judge_short_output"] = len(model_summary)
                except Exception as exc:
                    # 总结具备确定性降级报告；Judge 暂时不可用时仍可查看话题、
                    # 高频词和活跃成员，避免“群聊总结”被 API 凭据完全阻断。
                    statistics["judge_fallback"] = str(exc)[:500]
                    LOGGER.warning("群聊总结 Judge 不可用，使用本地结构化降级：%s", exc)
            # 图文报告读取这些结构化区块；旧总结记录没有该字段时仍可展示基础内容。
            report_sections = statistics.setdefault("report_sections", {})
            if isinstance(report_sections, dict):
                for field in (
                    "atri_intro", "overview", "activity_assessment", "timeline", "decisions",
                    "action_items", "open_questions", "notable_quotes", "member_highlights", "mood",
                    "atri_closing", "vibe", "important_messages",
                ):
                    if field in report:
                        report_sections[field] = report[field]
            await asyncio.to_thread(
                self.store.save_summary_report,
                summary_id,
                title=report["title"],
                message_count=len(messages),
                topics=report["topics"],
                key_points=report["key_points"],
                statistics=statistics,
                content=_visible_text(report["summary"]),
            )
            if detail.get("trigger_type") in {"scheduled", "manual_send", "manual_save"}:
                try:
                    await asyncio.to_thread(self.store.update_summary_progress, summary_id, 88, "生成图文报告", "正在绘制日报图片")
                    group_name = self.store.group_name_map().get(str(detail.get("group_id") or ""), "")
                    image_detail = dict(detail)
                    image_detail.update(
                        {
                            "group_name": group_name,
                            "title": report.get("title"),
                            "topics": report.get("topics", []),
                            "statistics": statistics,
                            "message_count": len(messages),
                        }
                    )
                    image_path = await asyncio.to_thread(
                        render_group_summary_image,
                        image_detail,
                        group_summary_image_path(image_detail, self.store.path.parent / "summary_reports"),
                    )
                    # “生成并保存”只落盘；只有显式发送的任务才会触碰 OneBot/NapCat。
                    if detail.get("trigger_type") in {"scheduled", "manual_send"}:
                        if self._group_sender is None:
                            raise RuntimeError("NapCat 当前未连接，无法发送群聊总结")
                        await asyncio.to_thread(self.store.update_summary_progress, summary_id, 96, "发送到群聊", "正在发送日报图片")
                        # OneBot 直接发送本机 PNG，QQ 端显示为图片消息，而不是链接或长文本。
                        await self._group_sender(str(detail["group_id"]), str(image_path))
                    if detail.get("trigger_type") == "scheduled":
                        await asyncio.to_thread(
                            self.store.mark_group_summary_schedule_sent,
                            str(detail["group_id"]), period_type,
                            datetime.now().astimezone().replace(second=0, microsecond=0, tzinfo=None).isoformat(timespec="minutes"),
                        )
                except Exception as exc:
                    raise RuntimeError(f"报告正文已生成，但图文保存或发送失败：{exc}") from exc
            await asyncio.to_thread(self.store.finish_summary, summary_id)
            LOGGER.info("群聊总结完成：id=%s group=%s messages=%s", summary_id, detail["group_id"], len(messages))
        except Exception as exc:
            await asyncio.to_thread(self.store.fail_summary, summary_id, str(exc), len(locals().get("messages", [])))
            LOGGER.warning("群聊总结失败：id=%s error=%s", summary_id, exc)

    async def _schedule_loop(self) -> None:
        last_minute = ""
        while True:
            await asyncio.sleep(15)
            config = self.config
            if not config.summary_enabled:
                continue
            now_local = datetime.now().astimezone()
            minute_key = now_local.strftime("%Y-%m-%d %H:%M")
            if minute_key == last_minute:
                continue
            last_minute = minute_key
            # 新版计划保存在 SQLite，每个群、每个周期有独立开关和时间。
            now_text = now_local.replace(second=0, microsecond=0, tzinfo=None).isoformat(timespec="minutes")
            due = await asyncio.to_thread(self.store.due_group_summary_schedules, now_text)
            for item in due:
                group_id = str(item.get("group_id") or "").strip()
                scheduled_period = str(item.get("period_type") or "daily")
                if not group_id:
                    continue
                _, _, period_key, _ = _resolve_period(scheduled_period)
                exists = await asyncio.to_thread(
                    self.store.scheduled_summary_exists, group_id, scheduled_period, period_key
                )
                if not exists:
                    interval_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(scheduled_period, 1)
                    next_at = (now_local + timedelta(days=interval_days)).replace(
                        second=0, microsecond=0, tzinfo=None
                    ).isoformat(timespec="minutes")
                    await asyncio.to_thread(
                        self.store.advance_group_summary_schedule,
                        group_id, scheduled_period, next_at,
                    )
                    with contextlib.suppress(Exception):
                        await self.submit(group_id, trigger_type="scheduled", period_type=scheduled_period)

    async def close(self) -> None:
        if self._scheduler is not None:
            self._scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler
            self._scheduler = None
        if self._jobs:
            await asyncio.gather(*tuple(self._jobs), return_exceptions=True)

    @staticmethod
    def _log_task_error(task: asyncio.Task[Any]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            error = task.exception()
            if error:
                LOGGER.warning("群聊总结后台任务异常：%s", error)


def summary_markdown(detail: dict[str, Any]) -> str:
    header = (
        f"---\ngroup_id: {detail.get('group_id')}\nperiod_start: {detail.get('period_start')}\n"
        f"period_end: {detail.get('period_end')}\nperiod_type: {detail.get('period_type', 'custom')}\n"
        f"period_key: {detail.get('period_key', '')}\nperiod_label: {detail.get('period_label', '')}\n"
        f"messages: {detail.get('message_count')}\n---\n\n"
    )
    return header + str(detail.get("content") or "")
