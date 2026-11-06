from __future__ import annotations

from .support import QZoneMixin


class QZoneAutomationMixin(QZoneMixin):
    def __init__(self, store: QZoneAutomationStore, admin_factory: Any, post_generator: Any = None, comment_generator: Any = None, fact_context_provider: Any = None) -> None:
        self.store = store
        self.admin_factory = admin_factory
        self.post_generator = post_generator
        self.comment_generator = comment_generator
        self.fact_context_provider = fact_context_provider
        self._task: asyncio.Task[None] | None = None
        self._run_lock = threading.Lock()
        self._lease_owner = f"qzone-{uuid.uuid4().hex}"
        self._fact_cache: dict[str, tuple[float, str]] = {}
        self._preview_prepare_after = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="atri-qzone-automation")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.store.release_scheduler_lease(self._lease_owner)

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                settings = self.store.settings()
                if not settings.get("enabled"):
                    continue
                await asyncio.to_thread(self.run_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 任务错误会写入日志，不能让 WebUI 调度器退出。
                self.store.log("scheduler", status="failed", error=str(exc))
                continue

    def _fact_context(self, settings: dict[str, Any], scheduled_at: float, slot_index: int | None = None) -> str:
        if not callable(self.fact_context_provider):
            return ""
        topic = topic_for_schedule(settings, scheduled_at, slot_index)
        if not any(marker in topic for marker in ("热点", "新闻", "前沿", "科普", "技术", "科学", "研究", "社会")):
            return ""
        cache_key = f"{datetime.fromtimestamp(scheduled_at, _zone(settings.get('timezone'))):%Y-%m-%d}|{topic}"
        cached_at, cached_value = self._fact_cache.get(cache_key, (0.0, ""))
        if time.time() - cached_at < 1800:
            return cached_value
        try:
            try:
                value = str(self.fact_context_provider(settings, scheduled_at, slot_index) or "").strip()
            except TypeError:
                value = str(self.fact_context_provider(settings, scheduled_at) or "").strip()
        except Exception as exc:
            self.store.log("fact_context", status="failed", error=str(exc))
            return ""
        self._fact_cache[cache_key] = (time.time(), value[:3000])
        return self._fact_cache[cache_key][1]

    def _topic_prompt(
        self,
        settings: dict[str, Any],
        scheduled_at: float,
        slot_index: int | None = None,
        fact_context: str | None = None,
    ) -> str:
        recent = [
            str(item.get("content") or "")
            for item in self.store.content_list(include_published=True)
            if item.get("status") == "published" and str(item.get("content") or "").strip()
        ][-5:]
        facts = self._fact_context(settings, scheduled_at, slot_index) if fact_context is None else fact_context
        return topic_prompt(settings, scheduled_at, slot_index, recent_contents=recent, fact_context=facts).strip()

    def _generate_post(
        self,
        settings: dict[str, Any],
        scheduled_at: float,
        slot_index: int | None = None,
        *,
        prompt: str | None = None,
        fact_context: str | None = None,
    ) -> str:
        if self.post_generator is None:
            return ""
        recent = [str(item.get("content") or "") for item in self.store.content_list() if item.get("status") == "published"][-5:]
        facts = self._fact_context(settings, scheduled_at, slot_index) if fact_context is None else fact_context
        generation_prompt = self._topic_prompt(settings, scheduled_at, slot_index, fact_context=facts) if prompt is None else prompt
        model_id = str(settings.get("post_model_profile_id") or "")
        generated = self.post_generator(generation_prompt, model_id)
        content = str((generated or {}).get("content") or "").strip()
        quality_args = {
            "fact_context": facts,
            "scheduled_at": scheduled_at,
            "timezone_value": settings.get("timezone"),
        }
        issues = content_quality_issues(content, recent, **quality_args)
        if issues:
            retry_prompt = (
                f"{generation_prompt}\n上一稿未通过质量检查：{'；'.join(issues)}。请完全换一种表达重写。"
                "有可靠事实上下文时只能使用其中明示的信息；没有时不要加入日期倒计时、新闻事件或数据。"
            )
            generated = self.post_generator(retry_prompt, model_id)
            content = str((generated or {}).get("content") or "").strip()
        if content_quality_issues(content, recent, **quality_args):
            return ""
        return content

    def _period_post_count(self, window_start: datetime) -> int:
        period_key = window_start.strftime("%Y-%m-%d")
        return max(
            self.store.count_success_since("post", window_start.timestamp()),
            self.store.count_consumed_post_slots(period_key),
        )

    def _ensure_generated_preview(self, settings: dict[str, Any]) -> None:
        """Restore one missing preview without coupling generation to page refreshes."""
        if (
            not settings.get("post_enabled")
            or not settings.get("post_auto_generate")
            or self.post_generator is None
            or self.store.next_content() is not None
        ):
            return
        now = time.time()
        if now < self._preview_prepare_after:
            return
        # Set the retry deadline before calling the model. A provider failure
        # therefore cannot turn the 30-second scheduler tick into request spam.
        self._preview_prepare_after = now + 300.0
        try:
            item = self.prepare_next_generated()
        except Exception as exc:
            self.store.log("post_prepare", status="failed", error=str(exc))
            return
        if item is not None:
            self._preview_prepare_after = 0.0

    def dashboard(self) -> dict[str, Any]:
        settings = self.store.settings()
        if settings.get("post_enabled"):
            _, window_start, _ = _period_window(settings)
            slots = schedule_times(settings)
            period_key = window_start.strftime("%Y-%m-%d")
            if settings.get("schedule_period_start") != period_key or settings.get("schedule_slots") != slots:
                self.store.save_settings({"schedule_period_start": period_key, "schedule_slots": slots})
                settings = self.store.settings()
            posted_count = self._period_post_count(window_start)
            scheduled = next_window_time(settings, posted_count=posted_count)
            settings["next_post_at"] = scheduled
            # Keep the preview and the scheduler on the same persisted slot.
            # Previously this was changed only in the response object, so a
            # refresh/restart could resurrect an older or near-immediate time.
            if abs(float(self.store.settings().get("next_post_at") or 0) - scheduled) > 1:
                self.store.save_settings({"next_post_at": scheduled})
        pending = self.store.next_content()
        if pending is not None and settings.get("post_enabled") and settings.get("post_auto_generate"):
            scheduled_at = float(settings.get("next_post_at") or 0)
            pending_at = float(pending.get("scheduled_at") or 0)
            recent = [str(item.get("content") or "") for item in self.store.content_list() if item.get("status") == "published"][-5:]
            needs_quality_reconcile = bool(content_quality_issues(str(pending.get("content") or ""), recent))
            quality_check_allowed = "quality_gate_checked" not in str(pending.get("last_error") or "")
            if needs_quality_reconcile and not quality_check_allowed:
                self.store.mark_content_rejected(int(pending["id"]), "quality_gate")
                pending = None
            if scheduled_at and (not pending_at or abs(pending_at - scheduled_at) > 60 or (needs_quality_reconcile and quality_check_allowed)):
                # One-time migration/reconciliation for drafts created by the
                # previous scheduler. Once aligned, read-only dashboard calls
                # do not invoke the model again.
                try:
                    pending = self.prepare_next_generated(scheduled_at)
                    if pending is not None and content_quality_issues(str(pending.get("content") or ""), recent):
                        self.store.mark_content_error(int(pending["id"]), "quality_gate_checked")
                except Exception as exc:
                    self.store.log("post_prepare", status="failed", error=str(exc))
        return {
            "ok": True,
            "settings": settings,
            "next_post": {
                "scheduled_at": float(settings.get("next_post_at") or 0),
                "item": pending,
                "auto_generate": bool(settings.get("post_auto_generate")),
                "prompt": str(settings.get("post_prompt") or ""),
            },
            "content_pool": self.store.content_list(),
            "comment_pool": self.store.comment_list(),
            "targets": self.store.targets(),
            "logs": self.store.logs(100),
            "today": self.store.today_counts(),
            "running": bool(self._task and not self._task.done()),
        }

    def prepare_next_generated(self, scheduled_at: float | None = None) -> dict[str, Any] | None:
        """预生成下一条自动动态，便于 WebUI 展示将要发布的正文。"""
        settings = self.store.settings()
        if not settings.get("post_enabled") or not settings.get("post_auto_generate"):
            return self.store.next_content()
        pending = self.store.next_content()
        _, window_start, _ = _period_window(settings)
        posted_count = self._period_post_count(window_start)
        # Always derive the target from the current period quota.  Trusting a
        # stale ``scheduled_at`` here was the reason deleting/reloading could
        # recreate a post at the current minute instead of the next slot.
        target_at = next_window_time(settings, posted_count=posted_count)
        if scheduled_at and float(scheduled_at) > time.time() and abs(float(scheduled_at) - target_at) <= 60:
            target_at = float(scheduled_at)
        if pending is not None:
            # A pending model-generated item created before a schedule change
            # must be regenerated for the new publication time.
            model_id = str(settings.get("post_model_profile_id") or "")
            recent = [str(item.get("content") or "") for item in self.store.content_list() if item.get("status") == "published"][-5:]
            needs_refresh = pending.get("generated_at") and (
                not pending.get("scheduled_at")
                or abs(float(pending.get("scheduled_at") or 0) - target_at) > 60
                or str(pending.get("model_profile_id") or "") != model_id
                or bool(content_quality_issues(str(pending.get("content") or ""), recent))
            )
            if needs_refresh:
                if self.post_generator is None:
                    return pending
                facts = self._fact_context(settings, target_at, posted_count)
                prompt = self._topic_prompt(settings, target_at, posted_count, fact_context=facts)
                content = self._generate_post(
                    settings,
                    target_at,
                    posted_count,
                    prompt=prompt,
                    fact_context=facts,
                )
                if content:
                    self.store.content_update(int(pending["id"]), content, "pending", prompt=prompt, model_profile_id=model_id, scheduled_at=target_at)
                    return self.store.content_get(int(pending["id"]))
                self.store.mark_content_rejected(int(pending["id"]), "quality_gate")
                return None
            return pending
        if self.post_generator is None:
            return pending
        generation_at = target_at or time.time()
        facts = self._fact_context(settings, generation_at, posted_count)
        prompt = self._topic_prompt(settings, generation_at, posted_count, fact_context=facts)
        if not prompt:
            return None
        content = self._generate_post(
            settings,
            generation_at,
            posted_count,
            prompt=prompt,
            fact_context=facts,
        )
        if not content:
            return None
        return self.store.content_add(
            content,
            prompt=prompt,
            model_profile_id=str(settings.get("post_model_profile_id") or ""),
            generated_at=time.time(),
            scheduled_at=target_at or None,
        )

    def run_once(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"ok": True, "skipped": "已有调度任务执行中"}
        run_lease = f"{self._lease_owner}:{uuid.uuid4().hex}"
        lease_acquired = False
        try:
            settings = self.store.settings()
            if not settings.get("enabled"):
                return {"ok": True, "skipped": "总控已暂停"}
            if not self.store.acquire_scheduler_lease(run_lease, ttl=600.0):
                return {"ok": True, "skipped": "其他进程持有调度租约"}
            lease_acquired = True
            self.store.save_settings({"last_scheduler_at": time.time()})
            result = {"posted": 0, "liked": 0, "commented": 0, "errors": []}
            try:
                result["posted"] = self._post_if_due(settings)
            except Exception as exc:
                result["errors"].append(f"发布：{exc}")
            self._ensure_generated_preview(settings)
            try:
                liked, commented = self._interact(settings)
                result["liked"] = liked
                result["commented"] = commented
            except Exception as exc:
                result["errors"].append(f"互动：{exc}")
            return {"ok": not result["errors"], **result}
        finally:
            if lease_acquired:
                self.store.release_scheduler_lease(run_lease)
            self._run_lock.release()

    def refresh_next_post(self) -> dict[str, Any] | None:
        """删除/人工发布后重算并展示下一条，不等待下一次 30 秒 tick。"""
        settings = self.store.settings()
        if not settings.get("post_enabled"):
            return self.store.next_content()
        _, window_start, _ = _period_window(settings)
        posted_count = self._period_post_count(window_start)
        target_at = next_window_time(settings, posted_count=posted_count)
        self.store.save_settings({"next_post_at": target_at})
        if settings.get("post_auto_generate"):
            return self.prepare_next_generated(target_at)
        return self.store.next_content()

    def publish_now(self, content_id: int) -> dict[str, Any]:
        """发布指定内容池条目；这是明确的人工操作，不受自动调度开关限制。"""
        item = self.store.content_get(content_id)
        if item is None:
            raise ValueError("内容不存在")
        if not str(item.get("content") or "").strip():
            raise ValueError("动态内容为空")
        settings = self.store.settings()
        try:
            result = self.admin_factory().post(str(item["content"]), int(settings.get("visibility", 1)))
            self.store.mark_content_published(int(item["id"]))
            self.store.log("post", tid=str(result.get("tid") or ""), content=str(item["content"]))
            self.store.save_settings({"last_post_at": time.time()})
            self.refresh_next_post()
            return {"ok": True, "item_id": int(item["id"]), "tid": str(result.get("tid") or "")}
        except Exception as exc:
            self.store.mark_content_error(int(item["id"]), str(exc))
            self.store.log("post", content=str(item["content"]), status="failed", error=str(exc))
            raise

    def _post_if_due(self, settings: dict[str, Any]) -> int:
        if not settings.get("post_enabled"):
            return 0
        now = time.time()
        local, window_start, window_end = _period_window(settings, now)
        period_key = window_start.strftime("%Y-%m-%d")
        slots = schedule_times(settings, now)
        if settings.get("schedule_period_start") != period_key or settings.get("schedule_slots") != slots:
            self.store.save_settings({"schedule_period_start": period_key, "schedule_slots": slots})
        max_posts = max(1, min(20, int(settings.get("posts_per_period", 1) or 1)))
        posted = self._period_post_count(window_start)
        if local >= window_end:
            self.store.save_settings({"next_post_at": next_window_time(settings, now=now, posted_count=posted)})
            return 0
        if posted >= max_posts:
            self.store.save_settings({"next_post_at": next_window_time(settings, now=now, posted_count=posted)})
            return 0
        # Recompute from the quota on every tick.  This makes a stale value
        # from a previous process/page harmless and enforces even spacing.
        next_at = next_window_time(settings, now=now, posted_count=posted)
        if now < next_at:
            self.store.save_settings({"next_post_at": next_at})
            return 0
        if local < window_start or local >= window_end:
            return 0
        slot_at = slots[min(posted, len(slots) - 1)]
        slot_key = f"{period_key}:{posted}:{int(slot_at)}"
        claim_token = self.store.claim_post_slot(slot_key)
        if not claim_token:
            return 0
        item: dict[str, Any] | None = None
        content = ""
        try:
            item = self.store.next_content()
            if item is not None and settings.get("post_auto_generate"):
                # A pending generated item may have been prepared for a slot that
                # was later missed or shifted. Refresh it before publishing so the
                # body, prompt and scheduled_at all describe the same slot.
                self.prepare_next_generated(next_at)
                item = self.store.next_content()
            if item is None:
                if not settings.get("post_auto_generate") or self.post_generator is None:
                    self.store.release_post_slot(slot_key, claim_token)
                    return 0
                content = self._generate_post(settings, next_at, posted)
                if not content:
                    self.store.release_post_slot(slot_key, claim_token)
                    return 0
            else:
                content = str(item["content"])
            admin = self.admin_factory()
            if not self.store.begin_post_send(slot_key, claim_token):
                self.store.release_post_slot(slot_key, claim_token)
                return 0
            result = admin.post(content, int(settings.get("visibility", 1)))
            tid = str(result.get("tid") or "")
            self.store.finish_automatic_post(
                slot_key,
                claim_token,
                tid=tid,
                content=content,
                content_id=int(item["id"]) if item is not None else None,
            )
            updates: dict[str, Any] = {"last_post_at": now}
            updates["next_post_at"] = next_window_time(settings, now=now, posted_count=posted + 1)
            try:
                self.store.save_settings(updates)
                # Keep the next future item visible immediately after a successful
                # post. It is queued for the next eligible slot and will not
                # bypass the per-period quota.
                self.prepare_next_generated(float(updates.get("next_post_at") or 0) or None)
            except Exception as prepare_exc:
                self.store.log("post_prepare", status="failed", error=str(prepare_exc))
            return 1
        except Exception as exc:
            self.store.mark_post_slot_uncertain(slot_key, claim_token)
            self.store.release_post_slot(slot_key, claim_token)
            if item is not None:
                self.store.mark_content_error(int(item["id"]), str(exc))
            self.store.log("post", content=content, status="failed", error=str(exc))
            raise

    def publish_generated_now(self, prompt: str = "", model_profile_id: str = "") -> dict[str, Any]:
        settings = self.store.settings()
        text_prompt = str(prompt or settings.get("post_prompt") or DEFAULT_SETTINGS["post_prompt"]).strip()
        if not text_prompt:
            raise ValueError("请先填写亚托莉动态提示词")
        if self.post_generator is None:
            raise RuntimeError("动态生成器尚未就绪")
        generated = self.post_generator(text_prompt, str(model_profile_id or settings.get("post_model_profile_id") or ""))
        content = str((generated or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("模型没有生成有效动态")
        result = self.admin_factory().post(content, int(settings.get("visibility", 1)))
        self.store.log("post", tid=str(result.get("tid") or ""), content=content)
        self.store.save_settings({"last_post_at": time.time()})
        self.refresh_next_post()
        return {"ok": True, "content": content, "tid": str(result.get("tid") or "")}

    def _interact(self, settings: dict[str, Any]) -> tuple[int, int]:
        targets = self.store.targets()
        has_comment_sources = bool(settings.get("comment_enabled") and settings.get("comment_use_pool", True) and self.store.comment_list(include_used=False))
        if (not targets and not has_comment_sources) or (not settings.get("like_enabled") and not settings.get("comment_enabled")):
            return 0, 0
        admin = self.admin_factory()
        target_ids = {str(item["user_id"]) for item in targets}
        # The list UI is the source of truth: every person must explicitly
        # opt in to liking/commenting. Legacy keyword/all rules are ignored.
        candidates = list(targets)
        if settings.get("comment_enabled") and settings.get("comment_use_pool", True):
            known_ids = {str(item.get("user_id")) for item in candidates}
            for pool_item in self.store.comment_list(include_used=False):
                source_user_id = str(pool_item.get("source_user_id") or "")
                if source_user_id.isdigit() and source_user_id not in known_ids:
                    candidates.append({"user_id": source_user_id, "nickname": f"QQ {source_user_id}", "enabled_comment": 0, "enabled_like": 0})
                    known_ids.add(source_user_id)
        liked = commented = 0
        for target in candidates:
            user_id = str(target["user_id"])
            feeds = admin.feeds(user_id, int(settings.get("feed_limit", 20))).get("feeds", [])
            # Bridge normally returns newest-first. Sort defensively by QQ's
            # timestamp so an oversized feed response cannot make us comment
            # on old history; automatic comments are limited to the newest 3.
            recent_comment_feeds = sorted(
                enumerate(feeds),
                key=lambda pair: (int(pair[1].get("abstime") or 0), -pair[0]),
                reverse=True,
            )[:MAX_RECENT_COMMENT_FEEDS]
            recent_comment_tids = {
                str(feed.get("tid") or "") for _, feed in recent_comment_feeds
            }
            for feed in feeds:
                text = str(feed.get("content") or "")
                tid = str(feed.get("tid") or "")
                if not tid:
                    continue
                if settings.get("like_enabled") and liked < int(settings.get("max_likes_per_run", 10)):
                    match = user_id in target_ids and bool(target.get("enabled_like", 0))
                    if match and not feed.get("liked") and not self.store.already_logged("like", tid):
                        try:
                            admin.like({"user_id": user_id, "tid": tid, "abstime": feed.get("abstime", 0)})
                            self.store.log("like", user_id=user_id, tid=tid, content=text)
                            liked += 1
                        except Exception as exc:
                            self.store.log("like", user_id=user_id, tid=tid, content=text, status="failed", error=str(exc))
                if settings.get("comment_enabled") and commented < int(settings.get("max_comments_per_run", 2)):
                    # 评论不再依赖关键词规则：只对目标动态生成评论。
                    if (tid in recent_comment_tids and bool(target.get("enabled_comment", 0))
                            and not self.store.already_logged("comment", tid)):
                        pool_item = self.store.comment_next(tid=tid, user_id=user_id) if settings.get("comment_use_pool", True) else None
                        comment = ""
                        if self.comment_generator is not None:
                            prompt = (
                                "请根据下面这条 QQ 空间动态，写一句自然、简短、真诚的评论。"
                                "不要复述原文，不要解释，只输出评论正文。评论必须由亚托莉结合动态内容现场生成，"
                                "不能直接照抄评论池草稿。\n\n"
                                f"动态作者：{target.get('nickname') or user_id}\n动态内容：{text}"
                            )
                            if pool_item and str(pool_item.get("content") or "").strip():
                                prompt += f"\n可参考的评论池草稿（仅参考语气）：{pool_item['content']}"
                            generated = self.comment_generator(prompt, str(settings.get("post_model_profile_id") or ""))
                            comment = str((generated or {}).get("content") or "").strip()
                        if not comment and pool_item is not None:
                            comment = str(pool_item.get("content") or "").replace("{nickname}", str(target.get("nickname") or ""))
                        if not comment:
                            comment = str(settings.get("comment_text") or "看到啦～")
                        if not comment:
                            continue
                        try:
                            admin.comment({"user_id": user_id, "tid": tid, "content": comment})
                            self.store.log("comment", user_id=user_id, tid=tid, content=comment)
                            if pool_item is not None:
                                self.store.mark_comment_used(int(pool_item["id"]))
                            commented += 1
                        except Exception as exc:
                            self.store.log("comment", user_id=user_id, tid=tid, content=comment, status="failed", error=str(exc))
        return liked, commented

