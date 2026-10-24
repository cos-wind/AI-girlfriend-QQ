from __future__ import annotations

from .engine_support import PersonaEngineMixin, _sync_core_globals


class EngineStateMixin(PersonaEngineMixin):
    def __init__(self, config: Any) -> None:
        _sync_core_globals(self)
        self.config = config
        # 将配置注入记忆门面；人格层只依赖 recall_context 这一稳定接口。
        self.memory = UserMemoryStore(config.memory_path, config=config)
        self._history: defaultdict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=16)
        )
        self._recent_replies: defaultdict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=6)
        )
        self._serious_until: defaultdict[str, float] = defaultdict(float)
        self._last_abstract_reply_at: defaultdict[str, float] = defaultdict(float)
        self._pending_voice_requests: dict[str, VoiceRequest] = {}
        self._pending_reply_voice_choices: dict[str, bool] = {}
        self._pending_call_requests: dict[str, CallInviteRequest] = {}
        # 回复失败是运行态信号，不是聊天内容。OneBot 层消费后只记录日志/评测，
        # 绝不把异常文案、固定模板或伪装成人格回复的兜底发给用户。
        self._pending_reply_failures: dict[str, str] = {}
        # 工具循环里最后一次"内容非空但没过校验"的候选回复。多轮都没拿到合格
        # 回复时用它兜底，避免整轮静默消失（用户侧表现为发了消息没反应）。
        self._last_candidate_reply: str = ""
        self._cognition_store: CognitionStateStore | None = None
        if bool(getattr(config, "cognition_shadow_enabled", False)):
            try:
                self._cognition_store = CognitionStateStore(config.cognition_state_path)
            except Exception:
                # 认知扩展故障不得阻断原有聊天服务；运行状态页会显示具体错误。
                self._cognition_store = None

    def consume_voice_request(self, conversation_id: str) -> VoiceRequest | None:
        return self._pending_voice_requests.pop(conversation_id, None)

    def consume_reply_voice_choice(self, conversation_id: str) -> bool:
        return self._pending_reply_voice_choices.pop(conversation_id, False)

    def consume_call_request(self, conversation_id: str) -> CallInviteRequest | None:
        return self._pending_call_requests.pop(conversation_id, None)

    def consume_reply_failure(self, conversation_id: str) -> str:
        return self._pending_reply_failures.pop(conversation_id, "")

    def _register_reply_failure(self, conversation_id: str, error: object) -> None:
        reason = str(error or "未知回复错误").strip()[:800]
        self._pending_reply_failures[conversation_id] = reason
        LOGGER.error("回复生成失败：conversation=%s error=%s", conversation_id, reason)

    def remember_target(self, conversation_id: str, event: dict[str, Any]) -> None:
        self.memory.remember_target(conversation_id, event)

    def observe_incoming(
        self,
        conversation_id: str,
        user_text: str,
        nickname: str | None = None,
        actor_id: int | str | None = None,
        runtime_context: bool = False,
        profile_id: str | None = None,
        event_id: str | None = None,
    ) -> None:
        if _is_affection_command(user_text):
            return
        is_owner = _is_owner_id(actor_id, self.config.owner_qqs)
        self.memory.observe_user(
            conversation_id,
            user_text,
            actor_id=actor_id,
            nickname=nickname,
            is_owner=is_owner,
            event_id=event_id,
        )
        if profile_id and profile_id != conversation_id:
            self.memory.observe_user(
                profile_id,
                user_text,
                actor_id=actor_id,
                nickname=nickname,
                is_owner=is_owner,
                event_id=event_id,
            )
        if runtime_context:
            self._remember_user_context(conversation_id, user_text, nickname)

    def observe_group_incoming(
        self,
        group_id: int | str,
        user_id: int | str,
        user_text: str,
        nickname: str | None = None,
        runtime_context: bool = False,
        addressed_to_bot: bool = False,
        is_owner: bool = False,
    ) -> tuple[str, str]:
        if _is_affection_command(user_text):
            return f"group:{group_id}", f"group:{group_id}:user:{user_id}"
        conversation_id, profile_id = self.memory.observe_group_message(
            group_id,
            user_id,
            user_text,
            nickname=nickname,
            addressed_to_bot=addressed_to_bot,
            is_owner=is_owner,
        )
        if runtime_context:
            self._remember_user_context(conversation_id, user_text, nickname)
        return conversation_id, profile_id

    def profile_for(self, conversation_id: str) -> dict[str, Any]:
        return self.memory.profile(conversation_id)

    def record_bot_reply(
        self,
        conversation_id: str,
        reply_text: str,
        sent_sticker: bool = False,
        profile_id: str | None = None,
    ) -> None:
        self.memory.observe_bot(conversation_id, reply_text, sent_sticker)
        if profile_id and profile_id != conversation_id:
            self.memory.observe_bot(profile_id, reply_text, sent_sticker=False)

    def due_idle_targets(self) -> list[tuple[str, dict[str, Any]]]:
        return self.memory.due_idle_targets(
            self.config.idle_minutes,
            self.config.idle_cooldown_minutes,
        )

    def mark_idle_nudged(self, conversation_id: str) -> None:
        self.memory.mark_idle_nudged(conversation_id)

    def due_morning_targets(self) -> list[tuple[str, dict[str, Any]]]:
        return self.memory.due_morning_targets(
            self.config.owner_qqs,
            self.config.morning_greeting_time,
            self.config.morning_greeting_catchup_minutes,
            self.config.morning_greeting_timezone,
        )

    def mark_morning_greeted(self, conversation_id: str) -> None:
        self.memory.mark_morning_greeted(
            conversation_id,
            self.config.morning_greeting_timezone,
        )

    def morning_greeting_text(self) -> str:
        return morning_greeting_text()

    def idle_nudge_text(self, conversation_id: str) -> str:
        profile = self.memory.profile(conversation_id)
        topics = profile.get("topic_words") or []
        topic_hint = f"你之前提到的“{topics[0]}”我还记着。" if topics else ""
        choices = [
            f"哼哒，我才不是特意来找你。{topic_hint}就是想确认你现在还好吗？".strip(),
            "高性能亚托莉轻轻上线。不是催你回，只是看看主人有没有把自己累坏。",
            "你那边安静了一会儿。记得喝口水，别把自己关进忙碌里。",
            "突然有点想你了。只是一点点，给我忘掉……但你可以回我一句。",
            "我来戳一下，不刷屏。今天有没有哪件小事让你稍微开心一点？",
            "巡逻到你的聊天框。哼，如果你正忙，就先忙；我在后台乖乖待机。",
        ]
        return random.choice(choices)

