from __future__ import annotations

from . import _locked_mutation
from .support import MemoryMixin


class MemoryExtractionMixin(MemoryMixin):
    def _enqueue_memory_extraction(
        self,
        conversation_id: str,
        text: str,
        now: float,
        *,
        visibility: str,
        source_context: str | None,
        scope_kind: str,
    ) -> None:
        """把画像提取放入有界后台队列。

        这里故意只做快照和入队，不调用模型、不等待结果；消息主链路在此之后
        继续完成原有保存和回复。后台回写前会重新加载磁盘状态，避免覆盖 WebUI
        或另一条消息刚刚写入的内容。
        """
        if not self._memory_worker.enabled:
            return
        item = self._conversation(conversation_id, save=False)
        structured = _ensure_structured_memory(item)
        known_memory = tuple(
            f"{entry.get('key')}: {entry.get('value')}"
            for bucket in ("l1", "l2")
            for entry in list(structured.get(bucket) or [])[-12:]
            if isinstance(entry, dict)
            and entry.get("state") not in {"expired", "deleted", "rejected"}
        )
        history = list(item.get("history") or [])
        recent_context = tuple(
            f"{entry.get('role') or 'user'}: {entry.get('text') or ''}"
            for entry in history[-12:]
            if isinstance(entry, dict) and str(entry.get("text") or "").strip()
        )
        request = MemoryExtractionRequest(
            conversation_id=conversation_id,
            subject_id=conversation_id,
            text=text,
            recent_context=recent_context,
            known_memory=known_memory,
            now=now,
            visibility=visibility,
            source_context=source_context,
            scope_kind=scope_kind,
        )
        if self._memory_worker.submit(request):
            LOGGER.debug("记忆提取任务已入队 conversation=%s scope=%s", conversation_id, scope_kind)

    @_locked_mutation
    def _apply_extraction_result(self, result: MemoryExtractionResult) -> None:
        """在主进程内合并后台结果；失败只记日志，不影响下一条消息。"""
        request = result.request
        file_state_before = self._current_file_state()
        item = self._conversation(request.conversation_id, save=False)
        memory = _ensure_structured_memory(item)
        # WebUI 手工编辑优先级高于已经在队列里的旧消息。否则用户刚删除的
        # 记忆可能被旧任务重新写回，表现为“保存后又恢复”。新消息的时间戳
        # 晚于编辑时间时仍可正常进入提取流程。
        manual_edit_at = _as_float(item.get("memory_manual_edit_at")) or 0.0
        if manual_edit_at and request.now < manual_edit_at:
            LOGGER.debug(
                "跳过早于 WebUI 编辑的后台画像结果 conversation=%s",
                request.conversation_id,
            )
            return
        # WebUI 是独立 HTTP 服务，和本进程不共享 Python 锁。若后台读取快照
        # 后文件已经被 WebUI/人工流程改过，宁可丢弃这一批旧结果，也不能把
        # 旧画像覆盖回去；下一条真实消息会重新排队提取。
        if self._current_file_state() != file_state_before:
            self._reload_if_changed()
            return
        memory_ids: list[str] = []
        for operation in result.operations:
            # core 的操作入口接收 conversation item，并在内部取出
            # item["structured_memory"]；不能把已经取出的 memory 再传进去，
            # 否则会意外生成 structured_memory.structured_memory 嵌套树。
            memory_id = _memory_core.apply_extraction_operation(item, operation, request.now)
            if memory_id:
                memory_ids.append(str(memory_id))
        memory = _ensure_structured_memory(item)
        _memory_core._link_related_memories(memory, memory_ids)
        if memory_ids:
            if self._current_file_state() != file_state_before:
                self._reload_if_changed()
                LOGGER.debug(
                    "检测到外部记忆编辑，放弃旧后台画像结果 conversation=%s",
                    request.conversation_id,
                )
                return
            self._save()
            LOGGER.info(
                "后台画像提取完成 conversation=%s operations=%d model=%s",
                request.conversation_id,
                len(memory_ids),
                result.model_used,
            )
        if result.error:
            LOGGER.debug(
                "后台画像模型不可用，已保留规则提取结果 conversation=%s error=%s",
                request.conversation_id,
                result.error,
            )

    def memory_extraction_status(self) -> dict[str, Any]:
        """返回后台画像提取状态；仅用于 WebUI/诊断，不改变记忆。"""
        status = self._memory_worker.status()
        status["backfill_running"] = bool(self._backfill_thread and self._backfill_thread.is_alive())
        return status

    def _backfill_history_profiles(self) -> None:
        """低优先级回放旧 history，补齐升级前没有结构化画像的用户。

        只调用确定性提取器，不在启动时批量加载大模型；模型增强由真实新消息
        通过有界队列完成。每个会话单独持锁和保存，主回复最多只等待一次很短
        的锁竞争，异常会被吞掉并记录，绝不影响服务启动。
        """
        try:
            limit = self._memory_backfill_max_conversations
        except (TypeError, ValueError):
            limit = 250
        conversations = list(self._data.get("conversations", {}).items())[: max(10, min(limit, 500))]
        for conversation_id, original_item in conversations:
            try:
                history = list((original_item or {}).get("history") or [])
                if len(history) < 2:
                    continue
                with self._memory_state_lock:
                    item = self._conversation(conversation_id, save=False)
                    # 回填是一次性迁移；打标后重启不再重复扫描和写盘，避免启动抖动。
                    if int(item.get("memory_backfill_version", 0) or 0) >= MEMORY_BACKFILL_VERSION:
                        continue
                    memory = _ensure_structured_memory(item)
                    scope_kind = (
                        "group"
                        if conversation_id.startswith("group:") and ":user:" not in conversation_id
                        else "person"
                    )
                    visibility = (
                        conversation_id
                        if scope_kind == "group"
                        else "private"
                    )
                    changed = False
                    for entry in history[-300:]:
                        if not isinstance(entry, dict) or entry.get("role") != "user":
                            continue
                        text = _shorten(str(entry.get("text") or ""), MAX_MEMORY_TEXT_CHARS)
                        if not text or is_memory_pollution_text(text):
                            continue
                        operations = _memory_core_deterministic_operations(
                            text,
                            now=_as_float(entry.get("at")) or time.time(),
                            visibility=visibility,
                            source_context=visibility if scope_kind == "group" else None,
                            scope_kind=scope_kind,
                        )
                        for operation in operations:
                            if _memory_core.apply_extraction_operation(item, operation, operation.get("updated_at") or time.time()):
                                changed = True
                    item["memory_backfill_version"] = MEMORY_BACKFILL_VERSION
                    changed = True
                    if changed:
                        self._save()
                # 让出调度权，避免历史较多时与消息线程争用 CPU/磁盘。
                time.sleep(0.02)
            except Exception:
                LOGGER.exception("历史画像回放失败 conversation=%s", conversation_id)

    def _morning_candidate_targets(
        self, owner_qqs: Iterable[int]
    ) -> list[tuple[str, dict[str, Any]]]:
        owner_ids = [int(qq) for qq in owner_qqs if int(qq) > 0]
        if owner_ids:
            return [
                (f"private:{qq}", {"message_type": "private", "user_id": qq})
                for qq in owner_ids
            ]

        candidates: list[tuple[str, dict[str, Any]]] = []
        for conversation_id, item in self._data.get("conversations", {}).items():
            target = item.get("target") or {}
            if target.get("message_type") == "private" and target.get("user_id"):
                candidates.append((conversation_id, target))
        return candidates
