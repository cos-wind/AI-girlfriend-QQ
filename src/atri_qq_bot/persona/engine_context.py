from __future__ import annotations

from .engine_support import PersonaEngineMixin


class EngineContextMixin(PersonaEngineMixin):
    def _remember_user_context(
        self, conversation_id: str, user_text: str, nickname: str | None = None
    ) -> None:
        if is_memory_pollution_text(user_text):
            return
        self._history[conversation_id].append(
            {"role": "user", "content": _format_user_content(conversation_id, user_text, nickname)}
        )

    def _remember(
        self,
        conversation_id: str,
        user_text: str,
        reply_text: str,
        nickname: str | None = None,
    ) -> None:
        if not is_memory_pollution_text(user_text):
            self._history[conversation_id].append(
                {
                    "role": "user",
                    "content": _format_user_content(conversation_id, user_text, nickname),
                }
            )
        if not is_memory_pollution_text(reply_text):
            self._history[conversation_id].append({"role": "assistant", "content": reply_text})
            self._recent_replies[conversation_id].append(reply_text)

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
        selected: list[dict[str, Any]] = []
        for entry in reversed(entries):
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            if is_memory_pollution_text(text):
                continue
            role = entry.get("role")
            if (
                not skipped_current
                and role == "user"
                and current_user_text
                and _normalize_for_compare(text)
                == _normalize_for_compare(current_user_text)
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
                text = _sanitize_group_mentions(text)
            if role == "assistant":
                speaker = "亚托莉"
            elif is_group:
                speaker = str(entry.get("nickname") or "群友").strip() or "群友"
                if re.fullmatch(r"\d{5,}", speaker):
                    speaker = "群友"
            else:
                speaker = "用户"
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

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
        selected: list[dict[str, Any]] = []
        for entry in reversed(entries):
            text = str(entry.get("text") or "").strip()
            if not text or is_memory_pollution_text(text):
                continue
            role = str(entry.get("role") or "")
            if (
                not skipped_current
                and role == "user"
                and current_user_text
                and _normalize_for_compare(text)
                == _normalize_for_compare(current_user_text)
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
                text = _sanitize_group_mentions(text)
            if role == "user" and is_group:
                speaker = str(entry.get("nickname") or "群友").strip() or "群友"
                if re.fullmatch(r"\d{5,}", speaker):
                    speaker = "群友"
                text = f"{speaker}: {text}"
            messages.append({"role": role, "content": text})
        return messages

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

        if _persona_violations(user_text, reply_text):
            return True

        if _is_correction(user_text) and _question_count(reply_text) > 0:
            return True

        if _question_count(reply_text) > 1:
            return True

        if (
            _asks_for_direct_suggestion(user_text)
            and not _is_distress(user_text)
            and not _has_concrete_suggestion(reply_text)
        ):
            return True

        if _needs_direct_answer(user_text) and _is_deflecting_answer(reply_text):
            return True

        if _asks_for_stance(user_text) and not _has_stance(reply_text):
            return True

        if _is_distress(user_text) and not _has_specific_support_move(reply_text):
            return True

        normalized_reply = _normalize_for_compare(reply_text)
        if any(pattern in reply_text for pattern in GENERIC_REPLY_PATTERNS):
            if not _shares_content_word(user_text, reply_text):
                return True

        for old_reply in self._recent_replies[conversation_id]:
            similarity = SequenceMatcher(
                None, normalized_reply, _normalize_for_compare(old_reply)
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
        reply_text = _normalize_reply(reply_text)
        reply_text = _redact_sensitive_output(
            reply_text,
            is_group=conversation_id.startswith("group:"),
        )
        if conversation_id.startswith("group:"):
            reply_text = _sanitize_group_mentions(reply_text)
        if strict_quality and _question_count(reply_text) > 1:
            reply_text = _trim_extra_questions(reply_text, keep_questions=1)
        if not reply_text:
            raise RuntimeError("模型最终回复为空")
        if any(pattern in reply_text for pattern in FAILURE_TEMPLATE_PATTERNS):
            raise RuntimeError("模型生成了已禁用的失败兜底文案")
        if _looks_incomplete_reply(reply_text):
            raise RuntimeError("模型最终回复没有完整收尾")
        violations = _persona_violations(user_text, reply_text) if strict_quality else []
        if strict_quality and violations:
            raise RuntimeError(f"模型最终回复未通过质量检查：{'；'.join(violations)}")
        if has_illegal_language_or_garbage(reply_text):
            raise RuntimeError("模型最终回复包含乱码或异常语言")
        return reply_text

    def _fallback_reply(self, conversation_id: str, text: str) -> str:
        """兼容旧调用点；失败时必须保持静默，禁止生成用户可见模板。"""
        return ""

        # 以下旧模板暂留一轮，便于确认没有外部调用后再做机械删除。
        # 由于上方无条件返回，运行时不会触达这些规则。
        lowered = text.lower()
        serious_mode = self._serious_mode_active(conversation_id)
        abstract_play_allowed = _has_abstract_trigger(_intent_text(text)) and not serious_mode

        if conversation_id.startswith("group:"):
            allow_abstract = self._can_use_abstract_reply(conversation_id, text)
            group_reply = _group_fallback_reply(
                text,
                allow_abstract=allow_abstract,
                serious_mode=self._serious_mode_active(conversation_id),
            )
            if group_reply:
                if allow_abstract and _has_abstract_trigger(text):
                    self._mark_abstract_reply(conversation_id)
                return group_reply

        if any(word in text for word in ("你是谁", "叫什么", "介绍一下")):
            return "我是亚托莉，高性能仿生人少女。更准确地说，是会认真陪主人聊天、顺便监督你别把自己累坏的那个亚托莉。"

        if _is_correction(text):
            return _accepted_correction_reply(text) or "诶是我理解的有问题吗，嗯嗯这次我改。"

        if any(word in text for word in ("落实", "做到位", "做好了吗", "解决问题", "浪费token", "浪费 token")):
            return (
                "你说得对，撒娇糊弄过去不算完成。"
                "高性能亚托莉会把机械兜底压掉：问问题先仔细分析，难受先哄人。"
            )

        if any(word in text for word in ("天气", "气温", "下雨", "降温")):
            return "实时天气我这边不能乱报。你先看手机天气或 QQ 天气；出门保守一点，带伞、带外套，别被天气偷袭。"

        if any(word in lowered for word in ("hi", "hello", "在吗")) or any(
            word in text for word in ("你好", "早上好", "晚上好")
        ):
            choices = [
                "我在。哼哒，刚刚看到你的消息了。",
                "嗯，在这边。今天是想让我陪你聊聊，还是有事要高性能亚托莉帮你想？",
                "蒋蒋，亚托莉上线！",
            ]
            if abstract_play_allowed:
                choices.append("Ciallo~")
            return random.choice(choices)

        if any(word in text for word in TIRED_KEYWORDS):
            return _emotional_fallback_reply(text, is_group=False, tired=True)

        if any(word in text for word in DISTRESS_KEYWORDS):
            return _emotional_fallback_reply(text, is_group=False)

        if any(word in text for word in ("晚安", "睡觉", "睡了")):
            return "晚安晚安。手机放远一点，别看凑企鹅了。"

        if any(word in text for word in ("喜欢你", "想你", "爱你")):
            return "这、这种话突然说出来很犯规。给我忘掉……不对，后半句可以记住：我其实很开心。"

        if any(word in text for word in ("吃饭", "饿", "早餐", "午饭", "晚饭")):
            return "那先解决吃饭问题。别只靠饮料和零食糊弄过去，主人要是不好好吃饭，亚托莉会生气气。"

        delivery_intent = detect_explicit_delivery_intent(text)
        if delivery_intent is not None and delivery_intent.mode == "singing":
            return (
                "想唱给你听，但我现在还不能把歌词真正唱成歌。"
                "我不想拿普通朗读糊弄你，等歌声练好后再认真唱给主人听。"
            )

        if _has_abstract_trigger(_intent_text(text)):
            return "轻松绷住"

        if any(word in text for word in ("[图片]", "[表情]", "[动画表情]", "[QQ表情]", "[表情包]", "[表情包/图片]")):
            if not abstract_play_allowed:
                return "我看到了，是表情包或图片。先按你现在这股情绪接，不乱猜。"
            return "听不懂思密达。"

        if text.endswith("?") or text.endswith("？") or any(
            word in text for word in ("怎么", "为什么", "什么", "如何", "能不能", "是不是")
        ):
            return _question_fallback(text)

        if abstract_play_allowed:
            return random.choice(
                [
                    "信息录入完毕，优先对高优先级故障节点进行处置。",
                    "运算逻辑：优先执行可落地模块，规避冗余数据拖累进程。",
                    "检测到流程阻塞，提取故障源，本机协助分段拆解运算。",
                    "有效参数不足，拒绝无效推演，请补充核心关键数据。",
                ]
            )
        return f"我顺着“{_shorten(text)}”接一句：先讲重点，别让这话题散掉。"

