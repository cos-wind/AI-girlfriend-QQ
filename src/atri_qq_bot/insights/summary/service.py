from __future__ import annotations

from . import *  # noqa: F403

class GroupSummaryService:
    def __init__(self, store: InsightsStore, config: InsightsConfig) -> None:
        self.store = store
        self.config = config
        self._encoder = SemanticEncoder(config.embedding_model, local_only=config.embedding_local_only)
        self._jobs: set[asyncio.Task[Any]] = set()
        self._scheduler: asyncio.Task[None] | None = None
        self._group_sender: Callable[[str, str], Awaitable[None]] | None = None

    def set_group_sender(self, sender: Callable[[str, str], Awaitable[None]] | None) -> None:
        """注入可选的 OneBot 图片发送器；未注入时仍只生成报告，不影响旁路。"""
        self._group_sender = sender

    async def start(self) -> None:
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
        if not str(group_id).strip():
            raise ValueError("群号不能为空")
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
            str(group_id), start_at.isoformat(), end_at.isoformat(), trigger_type,
            period_type or "custom", period_key, period_label,
        )
        task = asyncio.create_task(self._generate(summary_id), name=f"atri-summary-{summary_id[:8]}")
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)
        task.add_done_callback(self._log_task_error)
        return summary_id

    async def _generate(self, summary_id: str) -> None:
        detail = await asyncio.to_thread(self.store.summary_detail, summary_id)
        if not detail:
            return
        await asyncio.to_thread(self.store.mark_summary_running, summary_id)
        messages = await asyncio.to_thread(
            self.store.group_messages,
            detail["group_id"],
            detail["period_start"],
            detail["period_end"],
            self.config.summary_max_messages,
        )
        try:
            if len(messages) < self.config.summary_min_messages:
                raise ValueError(
                    f"时间范围内只有 {len(messages)} 条消息，少于最低要求 {self.config.summary_min_messages} 条"
                )
            period_type = str(detail.get("period_type") or "custom")
            statistics = _statistics(messages, period_type=period_type, period_start=detail.get("period_start"))
            statistics["period_start"] = detail.get("period_start")
            statistics["period_end"] = detail.get("period_end")
            statistics["period_label"] = detail.get("period_label") or ""
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
            try:
                vectors = await asyncio.to_thread(
                    self._encoder.encode, [chunk["text"] for chunk in chunks]
                )
                clusters = _cluster_vectors(
                    chunks,
                    vectors,
                    self.config.topic_cluster_threshold,
                    min(self.config.topic_max_clusters, profile["max_topics"]),
                )
                statistics["clustering"] = "sentence-transformers"
            except Exception as exc:
                LOGGER.warning("话题向量聚类不可用，改用关键词聚类：%s", exc)
                clusters = _fallback_clusters(chunks, min(self.config.topic_max_clusters, profile["max_topics"]))
                statistics["clustering"] = "keyword-fallback"
            topics = _topic_payload(chunks, clusters)
            report = _fallback_report(
                detail["group_id"], topics, statistics, profile=profile, messages=messages, period_type=period_type
            )
            if self.config.judge_ready:
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
                    "atri_closing", "important_messages",
                ):
                    if field in report:
                        report_sections[field] = report[field]
            await asyncio.to_thread(
                self.store.complete_summary,
                summary_id,
                title=report["title"],
                message_count=len(messages),
                topics=report["topics"],
                key_points=report["key_points"],
                statistics=statistics,
                content=_visible_text(report["summary"]),
            )
            if detail.get("trigger_type") in {"scheduled", "manual_send"} and self._group_sender is not None:
                try:
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
                        self.store.path.parent / "summary_reports" / f"{summary_id}.png",
                    )
                    # OneBot 直接发送本机 PNG，QQ 端显示为图片消息，而不是链接或长文本。
                    await self._group_sender(str(detail["group_id"]), str(image_path))
                    if detail.get("trigger_type") == "scheduled":
                        await asyncio.to_thread(
                            self.store.mark_group_summary_schedule_sent,
                            str(detail["group_id"]), period_type,
                            datetime.now().astimezone().replace(second=0, microsecond=0, tzinfo=None).isoformat(timespec="minutes"),
                        )
                except Exception as exc:
                    LOGGER.warning("定时群聊总结生成成功但发送失败：group=%s error=%s", detail["group_id"], exc)
            LOGGER.info("群聊总结完成：id=%s group=%s messages=%s", summary_id, detail["group_id"], len(messages))
        except Exception as exc:
            await asyncio.to_thread(self.store.fail_summary, summary_id, str(exc), len(messages))
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
