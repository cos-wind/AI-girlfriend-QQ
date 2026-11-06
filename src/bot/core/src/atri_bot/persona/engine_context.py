from __future__ import annotations

from atri_shared.reply_trace import span, traced

from . import core as _core


class EngineContextMixin:
    def _remember_user_context(
        self, conversation_id: str, user_text: str, nickname: str | None = None
    ) -> None:
        if _core.is_memory_pollution_text(user_text):
            return
        self._history[conversation_id].append(
            {"role": "user", "content": _core._format_user_content(conversation_id, user_text, nickname)}
        )

    def _remember(
        self,
        conversation_id: str,
        user_text: str,
        reply_text: str,
        nickname: str | None = None,
    ) -> None:
        if not _core.is_memory_pollution_text(user_text):
            self._history[conversation_id].append(
                {
                    "role": "user",
                    "content": _core._format_user_content(conversation_id, user_text, nickname),
                }
            )
        if not _core.is_memory_pollution_text(reply_text):
            self._history[conversation_id].append({"role": "assistant", "content": reply_text})
            self._recent_replies[conversation_id].append(reply_text)

    @traced('memory')
    def _recent_conversation_context(
        self,
        conversation_id: str,
        *,
        current_user_text: str = "",
        limit: int = 12,
    ) -> str:
        lines: list[str] = []
        entries = self.memory.recent_history(conversation_id, limit=limit + 3)
        skipped_current = False
        selected: list[dict[str, _core.Any]] = []
        for entry in reversed(entries):
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            if _core.is_memory_pollution_text(text):
                continue
            role = entry.get("role")
            if (
                not skipped_current
                and role == "user"
                and current_user_text
                and _core._normalize_for_compare(text)
                == _core._normalize_for_compare(current_user_text)
            ):
                skipped_current = True
                continue
            selected.append(entry)
            if len(selected) >= limit:
                break

        is_group = conversation_id.startswith("group:")
        for entry in reversed(selected):
            role = entry.get("role")
            text = str(entry.get("text") or "").strip()
            if is_group:
                text = _core._sanitize_group_mentions(text)
            if role == "assistant":
                speaker = "亚托莉"
            elif is_group:
                speaker = str(entry.get("nickname") or "群友").strip() or "群友"
                if _core.re.fullmatch(r"\d{5,}", speaker):
                    speaker = "群友"
            else:
                speaker = "用户"
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    @traced('memory')
    def _recent_conversation_messages(
        self,
        conversation_id: str,
        *,
        current_user_text: str = "",
        limit: int = 12,
        include_assistant: bool = True,
    ) -> list[dict[str, str]]:
        entries = self.memory.recent_history(conversation_id, limit=limit + 3)
        skipped_current = False
        selected: list[dict[str, _core.Any]] = []
        for entry in reversed(entries):
            text = str(entry.get("text") or "").strip()
            if not text or _core.is_memory_pollution_text(text):
                continue
            role = str(entry.get("role") or "")
            if (
                not skipped_current
                and role == "user"
                and current_user_text
                and _core._normalize_for_compare(text)
                == _core._normalize_for_compare(current_user_text)
            ):
                skipped_current = True
                continue
            if role not in {"user", "assistant"}:
                continue
            if role == "assistant" and not include_assistant:
                continue
            selected.append(entry)
            if len(selected) >= limit:
                break

        is_group = conversation_id.startswith("group:")
        messages: list[dict[str, str]] = []
        for entry in reversed(selected):
            role = str(entry.get("role"))
            text = str(entry.get("text") or "").strip()
            if is_group:
                text = _core._sanitize_group_mentions(text)
            if role == "user" and is_group:
                speaker = str(entry.get("nickname") or "群友").strip() or "群友"
                if _core.re.fullmatch(r"\d{5,}", speaker):
                    speaker = "群友"
                text = f"{speaker}: {text}"
            messages.append({"role": role, "content": text})
        return messages

    @traced('memory')
    def _recent_group_context(
        self,
        conversation_id: str,
        current_user_text: str = "",
    ) -> str:
        return self._recent_conversation_context(
            conversation_id,
            current_user_text=current_user_text,
            limit=12,
        )

    @traced('memory')
    def _recent_private_context(
        self,
        conversation_id: str,
        current_user_text: str = "",
    ) -> str:
        return self._recent_conversation_context(
            conversation_id,
            current_user_text=current_user_text,
            limit=12,
        )

    def _needs_rewrite(self, conversation_id: str, user_text: str, reply_text: str) -> bool:
        if not reply_text or len(reply_text.strip()) < 2:
            return True

        if _core._persona_violations(user_text, reply_text):
            return True

        if _core._is_correction(user_text) and _core._question_count(reply_text) > 0:
            return True

        if _core._question_count(reply_text) > 1:
            return True

        if (
            _core._asks_for_direct_suggestion(user_text)
            and not _core._is_distress(user_text)
            and not _core._has_concrete_suggestion(reply_text)
        ):
            return True

        if _core._needs_direct_answer(user_text) and _core._is_deflecting_answer(reply_text):
            return True

        if _core._asks_for_stance(user_text) and not _core._has_stance(reply_text):
            return True

        if _core._is_distress(user_text) and not _core._has_specific_support_move(reply_text):
            return True

        normalized_reply = _core._normalize_for_compare(reply_text)
        if any(pattern in reply_text for pattern in _core.GENERIC_REPLY_PATTERNS):
            if not _core._shares_content_word(user_text, reply_text):
                return True

        for old_reply in self._recent_replies[conversation_id]:
            similarity = _core.SequenceMatcher(
                None, normalized_reply, _core._normalize_for_compare(old_reply)
            ).ratio()
            if similarity >= 0.74:
                return True

        return False

    def _finalize_reply(
        self,
        conversation_id: str,
        user_text: str,
        reply_text: str,
        *,
        strict_quality: bool = True,
    ) -> str:
        reply_text = _core._normalize_reply(reply_text)
        reply_text = _core._redact_sensitive_output(
            reply_text,
            is_group=conversation_id.startswith("group:"),
        )
        if conversation_id.startswith("group:"):
            reply_text = _core._sanitize_group_mentions(reply_text)
        if strict_quality and _core._question_count(reply_text) > 1:
            reply_text = _core._trim_extra_questions(reply_text, keep_questions=1)
        if not reply_text:
            raise RuntimeError("模型最终回复为空")
        if any(pattern in reply_text for pattern in _core.FAILURE_TEMPLATE_PATTERNS):
            raise RuntimeError("模型生成了已禁用的失败兜底文案")
        if _core._looks_incomplete_reply(reply_text):
            raise RuntimeError("模型最终回复没有完整收尾")
        violations = _core._persona_violations(user_text, reply_text) if strict_quality else []
        if strict_quality and violations:
            raise RuntimeError(f"模型最终回复未通过质量检查：{'；'.join(violations)}")
        if _core.has_illegal_language_or_garbage(reply_text):
            raise RuntimeError("模型最终回复包含乱码或异常语言")
        return reply_text

    def _fallback_reply(self, conversation_id: str, text: str) -> str:
        """兼容旧调用点；失败时必须保持静默，禁止生成用户可见模板。"""
        return ""

