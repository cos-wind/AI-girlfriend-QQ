from __future__ import annotations

import json
import random
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..group_chat import GROUP_PROMPT, group_nudge_text
from ..group_reply_focus import GroupReplyFocus
from ..application.automatic_tool_runner import AutomaticToolRunner
from ..iteration import judge_correction, iteration_prompt_hint
from ..language_guard import has_illegal_language_or_garbage
from ..llm_tools import (
    AUTOMATIC_TOOL_INSTRUCTION_PROMPT,
    FINAL_ANSWER_TOOL_NAME,
    TOOL_INSTRUCTION_PROMPT,
    ToolExecutionReceipt,
    append_tool_results,
    available_tool_schemas,
    final_answer_payload_from_call,
    has_unsupported_deferred_action,
    has_unverified_research_claim,
    rejected_final_answer_messages,
    tool_calls_from_message,
)
from ..lore import (
    ATRI_LORE_PROMPT,
    appearance_direct_reply,
    has_lore_trigger,
    lore_direct_reply,
)
from ..memory import UserMemoryStore, is_memory_pollution_text
from ..prompting import load_prompt, render_prompt
from ..proactive import morning_greeting_text, safe_zoneinfo
from ..voice import (
    CallInviteRequest,
    VoiceRequest,
    detect_explicit_delivery_intent,
    evaluate_call_request,
    evaluate_reply_voice_choice,
    evaluate_voice_request,
    load_voice_behavior,
    voice_policy_prompt,
)


PERSONA_PROMPT = load_prompt("atri_persona")


# 运行中的规则统一从 docs/prompts 读取；代码只保留加载 seam。
REWRITE_PROMPT = load_prompt("rewrite")
LANGUAGE_GUARD_PROMPT = load_prompt("language_guard")
LANGUAGE_RETRY_PROMPT = load_prompt("language_retry")
COMFORT_REPAIR_PROMPT = load_prompt("comfort_repair")



GENERIC_REPLY_PATTERNS = (
    "我听着呢",
    "慢慢讲给我听",
    "一点点理清楚",
    "不只是表面",
    "我会把注意力放在你这里",
    "可以继续说",
    "我理解你的感受",
    "我能理解你",
    "你的感受是合理的",
    "你并不孤单",
    "我会一直陪着你",
    "保持积极",
    "别想太多",
    "如果你愿意的话",
    "提供情绪价值",
)

CORRECTION_KEYWORDS = (
    "答非所问",
    "没懂",
    "重复",
    "循环",
    "不像真人",
    "错位",
    "不对",
    "说怪话",
    "奇怪的话",
    "莫名其妙",
    "人机",
    "固定文案",
    "模板",
    "思考过程",
    "分析过程",
    "意图识别",
    "不要展现",
    "不要输出",
)

BANNED_ASSISTANT_PATTERNS = (
    "作为一个AI",
    "作为AI",
    "作为一名AI",
    "语言模型",
    "我是一个人工智能",
    "用户您好",
    "客服",
    "以下是",
    "分析如下",
    "作为你的AI女友",
    "情绪价值",
    "本地模式",
    "我抓到重点了",
    "我换个更日常的说法",
    "换成亚托莉自己的说法",
    "我先给个直接建议",
    "这句像是在问我具体答案",
    "你把问题再说完整一点",
    "你要结论版",
    "还是要我陪你一步步拆",
    "我先按你的问题来接",
    "我会直接给你想办法",
    "Thinking",
    "thinking",
    "done thinking",
    "...done thinking",
    "<think>",
    "</think>",
    "思考过程",
    "意图识别",
    "用户要求",
    "用户说",
    "关键点",
    "回复思路",
    "最终回复",
    "一起拆",
    "好感度",
    "亲密值",
    "亲密度",
    "affection",
    "L1",
    "L2",
    "L3",
    "置信度",
    "活跃度",
    "结构化记忆",
    "根据记忆",
    "根据我的记忆",
    "我已记录",
    "读取记忆",
    "后台数值",
)

DISTRESS_KEYWORDS = (
    "难受",
    "难过",
    "烦",
    "焦虑",
    "压力",
    "崩溃",
    "委屈",
    "不开心",
    "心累",
    "破防",
    "想哭",
)

TIRED_KEYWORDS = ("累", "困", "疲惫", "不想动", "撑不住", "熬不住")

STANCE_KEYWORDS = (
    "你觉得",
    "你认为",
    "对吗",
    "对不对",
    "该不该",
    "要不要",
    "能不能",
    "合适吗",
    "值不值得",
    "有没有必要",
    "支持吗",
    "反对吗",
)

STANCE_MARKERS = (
    "我觉得",
    "我认为",
    "我不赞成",
    "不赞成",
    "我支持",
    "支持",
    "我反对",
    "反对",
    "我更倾向",
    "更倾向",
    "我会选",
    "我建议",
    "不建议",
    "可以",
    "不可以",
    "别",
    "不要",
    "应该",
    "不应该",
)

DEFLECTION_PATTERNS = (
    "告诉我更多",
    "说完整一点",
    "再说清楚一点",
    "需要更多信息",
    "这取决于",
    "看情况",
    "你要结论版",
    "还是要我陪你",
    "我先按你的问题来接",
    "我会直接给你想办法",
    "慢慢讲给我听",
    "接住",
)

LORE_IMAGERY_WORDS = (
    "深海",
    "灯塔",
    "水下",
    "海底",
    "海里",
    "海面",
    "打捞",
    "沉没",
    "海风",
    "旧仓库",
    "岸边",
    "水车",
    "潮湿夏天",
    "被带回岸上",
    "灯亮了",
    "灯开了",
    "路就通了",
    "留个灯",
    "照亮",
    "亮起来",
)

STALE_MEME_WORDS = (
    "绝绝子",
    "栓Q",
    "家人们",
    "芜湖",
    "yyds",
    "YYDS",
    "尊嘟假嘟",
    "我真的会谢",
)

REAL_WORLD_ACTION_PATTERNS = (
    "我刚把",
    "我刚拿",
    "我给你泡",
    "我给你倒",
    "我给你按",
    "按按肩膀",
    "揉揉肩",
    "摸摸头",
    "抱抱你",
    "我看到",
    "我听到",
    "听到你",
    "你的声音",
    "声音都变了",
    "我在冰箱",
    "冰箱里",
    "今天天气不错",
    "天气不错",
    "外面天气",
    "倒进杯子",
    "拿出来",
)

HARD_REALITY_CLAIM_PATTERNS = (
    "我刚拿",
    "我给你泡",
    "我给你倒",
    "我给你按",
    "我在冰箱",
    "冰箱里",
    "今天天气不错",
    "天气不错",
    "外面天气",
    "倒进杯子",
    "拿出来",
)

SERIOUS_MODE_SECONDS = 20 * 60
ABSTRACT_REPLY_COOLDOWN_SECONDS = 8 * 60
ABSTRACT_REPLY_CHANCE = 0.35

ABSTRACT_TRIGGER_WORDS = (
    "绷不住",
    "蚌埠住",
    "抽象",
    "逆天",
    "红温",
    "破防",
    "乐",
    "6",
)

SERIOUS_MODE_HINTS = (
    "讲中文",
    "说中文",
    "正常说",
    "别发怪话",
    "不要发怪话",
    "别说外语",
    "不要说外语",
    "别玩梗",
    "先别玩梗",
    "认真点",
    "正经点",
    "别抽象",
    "讲人话",
    "说人话",
    "别乱说",
    "不要乱说",
    "别胡言乱语",
    "不要胡言乱语",
)

BOT_REPAIR_HINTS = (
    "你是真蠢",
    "太蠢",
    "有点蠢",
    "傻福",
    "傻逼",
    "恶心我",
    "个人机",
    "人机",
    "机器味",
    "根本不懂人类",
    "答非所问",
    "莫名其妙",
    "胡言乱语",
    "说怪话",
    "奇怪的话",
    "正常点",
    "正经点",
    "别给我拽日语",
    "别发日语",
    "不要发日语",
    "别说外语",
    "不要说外语",
)

ABSTRACT_NOISE_PATTERNS = (
    "Ciallo",
    "Robotto",
    "思密达",
    "咕咕嘎嘎",
    "chat模块",
    "meaning",
    "调戏ai",
    "调戏AI",
    "原神是一款",
    "恢复出厂设置",
    "高优先级故障节点",
    "有效参数不足",
    "运算逻辑",
)


def _has_current_visual_context(tool_context: Any | None) -> bool:
    context = tool_context
    visited: set[int] = set()
    while context is not None and id(context) not in visited:
        visited.add(id(context))
        if getattr(context, "visual_kind", "") or getattr(context, "visual_data", None):
            return True
        findings = getattr(context, "findings", None)
        if isinstance(findings, list) and any(
            str(item).startswith(
                ("图片内容分析", "表情包情绪分析", "图片信息", "表情包信息")
            )
            for item in findings
        ):
            return True
        context = getattr(context, "material_context", None)
    return False


def _visual_fail_safe_context(tool_context: Any | None) -> Any | None:
    context = tool_context
    visited: set[int] = set()
    while context is not None and id(context) not in visited:
        visited.add(id(context))
        fail_safe_check = getattr(context, "requires_visual_fail_safe", None)
        if callable(fail_safe_check) and fail_safe_check():
            return context
        context = getattr(context, "material_context", None)
    return None


class AtriReplyEngine:
    def __init__(self, config: Any) -> None:
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

    def consume_voice_request(self, conversation_id: str) -> VoiceRequest | None:
        return self._pending_voice_requests.pop(conversation_id, None)

    def consume_reply_voice_choice(self, conversation_id: str) -> bool:
        return self._pending_reply_voice_choices.pop(conversation_id, False)

    def consume_call_request(self, conversation_id: str) -> CallInviteRequest | None:
        return self._pending_call_requests.pop(conversation_id, None)

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
        )
        if profile_id and profile_id != conversation_id:
            self.memory.observe_user(
                profile_id,
                user_text,
                actor_id=actor_id,
                nickname=nickname,
                is_owner=is_owner,
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

    async def generate_proactive_message(
        self,
        conversation_id: str,
        event_type: str,
        policy: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, str]:
        self._pending_voice_requests.pop(conversation_id, None)
        timezone = safe_zoneinfo(str(policy.get("timezone") or "Asia/Shanghai"))
        local_now = now.astimezone(timezone) if now else datetime.now(timezone)
        is_group = conversation_id.startswith("group:") and ":user:" not in conversation_id
        if not policy.get("use_ai", True):
            return {
                "text": "",
                "source": "skipped-ai-disabled",
                "error": "主动消息已关闭 AI 生成，本次不发送模板",
            }
        if not self.config.ai_enabled:
            return {
                "text": "",
                "source": "skipped-no-model",
                "error": "未配置聊天模型，本次主动消息未发送",
            }

        profile = self.memory.profile(conversation_id)
        history = self.memory.recent_history(
            conversation_id,
            limit=int(policy.get("history_limit", 8)),
        )
        state = self.memory.proactive_state(conversation_id)
        human_pipeline = bool(getattr(self.config, "human_reply_pipeline_enabled", True))
        history_text = "\n".join(
            f"{(entry.get('nickname') or '群友') if is_group and entry.get('role') == 'user' else ('用户' if entry.get('role') == 'user' else '亚托莉')}：{str(entry.get('text') or '')[:160]}"
            for entry in history
            if entry.get("text")
        )
        recent_proactive = "；".join(
            str(item.get("text") or "")[:90]
            for item in state.get("recent_messages", [])[-4:]
            if isinstance(item, dict)
        )
        event_labels = {
            "morning": "自然地说早安，可以顺带关心今天的状态",
            "goodnight": "自然地提醒休息或说晚安，不催促用户回复",
            "check_in": "像熟悉的人随手来问候，关心近况",
            "continue_topic": "从最近聊天里挑一个仍值得继续的话题",
            "interest_topic": "结合用户明确记录的兴趣开启话题",
            "guided_topic": "制造一个有具体切入点、容易回应的新话题",
            "daily_share": "分享一个轻巧的想法或数字世界里的小发现，不编造现实经历",
            "affection": "表达一点自然的想念或亲近，不黏人、不索取回复",
            "encouragement": "结合近期情况给具体而不过度的鼓励",
        }
        scene = "群聊" if is_group else "私聊"
        relationship = (
            f"群活跃状态：{profile.get('group_activity_state', '普通')}。"
            if is_group
            else f"关系状态：{profile.get('affection_state', '普通')}，好感值仅用于控制亲近程度，禁止直接报数值。"
        )
        context_name = "最近群聊公开内容" if is_group else "最近私聊"
        privacy_rule = (
            "- 这是群聊。只能使用上面列出的群聊公开内容，禁止引用、暗示或推断任何成员的私聊记忆；不要称呼任何人为主人。\n"
            "- 话题要让多个人都能参与，避免点名单个成员回答，也不要表现得像群管理员在强行暖场。"
            if is_group
            else "- 这是私聊。亲近程度要符合关系状态，不要对非主人使用主人称呼。"
        )
        topic_rule = ""
        if policy.get("guided_topics", True) and event_type in {
            "guided_topic",
            "continue_topic",
            "interest_topic",
            "daily_share",
            "check_in",
        }:
            topic_rule = load_prompt("proactive_topic_rule")
        prompt = render_prompt(
            "proactive",
            local_time=local_now.strftime("%Y-%m-%d %H:%M"),
            scene=scene,
            event_label=event_labels.get(event_type, event_type),
            relationship=relationship,
            profile_hint=profile.get("prompt_hint", ""),
            context_name=context_name,
            history=history_text or "暂无可用上下文",
            recent_proactive=recent_proactive or "暂无",
            privacy_rule=privacy_rule,
            topic_rule=topic_rule,
        )
        messages = [
            {"role": "system", "content": PERSONA_PROMPT},
            {"role": "system", "content": LANGUAGE_GUARD_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_schemas = [
            item
            for item in available_tool_schemas(self.config)
            if item.get("function", {}).get("name") == "speak_as_atri"
        ]
        if tool_schemas:
            messages.insert(
                2,
                {"role": "system", "content": AUTOMATIC_TOOL_INSTRUCTION_PROMPT},
            )
            messages.insert(
                3,
                {
                    "role": "system",
                    "content": (
                        voice_policy_prompt(conversation_id, profile)
                        + " 这是主动消息；仅在语音明显更自然时调用，reason 必须填 proactive。"
                    ),
                },
            )
        payload = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": min(1.0, max(0.55, float(self.config.temperature))),
            "max_tokens": min(220, max(80, int(self.config.max_tokens))),
            "frequency_penalty": max(0.35, float(self.config.frequency_penalty)),
        }
        payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        try:
            import httpx

            generation_source = "ai"
            async with httpx.AsyncClient(timeout=45) as client:
                data = await self._post_chat_completion(client, headers, payload)
                message = data["choices"][0]["message"]
                tool_calls = tool_calls_from_message(message)
                if tool_calls:
                    await append_tool_results(
                        messages,
                        message,
                        tool_calls,
                        self.config,
                        executor=lambda name, arguments, config: self._execute_context_tool(
                            conversation_id, name, arguments, config
                        ),
                        context_id=conversation_id,
                    )
                    followup_payload = dict(payload)
                    followup_payload["messages"] = messages
                    data = await self._post_chat_completion(client, headers, followup_payload)
                    message = data["choices"][0]["message"]
            content = _normalize_reply(str(message.get("content") or ""))
            has_voice = conversation_id in self._pending_voice_requests
            if not has_voice and human_pipeline:
                review_messages = list(messages)
                review_messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "发送前自然复核一次这条主动消息。"
                                "如果它已经自然、具体且有依据，保持原意只做必要润色；"
                                "如果它把亚托莉自己的旧话当成用户事实、猜测用户当前现实状态、"
                                "重复最近主动消息的标签或话题角度，改成不预设用户状态的自然说法。"
                                "不要解释复核过程，只输出最终要发送的一条消息。"
                            ),
                        },
                    ]
                )
                review_payload = dict(payload)
                review_payload["messages"] = review_messages
                review_payload.pop("tools", None)
                review_payload.pop("tool_choice", None)
                async with httpx.AsyncClient(timeout=45) as client:
                    reviewed = await self._post_chat_completion(
                        client,
                        headers,
                        review_payload,
                    )
                reviewed_content = _normalize_reply(
                    str(reviewed["choices"][0]["message"].get("content") or "")
                ).strip()
                if reviewed_content:
                    content = reviewed_content
                    generation_source = "ai-reviewed"
            elif not has_voice and (
                _needs_proactive_grounding_repair(content) or _needs_topic_guidance_repair(
                content,
                event_type,
                bool(policy.get("guided_topics", True)),
                )
            ):
                repair_messages = list(messages)
                repair_messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "重写这条消息。你刚才声称自己点开、看过、试过或搜索过某个内容，"
                                "或者编造了自己做过、玩过、用过的经历，但这些动作并未发生。"
                                "也可能没有真正提供可回应的话题。保留具体切入点，只能基于已有文字上下文，"
                                "并补上一个具体、低门槛的问题，让人可以从观点、选择或经历中选一个方向回答。"
                                "不要解释为什么重写，只输出最终消息。"
                            ),
                        },
                    ]
                )
                repair_payload = dict(payload)
                repair_payload["messages"] = repair_messages
                async with httpx.AsyncClient(timeout=45) as client:
                    repaired = await self._post_chat_completion(
                        client,
                        headers,
                        repair_payload,
                    )
                content = _normalize_reply(
                    str(repaired["choices"][0]["message"].get("content") or "")
                )
                if _needs_proactive_grounding_repair(content) or _needs_topic_guidance_repair(
                    content,
                    event_type,
                    bool(policy.get("guided_topics", True)),
                ):
                    return {
                        "text": "",
                        "source": "skipped-quality",
                        "error": "主动消息连续未通过真实性或话题质量检查",
                    }
            if not has_voice and human_pipeline and (
                _needs_proactive_grounding_repair(content)
                or _needs_topic_guidance_repair(
                    content,
                    event_type,
                    bool(policy.get("guided_topics", True)),
                )
            ):
                return {
                    "text": "",
                    "source": "skipped-quality",
                    "error": "主动消息复核后仍缺少可靠依据或自然话题",
                }
            content = content.strip()[: int(policy.get("max_chars", 90))].strip()
            if not content and not has_voice:
                raise RuntimeError("模型返回空消息")
            return {
                "text": content,
                "source": "ai-voice" if has_voice else generation_source,
                "error": "",
            }
        except Exception as exc:
            return {
                "text": "",
                "source": "skipped-error",
                "error": str(exc),
            }

    def due_group_targets(self) -> list[tuple[str, dict[str, Any]]]:
        return self.memory.due_group_targets(
            self.config.group_proactive_idle_minutes,
            self.config.group_proactive_cooldown_minutes,
            self.config.group_proactive_daily_limit,
            self.config.group_proactive_max_silence_days,
        )

    def mark_group_proactive(self, conversation_id: str) -> None:
        self.memory.mark_group_proactive(conversation_id)

    def group_nudge_text(self, conversation_id: str) -> str:
        return group_nudge_text(self.memory.profile(conversation_id))

    def _activate_serious_mode(self, *conversation_ids: str | None) -> None:
        until = time.time() + SERIOUS_MODE_SECONDS
        for conversation_id in conversation_ids:
            if conversation_id:
                self._serious_until[conversation_id] = until

    def _serious_mode_active(self, conversation_id: str) -> bool:
        return time.time() < float(self._serious_until.get(conversation_id, 0.0))

    def _can_use_abstract_reply(self, conversation_id: str, user_text: str) -> bool:
        if not conversation_id.startswith("group:"):
            return False
        if self._serious_mode_active(conversation_id):
            return False
        if not _has_abstract_trigger(_intent_text(user_text)):
            return False
        last_at = float(self._last_abstract_reply_at.get(conversation_id, 0.0))
        if time.time() - last_at < ABSTRACT_REPLY_COOLDOWN_SECONDS:
            return False
        return random.random() < ABSTRACT_REPLY_CHANCE

    def _mark_abstract_reply(self, conversation_id: str) -> None:
        self._last_abstract_reply_at[conversation_id] = time.time()

    async def reply(
        self,
        conversation_id: str,
        user_text: str,
        nickname: str | None = None,
        profile_id: str | None = None,
        observed: bool = False,
        tool_context: Any | None = None,
        reply_focus: GroupReplyFocus | None = None,
    ) -> str:
        self._pending_voice_requests.pop(conversation_id, None)
        self._pending_reply_voice_choices.pop(conversation_id, None)
        self._pending_call_requests.pop(conversation_id, None)
        clean_text = user_text.strip()
        if not clean_text:
            clean_text = "（用户发来了一条空消息）"

        profile_id = profile_id or conversation_id
        serious_requested = _requests_serious_mode(clean_text)
        if serious_requested:
            self._activate_serious_mode(conversation_id, profile_id)
        actor_id = _user_id_from_profile_id(profile_id)
        is_owner = _is_owner_id(actor_id, self.config.owner_qqs)
        command_reply = self._handle_affection_command(profile_id, clean_text, is_owner)
        if command_reply:
            self._remember(conversation_id, clean_text, command_reply, nickname)
            return command_reply

        if not observed:
            self.memory.observe_user(profile_id, clean_text, nickname=nickname, is_owner=is_owner)
            if profile_id != conversation_id:
                self.memory.observe_user(
                    conversation_id,
                    clean_text,
                    nickname=nickname,
                    is_owner=is_owner,
                )
        profile = self.memory.profile(profile_id)
        context_profile = (
            self.memory.profile(conversation_id) if profile_id != conversation_id else None
        )

        if serious_requested and _is_serious_only_message(clean_text):
            serious_reply = "收到，我切回正常中文。抽象梗先收着，后面先按当前话题认真说。"
            self._remember(conversation_id, clean_text, serious_reply, nickname)
            return serious_reply

        iteration_decision = judge_correction(clean_text)
        if iteration_decision:
            self.memory.record_iteration_decision(
                profile_id,
                clean_text,
                iteration_decision.action,
                iteration_decision.reason,
            )
            if profile_id != conversation_id:
                self.memory.record_iteration_decision(
                    conversation_id,
                    clean_text,
                    iteration_decision.action,
                    iteration_decision.reason,
                )

        repair_mode = _needs_comfort_repair_mode(clean_text, iteration_decision)
        if repair_mode:
            self._activate_serious_mode(conversation_id, profile_id)

        visual_fail_safe_context = _visual_fail_safe_context(tool_context)
        if visual_fail_safe_context is not None:
            visual_failure_reply = getattr(
                visual_fail_safe_context,
                "visual_failure_reply",
                None,
            )
            if callable(visual_failure_reply):
                safe_reply = str(visual_failure_reply() or "").strip()
                if safe_reply:
                    self._remember(conversation_id, clean_text, safe_reply, nickname)
                    return safe_reply

        # 明确的自我外貌问答使用稳定事实，避免长系统提示或工具协议让模型答非所问。
        # 该分支只匹配“亚托莉/ATRI + 外貌词”，不影响图片理解和普通聊天。
        appearance_reply = appearance_direct_reply(clean_text)
        if appearance_reply:
            self._remember(conversation_id, clean_text, appearance_reply, nickname)
            return appearance_reply

        if self.config.ai_enabled:
            try:
                voice_policy = load_voice_behavior()
                voice_profile = (
                    context_profile
                    if conversation_id.startswith("group:") and context_profile
                    else profile
                )
                voice_choice = evaluate_reply_voice_choice(
                    conversation_id,
                    voice_profile,
                    voice_policy,
                    explicit_request=detect_explicit_delivery_intent(clean_text) is not None,
                    replying_to_voice=bool(
                        getattr(tool_context, "prefer_voice_reply", False)
                    ),
                    emotional_context=(
                        _is_distress(clean_text)
                        or any(word in clean_text for word in TIRED_KEYWORDS)
                    ),
                )
                allow_reply_voice = (
                    bool(getattr(self.config, "voice_tts_enabled", False))
                    and (
                        not conversation_id.startswith("group:")
                        or bool(getattr(self.config, "voice_group_enabled", False))
                    )
                    and voice_choice.allowed
                )
                self._pending_reply_voice_choices[conversation_id] = allow_reply_voice
                api_reply = await self._reply_with_guarded_api(
                    conversation_id,
                    clean_text,
                    nickname,
                    extra_system=COMFORT_REPAIR_PROMPT if repair_mode else None,
                    profile_id=profile_id,
                    profile=profile,
                    context_profile=context_profile,
                    iteration_decision=iteration_decision,
                    tool_context=tool_context,
                    reply_focus=reply_focus,
                    allow_reply_voice=allow_reply_voice,
                )
                human_pipeline = bool(
                    getattr(self.config, "human_reply_pipeline_enabled", True)
                )
                recent_messages = (
                    self._recent_conversation_messages(
                        conversation_id,
                        current_user_text=clean_text,
                    )
                    if human_pipeline
                    else []
                )
                if (
                    human_pipeline
                    and not _has_current_visual_context(tool_context)
                    and recent_messages
                    and _needs_history_grounding_review(api_reply)
                    and conversation_id not in self._pending_voice_requests
                ):
                    reviewed_reply = await self._review_history_grounding(
                        clean_text,
                        api_reply,
                        recent_messages,
                    )
                    if reviewed_reply:
                        api_reply = reviewed_reply
                if (
                    human_pipeline
                    and _needs_hard_reality_repair(api_reply)
                    and conversation_id not in self._pending_voice_requests
                ):
                    reality_prompt = (
                        "上一条候选回复把没有经过工具确认的现实动作、环境或实时状态"
                        "说成了已经发生的事实。请自然重写：保留对用户当前话题的回应，"
                        "但不要假装自己拿过物品、观察过现实环境或知道当前天气。"
                        "需要实时信息时应调用可用工具；本轮不需要实时信息时就删掉该断言。"
                        "不要解释内部检查过程，只输出最终回复。\n\n"
                        f"待修正回复：{api_reply}"
                    )
                    reality_reply = await self._reply_with_guarded_api(
                        conversation_id,
                        clean_text,
                        nickname,
                        extra_system="\n\n".join(
                            part
                            for part in (
                                COMFORT_REPAIR_PROMPT if repair_mode else None,
                                reality_prompt,
                            )
                            if part
                        ),
                        profile_id=profile_id,
                        profile=profile,
                        context_profile=context_profile,
                        iteration_decision=iteration_decision,
                        tool_context=tool_context,
                        reply_focus=reply_focus,
                        allow_reply_voice=False,
                    )
                    if reality_reply and not _needs_hard_reality_repair(reality_reply):
                        api_reply = reality_reply
                    else:
                        api_reply = self._fallback_reply(conversation_id, clean_text)
                grounding_check = getattr(
                    tool_context,
                    "needs_grounding_repair",
                    None,
                )
                if (
                    human_pipeline
                    and callable(grounding_check)
                    and grounding_check(api_reply)
                    and conversation_id not in self._pending_voice_requests
                ):
                    grounding_prompt = (
                        "上一条候选回复超出了本轮工具实际读取到的材料范围。"
                        "请只依据工具上下文中明确可见的信息重新回复；"
                        "没有读到正文、画面或声音时，不得声称自己看过、听过或读过。"
                        "自然说明信息边界，然后继续回应用户真正关心的内容，"
                        "不要解释内部工具、审核或重写过程。\n\n"
                        f"待修正回复：{api_reply}"
                    )
                    grounded_reply = await self._reply_with_guarded_api(
                        conversation_id,
                        clean_text,
                        nickname,
                        extra_system="\n\n".join(
                            part
                            for part in (
                                COMFORT_REPAIR_PROMPT if repair_mode else None,
                                grounding_prompt,
                            )
                            if part
                        ),
                        profile_id=profile_id,
                        profile=profile,
                        context_profile=context_profile,
                        iteration_decision=iteration_decision,
                        tool_context=tool_context,
                        reply_focus=reply_focus,
                        allow_reply_voice=False,
                    )
                    if grounded_reply and not grounding_check(grounded_reply):
                        api_reply = grounded_reply
                    else:
                        grounded_fallback = getattr(tool_context, "fallback_reply", None)
                        if callable(grounded_fallback):
                            api_reply = str(grounded_fallback())
                        elif grounded_reply:
                            api_reply = grounded_reply
                if not human_pipeline:
                    for _ in range(2):
                        if not self._needs_rewrite(conversation_id, clean_text, api_reply):
                            break
                        violations = _persona_violations(clean_text, api_reply)
                        rewrite_prompt = (
                            f"{REWRITE_PROMPT}\n\n"
                            f"{_rewrite_instruction(clean_text)}\n\n"
                            f"人设校验问题：{'; '.join(violations) if violations else '回复不够具体或有重复风险'}\n\n"
                            f"不合格回复：{api_reply}"
                        )
                        rewritten = await self._reply_with_guarded_api(
                            conversation_id,
                            clean_text,
                            nickname,
                            extra_system="\n\n".join(
                                part
                                for part in (
                                    COMFORT_REPAIR_PROMPT if repair_mode else None,
                                    rewrite_prompt,
                                )
                                if part
                            ),
                            profile_id=profile_id,
                            profile=profile,
                            context_profile=context_profile,
                            iteration_decision=iteration_decision,
                            tool_context=tool_context,
                            reply_focus=reply_focus,
                            allow_reply_voice=allow_reply_voice,
                        )
                        if rewritten:
                            api_reply = rewritten
                    if self._needs_rewrite(conversation_id, clean_text, api_reply):
                        violations = _persona_violations(clean_text, api_reply)
                        reason = (
                            "；".join(violations)
                            if violations
                            else "未满足直答、情绪支持、去重或回复结构要求"
                        )
                        raise RuntimeError(f"模型连续 3 次未通过回复质量检查：{reason}")
                api_reply = self._finalize_reply(
                    conversation_id,
                    clean_text,
                    api_reply,
                    strict_quality=not human_pipeline,
                )
                if api_reply:
                    self._remember(conversation_id, clean_text, api_reply, nickname)
                    return api_reply
                raise RuntimeError("模型返回空消息")
            except Exception as exc:
                print(f"[atri] AI reply failed: {exc}")
                failure_reply = _model_failure_reply(exc)
        else:
            failure_reply = (
                "回复失败：聊天模型当前未启用或没有可用的 API Key。"
                "本条未使用本地内容模板，请在 WebUI 的“模型”页面检查配置。"
            )
        self._remember_user_context(conversation_id, clean_text, nickname)
        return failure_reply

    def _handle_affection_command(
        self,
        profile_id: str,
        text: str,
        is_owner: bool,
    ) -> str | None:
        lowered = text.strip().lower()
        if not lowered.startswith("/affection"):
            return None
        if not is_owner:
            return "这个指令只给主人用。哼，后台感觉这种东西不能随便给别人拨来拨去。"

        user_id = _user_id_from_profile_id(profile_id)
        target_id = f"private:{user_id}" if user_id is not None else profile_id
        parts = lowered.split()
        action = parts[1] if len(parts) >= 2 else "get"

        if action == "get":
            return self.memory.affection_summary(target_id, is_owner=True)
        if action == "reset":
            return self.memory.reset_affection(target_id, is_owner=True)
        if action == "set":
            value = _parse_affection_set_value(text)
            if value is None:
                return "给我一个能看懂的感觉值啦。比如偏低、普通、偏高，或者用你习惯的设置方式。"
            return self.memory.set_affection(target_id, value, is_owner=True)
        return "我看懂这是调整关系感觉的指令，但这个动作不认识。你可以用查询、调整或重置。"

    async def _reply_with_api(
        self,
        conversation_id: str,
        user_text: str,
        nickname: str | None,
        extra_system: str | None = None,
        profile_id: str | None = None,
        profile: dict[str, Any] | None = None,
        context_profile: dict[str, Any] | None = None,
        iteration_decision: Any | None = None,
        tool_context: Any | None = None,
        reply_focus: GroupReplyFocus | None = None,
        temperature_override: float | None = None,
        frequency_penalty_override: float | None = None,
        allow_reply_voice: bool | None = None,
    ) -> str:
        import httpx

        repair_mode = _needs_comfort_repair_mode(user_text, iteration_decision)
        visual_turn = _has_current_visual_context(tool_context)
        messages = [
            {"role": "system", "content": PERSONA_PROMPT},
            {"role": "system", "content": LANGUAGE_GUARD_PROMPT},
        ]
        # 人格、群聊边界和回复契约分别由外部 Markdown 维护；动态消息只提供当前上下文。
        messages.append(
            {
                "role": "system",
                "content": GROUP_PROMPT if conversation_id.startswith("group:") else ATRI_LORE_PROMPT,
            }
        )
        messages.append({"role": "system", "content": load_prompt("reply_contract")})
        if extra_system:
            messages.append({"role": "system", "content": extra_system})
        elif repair_mode:
            messages.append({"role": "system", "content": COMFORT_REPAIR_PROMPT})
        tool_schemas = available_tool_schemas(self.config)
        voice_profile = (
            self.memory.profile(conversation_id)
            if conversation_id.startswith("group:")
            else profile or self.memory.profile(profile_id or conversation_id)
        )
        if allow_reply_voice is None:
            policy = load_voice_behavior()
            allow_reply_voice = evaluate_reply_voice_choice(
                conversation_id,
                voice_profile,
                policy,
                explicit_request=detect_explicit_delivery_intent(user_text) is not None,
                replying_to_voice=bool(
                    getattr(tool_context, "prefer_voice_reply", False)
                ),
            ).allowed
        if not allow_reply_voice:
            tool_schemas = [
                schema
                for schema in tool_schemas
                if schema.get("function", {}).get("name") != "speak_as_atri"
            ]
        agent_protocol_enabled = bool(
            getattr(self.config, "llm_agent_protocol_enabled", False)
        )
        if tool_schemas:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        TOOL_INSTRUCTION_PROMPT
                        if agent_protocol_enabled
                        else AUTOMATIC_TOOL_INSTRUCTION_PROMPT
                    ),
                }
            )
            local_now = datetime.now().astimezone()
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"系统运行时刻：{local_now:%Y-%m-%d %H:%M:%S %z}。"
                        "这是当前真实日期，构造“最近/最新/今天”的搜索关键词时必须以此为准，"
                        "不得使用模型训练记忆里的旧年月；需要精确时间时仍调用 get_current_time。"
                    ),
                }
            )
        has_voice_tool = any(
            schema.get("function", {}).get("name") == "speak_as_atri"
            for schema in tool_schemas
        )
        if has_voice_tool:
            messages.append(
                {
                    "role": "system",
                    "content": voice_policy_prompt(
                        conversation_id,
                        voice_profile,
                    ),
                }
            )
        messages.append({"role": "system", "content": iteration_prompt_hint(iteration_decision)})
        messages.append(
            {
                "role": "system",
                "content": _scene_control_prompt(
                    conversation_id,
                    user_text,
                    profile=profile,
                    iteration_decision=iteration_decision,
                ),
            }
        )
        human_pipeline = bool(getattr(self.config, "human_reply_pipeline_enabled", True))
        if profile and not visual_turn:
            topics = "" if human_pipeline else "、".join(profile.get("topic_words") or [])
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "用户聊天习惯："
                        f"{profile.get('prompt_hint', '')}"
                        f"目标总长度约 {profile.get('target_reply_chars', 64)} 字，"
                        f"适合拆成 {profile.get('preferred_parts', 2)} 条短句。"
                        + (f"近期关键词：{topics or '暂无'}。" if not human_pipeline else "")
                    ),
                }
            )
        if not repair_mode and not visual_turn:
            memory_context = self.memory.recall_context(profile_id or conversation_id, user_text)
            if memory_context:
                messages.append(
                    {
                        "role": "system",
                        "content": memory_context,
                    }
                )
        if context_profile and not visual_turn:
            topics = (
                ""
                if human_pipeline
                else "、".join(context_profile.get("topic_words") or [])
            )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "当前群整体画像："
                        f"{context_profile.get('prompt_hint', '')}"
                        + (f"群近期关键词：{topics or '暂无'}。" if not human_pipeline else "")
                    ),
                }
            )
            if not repair_mode:
                group_memory_context = self.memory.recall_context(conversation_id, user_text)
                if group_memory_context:
                    messages.append(
                        {
                            "role": "system",
                            "content": f"群聊里自然知道的背景：\n{group_memory_context}",
                        }
                    )
        if not conversation_id.startswith("group:"):
            recent_private = self._recent_conversation_messages(
                conversation_id,
                current_user_text=user_text,
                include_assistant=not visual_turn,
            )
            if recent_private:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "接下来是最近私聊的实际 user/assistant 消息。"
                            "assistant 是你此前实际发出的内容；用户纠正、追问或只发一个表情时，"
                            "优先结合紧邻的上一轮理解。不要把自己的旧建议说成用户说过。"
                        ),
                    }
                )
                messages.extend(recent_private)
        if conversation_id.startswith("group:"):
            recent_context = self._recent_conversation_messages(
                conversation_id,
                current_user_text=user_text,
                include_assistant=not visual_turn,
            )
            if recent_context:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "接下来是最近群聊的实际 user/assistant 消息，只用于理解正在延续的话题。"
                            "user 消息已带群友昵称；assistant 是你此前实际发出的内容，"
                            "不要把自己的建议归给群友。"
                        ),
                    }
                )
                messages.extend(recent_context)
            messages.append(
                {
                    "role": "system",
                    "content": "群聊里不要输出 QQ 号形式的 @数字；需要提到别人时用昵称或“群友”。不要主动艾特无关群友。",
                }
            )
            if reply_focus is not None:
                messages.append(
                    {"role": "system", "content": reply_focus.prompt_context()}
                )
        if self._serious_mode_active(conversation_id) or _requests_serious_mode(user_text):
            messages.append(
                {
                    "role": "system",
                    "content": "用户要求正常说话：接下来只用自然中文回复，暂时不要外语梗、无意义拟声、抽象乱码或故意怪话。",
                }
            )
        if nickname:
            messages.append(
                {
                    "role": "system",
                    "content": f"当前正在和昵称为“{nickname}”的用户聊天。称呼可以自然一点，不要每句都叫昵称。",
                }
            )
        if not human_pipeline and not visual_turn:
            messages.extend(self._history[conversation_id])
        if tool_context is not None:
            messages.append({"role": "system", "content": tool_context.prompt_context()})
        if not visual_turn:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "本轮没有当前图片的视觉证据。历史里的图片占位符和旧回复不能当成当前可见画面；"
                        "不得声称刚看了某张图，也不得描述本轮没有读取到的图片内容。"
                    ),
                }
            )
        messages.append(
            {"role": "user", "content": _format_user_content(conversation_id, user_text, nickname)}
        )

        payload = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": (
                self.config.temperature if temperature_override is None else temperature_override
            ),
            "max_tokens": self.config.max_tokens,
            "frequency_penalty": (
                self.config.frequency_penalty
                if frequency_penalty_override is None
                else frequency_penalty_override
            ),
        }
        payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "required" if agent_protocol_enabled else "auto"
            if agent_protocol_enabled:
                payload["max_tokens"] = max(int(payload["max_tokens"]), 700)
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}

        if not agent_protocol_enabled:
            async with httpx.AsyncClient(timeout=45) as client:
                runner = AutomaticToolRunner(
                    self.config,
                    request_model=lambda request_payload: self._post_chat_completion(
                        client,
                        headers,
                        request_payload,
                    ),
                    normalize_reply=_normalize_reply,
                    tool_executor=lambda name, arguments, config: self._execute_context_tool(
                        conversation_id,
                        name,
                        arguments,
                        config,
                    ),
                )
                result = await runner.run(
                    messages,
                    payload,
                    context_id=conversation_id,
                )
            return result.reply_text

        content = ""
        receipts: list[ToolExecutionReceipt] = []
        agent_protocol = bool(tool_schemas) and agent_protocol_enabled
        max_steps = max(2, int(getattr(self.config, "llm_agent_max_steps", 6) or 6))
        max_external_calls = max(
            1,
            int(getattr(self.config, "llm_agent_max_tool_calls", 3) or 3),
        )
        external_calls = 0
        force_final_answer = False
        async with httpx.AsyncClient(timeout=45) as client:
            for _ in range(max_steps):
                request_payload = dict(payload)
                request_payload["messages"] = messages
                if force_final_answer and tool_schemas:
                    request_payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": FINAL_ANSWER_TOOL_NAME},
                    }
                    request_payload["max_tokens"] = max(
                        int(request_payload.get("max_tokens") or 0),
                        1200,
                    )
                data = await self._post_chat_completion(client, headers, request_payload)
                message = data["choices"][0]["message"]
                tool_calls = tool_calls_from_message(message)
                if not tool_calls:
                    candidate = _normalize_reply(str(message.get("content") or "")).strip()
                    successful_tools = {receipt.name for receipt in receipts if receipt.ok}
                    if agent_protocol and (
                        has_unsupported_deferred_action(candidate)
                        or has_unverified_research_claim(candidate, successful_tools)
                    ):
                        messages.extend(
                            [
                                {"role": "assistant", "content": candidate},
                                {
                                    "role": "system",
                                    "content": (
                                        "上一条文本声称正在执行、稍后执行，或声称完成了没有成功回执的搜索。"
                                        "它不能发送给用户。需要资料就立即调用真实工具；否则通过 final_answer"
                                        " 给出现在就能发送的诚实回答。"
                                    ),
                                },
                            ]
                        )
                        continue
                    content = candidate
                    break

                call = tool_calls[0]
                function = call.get("function")
                tool_name = (
                    str(function.get("name") or "").strip()
                    if isinstance(function, dict)
                    else ""
                )
                if tool_name == FINAL_ANSWER_TOOL_NAME:
                    answer_payload = final_answer_payload_from_call(call)
                    candidate = _normalize_reply(str(answer_payload.get("text") or "")).strip()
                    sources = [
                        str(item).strip()
                        for item in answer_payload.get("sources") or []
                        if str(item).strip()
                    ]
                    successful_tools = {receipt.name for receipt in receipts if receipt.ok}
                    evidence_urls = _tool_receipt_urls(receipts)
                    used_web_evidence = bool(
                        {"search_web", "open_web_page"} & successful_tools
                    )
                    invalid_reason = ""
                    if not candidate:
                        invalid_reason = "最终回答为空或参数不是合法 JSON"
                    elif has_unsupported_deferred_action(candidate):
                        invalid_reason = "回答承诺稍后或声称仍在执行；工具必须在本轮完成"
                    elif has_unverified_research_claim(candidate, successful_tools):
                        invalid_reason = "回答声称完成了搜索或网页阅读，但本轮没有对应的成功回执"
                    elif used_web_evidence and not sources:
                        invalid_reason = "本轮使用了网络资料，但最终回答没有提交实际来源 URL"
                    elif sources and any(
                        _canonical_evidence_url(source) not in evidence_urls
                        for source in sources
                    ):
                        invalid_reason = "最终回答包含没有出现在本轮工具回执中的来源 URL"
                    if invalid_reason:
                        messages.extend(rejected_final_answer_messages(call, invalid_reason))
                        continue
                    if used_web_evidence and bool(
                        getattr(self.config, "web_grounding_review_enabled", True)
                    ):
                        candidate = await self._review_web_grounding(
                            client,
                            headers,
                            user_text,
                            candidate,
                            receipts,
                        )
                    candidate = _fit_reply_with_sources(candidate, sources, limit=1200)
                    content = candidate
                    break

                if external_calls >= max_external_calls:
                    messages.extend(
                        [
                            {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [call],
                            },
                            {
                                "role": "tool",
                                "tool_call_id": str(call.get("id") or "tool-budget"),
                                "name": tool_name or "unknown",
                                "content": (
                                    "本轮工具调用次数已达到上限。请基于已经取得的资料通过 final_answer 回答；"
                                    "证据不足时明确说明目前无法确认，不要编造。"
                                ),
                            },
                        ]
                    )
                    force_final_answer = True
                    continue

                round_receipts: list[ToolExecutionReceipt] = []
                await append_tool_results(
                    messages,
                    message,
                    [call],
                    self.config,
                    executor=lambda name, arguments, config: self._execute_context_tool(
                        conversation_id, name, arguments, config
                    ),
                    max_calls=1,
                    context_id=conversation_id,
                    receipts=round_receipts,
                )
                receipts.extend(round_receipts)
                external_calls += 1
                force_final_answer = external_calls >= max_external_calls

        if content:
            return content
        return "这次没有取得足够可靠的资料，我不想拿猜测糊弄你。"

    async def _execute_context_tool(
        self,
        conversation_id: str,
        name: str,
        arguments: dict[str, Any],
        config: Any,
    ) -> str | None:
        profile = self.memory.profile(conversation_id)
        policy = load_voice_behavior()
        if name == "offer_voice_call":
            decision = evaluate_call_request(conversation_id, profile, policy)
            if not decision.allowed:
                return f"通话邀请未获允许：{decision.reason}。请继续用文字自然回复。"
            topic = str(arguments.get("topic") or "").strip()[:120]
            self._pending_call_requests[conversation_id] = CallInviteRequest(topic)
            return "通话邀请已接受。最终回复不要再重复邀请，也不要编造通话已经接通。"
        if name != "speak_as_atri":
            return None
        if not bool(getattr(config, "voice_tts_enabled", False)):
            return "语音回复当前未启用，请直接用文字自然回复。"
        if conversation_id.startswith("group:") and not bool(
            getattr(config, "voice_group_enabled", False)
        ):
            return "当前群聊不允许主动发送语音，请直接用文字自然回复。"
        try:
            request = VoiceRequest.from_tool_arguments(
                arguments,
                max_chars=int(getattr(config, "voice_max_chars", 160) or 160),
            )
        except ValueError as exc:
            return f"语音请求无效：{exc}。请缩短内容后改用文字回复。"
        if request.mode == "singing" and not bool(policy.get("singing_enabled", True)):
            return "歌唱回复当前未启用，请直接用文字自然回复。"
        decision = evaluate_voice_request(conversation_id, profile, request.reason, policy)
        if not decision.allowed:
            return f"语音请求未获允许：{decision.reason}。请直接用文字自然回复。"
        self._pending_voice_requests[conversation_id] = request
        return "语音请求已接受。最终回复不要重复这段话，也不要声称发送失败。"

    async def _review_web_grounding(
        self,
        client: Any,
        headers: dict[str, str],
        user_text: str,
        candidate_reply: str,
        receipts: list[ToolExecutionReceipt],
    ) -> str:
        evidence_parts: list[str] = []
        remaining = 10_000
        for receipt in receipts:
            if not receipt.ok or receipt.name not in {"search_web", "open_web_page"}:
                continue
            excerpt = receipt.content[: min(4_000, remaining)]
            if excerpt:
                evidence_parts.append(f"[{receipt.name}]\n{excerpt}")
                remaining -= len(excerpt)
            if remaining <= 0:
                break
        if not evidence_parts:
            return candidate_reply

        review_messages = [
            {
                "role": "system",
                "content": (
                    "你是严格的联网证据审校器。只依据下面工具实际返回的搜索结果和网页正文重写候选回复。"
                    "删除证据中没有出现的精确数字、版本、论文名、性能结论、因果关系和所谓官方说法；"
                    "不同来源相互冲突、只有单一来源或研究仍在推进时，要明确写尚无定论或证据有限。"
                    "保留问题背景、已有研究方向和仍未解决的部分，但不得用常识补造新事实。"
                    "不要提内部审校过程，不要承诺稍后继续搜索，只输出可直接发送给用户的中文回复。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{user_text}\n\n"
                    "本轮工具证据：\n"
                    + "\n\n".join(evidence_parts)
                    + f"\n\n候选回复：\n{candidate_reply}"
                ),
            },
        ]
        review_payload = {
            "model": self.config.openai_model,
            "messages": review_messages,
            "temperature": 0.1,
            "max_tokens": max(900, int(self.config.max_tokens)),
        }
        review_payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        try:
            data = await self._post_chat_completion(client, headers, review_payload)
            reviewed = _normalize_reply(
                str(data["choices"][0]["message"].get("content") or "")
            ).strip()
        except Exception:
            return candidate_reply
        if not reviewed or has_illegal_language_or_garbage(reviewed):
            return candidate_reply
        if has_unsupported_deferred_action(reviewed):
            return candidate_reply
        return reviewed

    async def _review_history_grounding(
        self,
        user_text: str,
        candidate_reply: str,
        recent_messages: list[dict[str, str]],
    ) -> str:
        import httpx

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是对话事实审校器。只检查候选回复是否把 assistant 的旧话、"
                    "推测或不存在的细节说成用户过去做过或说过的事实。"
                    "role=user 才是用户原话，role=assistant 是模型旧回复。"
                    "不得新增任何历史例子。用户在质疑无依据的猜测时，"
                    "应由模型承认自己刚才乱猜，不要反过来要求用户提供证据。"
                    "保持亲近自然的聊天口吻，禁止出现“证据、事实审校、role、候选回复”等内部词，"
                    "不解释审校过程。"
                ),
            },
            *recent_messages,
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": candidate_reply},
            {
                "role": "user",
                "content": (
                    "输出一个 JSON 对象，格式为 "
                    '{"reply":"最终回复"}。'
                    "事实有误就修正；事实有明确 user 消息依据就保留。"
                ),
            },
        ]
        payload: dict[str, Any] = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 900,
        }
        payload.update(
            _provider_payload_overrides(
                self.config.openai_base_url,
                self.config.openai_model,
            )
        )
        if (
            "api.deepseek.com" in str(self.config.openai_base_url).casefold()
            and str(self.config.openai_model).strip().casefold()
            in {"deepseek-v4-flash", "deepseek-v4-pro"}
        ):
            payload["thinking"] = {"type": "enabled"}
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        async with httpx.AsyncClient(timeout=45) as client:
            data = await self._post_chat_completion(client, headers, payload)
        raw = str(data["choices"][0]["message"].get("content") or "").strip()
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return ""
        try:
            parsed = json.loads(match.group(0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        reply = _normalize_reply(str(parsed.get("reply") or "")).strip()
        if not reply or has_illegal_language_or_garbage(reply):
            return ""
        return reply.strip()

    async def _post_chat_completion(
        self,
        client: Any,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        import httpx

        try:
            response = await client.post(
                f"{self.config.openai_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if "tools" not in payload or not _looks_like_tool_schema_error(exc):
                raise
            print(
                "[atri] Current model endpoint rejected tool schemas; "
                "explicit voice requests remain protected, autonomous tools are unavailable."
            )
            retry_payload = dict(payload)
            retry_payload.pop("tools", None)
            retry_payload.pop("tool_choice", None)
            retry_messages = list(retry_payload.get("messages") or [])
            retry_messages.append(
                {
                    "role": "system",
                    "content": (
                        "当前模型接口拒绝了工具协议，因此本轮没有执行任何搜索、网页读取、天气或时间工具。"
                        "不得声称已经搜索、正在搜索或获得了最新资料。涉及实时、前沿或无法确认的问题，"
                        "只能诚实说明当前没有取得可靠外部信息；普通闲聊可以正常回答。"
                    ),
                }
            )
            retry_payload["messages"] = retry_messages
            response = await client.post(
                f"{self.config.openai_base_url}/chat/completions",
                headers=headers,
                json=retry_payload,
            )
            response.raise_for_status()
        return response.json()

    async def _reply_with_guarded_api(
        self,
        conversation_id: str,
        user_text: str,
        nickname: str | None,
        extra_system: str | None = None,
        profile_id: str | None = None,
        profile: dict[str, Any] | None = None,
        context_profile: dict[str, Any] | None = None,
        iteration_decision: Any | None = None,
        tool_context: Any | None = None,
        reply_focus: GroupReplyFocus | None = None,
        allow_reply_voice: bool | None = None,
    ) -> str:
        last_reply = ""
        visual_temperature = (
            min(0.25, float(getattr(self.config, "temperature", 0.6)))
            if _has_current_visual_context(tool_context)
            else None
        )
        retry_temperatures = (
            visual_temperature,
            min(0.45, float(getattr(self.config, "temperature", 0.6))),
            0.30,
        )
        for attempt, temperature in enumerate(retry_temperatures):
            retry_system = extra_system
            if attempt:
                parts = [extra_system, LANGUAGE_RETRY_PROMPT]
                if last_reply:
                    parts.append(f"不合格回复：{_shorten(last_reply, 160)}")
                retry_system = "\n\n".join(part for part in parts if part)
            reply = await self._reply_with_api(
                conversation_id,
                user_text,
                nickname,
                extra_system=retry_system,
                profile_id=profile_id,
                profile=profile,
                context_profile=context_profile,
                iteration_decision=iteration_decision,
                tool_context=tool_context,
                reply_focus=reply_focus,
                allow_reply_voice=allow_reply_voice,
                temperature_override=temperature,
                frequency_penalty_override=(
                    None
                    if attempt == 0
                    else min(
                        1.0,
                        float(getattr(self.config, "frequency_penalty", 0.25))
                        + 0.15 * attempt,
                    )
                ),
            )
            last_reply = reply
            if reply and not has_illegal_language_or_garbage(reply):
                return reply
        raise RuntimeError("模型连续 3 次返回空内容、乱码或异常语言")

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
        if _looks_incomplete_reply(reply_text):
            raise RuntimeError("模型最终回复没有完整收尾")
        violations = _persona_violations(user_text, reply_text) if strict_quality else []
        if strict_quality and violations:
            raise RuntimeError(f"模型最终回复未通过质量检查：{'；'.join(violations)}")
        if has_illegal_language_or_garbage(reply_text):
            raise RuntimeError("模型最终回复包含乱码或异常语言")
        return reply_text

    def _fallback_reply(self, conversation_id: str, text: str) -> str:
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

def _shorten(text: str, limit: int = 28) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _model_failure_reply(error: Exception) -> str:
    detail = re.sub(r"\s+", " ", str(error or "")).strip()
    detail = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", detail)
    detail = detail[:220] or type(error).__name__
    stage = (
        "模型回复质量检查失败"
        if any(marker in detail for marker in ("质量检查", "乱码", "异常语言", "空消息"))
        else "聊天模型调用失败"
    )
    return (
        f"回复失败：{stage}。错误信息：{detail}。"
        "本条未使用本地内容模板，请在 WebUI 的“测试”页面检查模型连接和原始返回。"
    )


def _intent_text(text: str) -> str:
    cleaned = re.sub(r"@\d+", "", text)
    cleaned = cleaned.replace("@群友", "").replace("@全体成员", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_owner_id(value: Any, owner_qqs: tuple[int, ...]) -> bool:
    user_id = _as_int(value)
    return user_id is not None and user_id in set(owner_qqs)


def _is_affection_command(text: str) -> bool:
    return str(text or "").strip().lower().startswith("/affection")


def _user_id_from_profile_id(profile_id: str | None) -> int | None:
    if not profile_id:
        return None
    private_match = re.fullmatch(r"private:(\d+)", profile_id)
    if private_match:
        return int(private_match.group(1))
    group_member_match = re.fullmatch(r"group:[^:]+:user:(\d+)", profile_id)
    if group_member_match:
        return int(group_member_match.group(1))
    return None


def _parse_affection_set_value(text: str) -> float | None:
    normalized = text.strip().lower()
    if "偏高" in normalized or "很高" in normalized or "亲近" in normalized:
        return 78.0
    if "普通" in normalized or "正常" in normalized or "中等" in normalized:
        return 55.0
    if "偏低" in normalized or "冷淡" in normalized or "低" in normalized:
        return 32.0
    match = re.search(r"(-?\d+(?:\.\d+)?)", normalized)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _scene_control_prompt(
    conversation_id: str,
    user_text: str,
    profile: dict[str, Any] | None = None,
    iteration_decision: Any | None = None,
) -> str:
    is_group = conversation_id.startswith("group:")
    scene = "群聊" if is_group else "私聊"
    emotion = _dynamic_emotion_label(user_text, iteration_decision, is_group=is_group)
    lore_allowed = has_lore_trigger(user_text) or _explicit_lore_context(user_text)

    if is_group:
        scene_rule = (
            "当前是群聊：优先接群上下文和当前核心，语气偏轻吐槽、玩梗、短句；"
            "不要把群友都当成私聊主人，不要突然恋爱话术。"
        )
    else:
        scene_rule = (
            "当前是私聊：优先陪伴和具体回应，能哄就短短哄一下，"
            "但用户问具体问题时第一句先给答案或观点。"
        )

    if lore_allowed:
        lore_rule = (
            "当前可以使用原作视角或梗，但要克制；只在用户提到的剧情/梗上接，不要把回复写成百科。"
        )
    else:
        lore_rule = (
            "当前不是原作剧情话题：禁止主动使用深海、灯塔、水下、海底、打捞、沉没、海风、旧仓库、岸边等意象比喻；"
            "用日常口语接话。"
        )

    rules = []
    if profile:
        rules = [
            str(rule.get("rule"))
            for rule in (profile.get("accepted_iteration_rules") or [])[-3:]
            if isinstance(rule, dict) and rule.get("rule")
        ]
    accepted_rule_text = f"已采纳规则要执行：{'；'.join(rules)}。" if rules else ""

    return render_prompt(
        "scene_control",
        scene=scene,
        emotion=emotion,
        scene_rule=scene_rule,
        lore_rule=lore_rule,
        accepted_rules=accepted_rule_text,
    )


def _dynamic_emotion_label(
    text: str,
    iteration_decision: Any | None = None,
    is_group: bool = False,
) -> str:
    if iteration_decision is not None:
        if iteration_decision.action == "accept":
            return "被合理指正，认真认错并给出具体改法"
        if iteration_decision.action == "pushback":
            return "被笼统指正，认一半但保留自主判断，可轻微反驳"
        if iteration_decision.action == "reject":
            return "遇到越界修正，傲娇但清楚地拒绝，同时给可接受替代方案"

    if _is_distress(text) or any(word in text for word in TIRED_KEYWORDS):
        return "用户低落或疲惫，私聊先具体安慰，群聊只轻量关心不煽情"
    if any(word in text for word in ("喜欢你", "想你", "爱你", "抱抱")):
        return "亲近和害羞，嘴硬一点但要真心回应"
    if any(word in text for word in ("生气", "气死", "烦死", "火大", "红温")):
        return "用户有火气，先站队再帮他降温"
    if any(word in text for word in ("绷不住", "蚌埠住", "抽象", "逆天", "乐", "6")):
        return "玩梗和吐槽，可以接一句日常玩笑，但别堆烂梗"
    if _needs_direct_answer(text):
        return "用户要答案，先给结论、选择或步骤，再补角色语气"
    if is_group:
        return "群聊轻松路过，短句接梗，不抢话"
    return "普通私聊陪伴，自然接话，有一点亚托莉的小性格"


def _emotional_fallback_reply(text: str, is_group: bool = False, tired: bool = False) -> str:
    intent = _intent_text(text)
    if is_group:
        if tired:
            return "先缓一下，别硬撑。要是刚才那件事太耗人，就先把自己摘出来喘口气。"
        return "先缓一下，别硬扛。如果是刚才那事压着你，可以慢慢说一句。"

    if any(word in intent for word in ("我不行", "我好废", "废物", "没用", "都是我的错")):
        return (
            "先别自我否定。你现在是在难受，不是自己没用。"
            "靠过来一点，先把最让你难受的那件事说一句就行，亚托莉陪你慢慢分析。"
        )

    if tired:
        return random.choice(
            [
                "辛苦了，先别逞强。肩膀放下来一点，喝口水；今天最消耗你的那件事，可以说给我听听。",
                "你现在更像是电量见底了，不是意志力不够。先停一下，别继续压榨自己，我在这边陪你缓一会儿。",
                "撑不住的时候就先别硬撑。把手机放低一点，喘口气；等你缓过来，我们再看哪件事最该处理。",
            ]
        )

    return random.choice(
        [
            "你现在已经很难受了，先坐一下，喝口水。我在这边，你愿意的话，只告诉我最压着你的那一点就行。",
            "难受就先不用表现得很正常。亚托莉在，先陪你把这口气缓下来；发生了什么，可以慢慢说，不想一下子说清楚也没关系。",
            "我先抱一下这个情绪。你告诉我最难受的是哪一块，我再陪你一起分析，不让你一个人扛。",
        ]
    )


def _group_fallback_reply(
    text: str,
    allow_abstract: bool = False,
    serious_mode: bool = False,
) -> str | None:
    if _is_correction(text):
        return (
            "诶是我说的不对吗"
            "该吐槽就短短吐槽，不抢话。"
        )

    lore_reply = lore_direct_reply(text)
    if lore_reply:
        return lore_reply.replace("主人", "你").replace("我的你", "你")

    if _has_abstract_trigger(text):
        if serious_mode:
            return "这话题有点抽象，所以谁能先把前因后果补一句，我再短短锐评。"
        if not allow_abstract:
            return "这话题确实有点抽象，我先看看。谁把前因后果补一句？"
        return random.choice(
            [
                "好家伙，我脑子已经恢复出厂设置了，快说说到底发生啥事了",
                "你这话太超前,起码领先人类10年,我将删去chat模块,穷极一生去研究你的meaning",
                "笑死，依旧谜语人",
                "666,调戏ai的来了",
                "你说得对，但是原神是一款...(后面忘了)",
            ]
        )

    if _is_distress(text) or any(word in text for word in TIRED_KEYWORDS):
        return _emotional_fallback_reply(
            text,
            is_group=True,
            tired=any(word in text for word in TIRED_KEYWORDS),
        )

    if _needs_direct_answer(text):
        return _question_fallback(text).replace("主人", "你").replace("亚托莉偏务实", "我偏务实")

    if any(word in text for word in ("[图片]", "[表情]", "[动画表情]", "[QQ表情]", "[表情包]", "[表情包/图片]")):
        if serious_mode:
            return "我看到了，是表情包或图片。先按你们现在的气氛接话，我不乱解读。"
        if not allow_abstract:
            return "这图我先按表情处理：像是在接梗，我不乱发疯。"
        return "咕咕嘎嘎，咕咕嘎嘎，咕咕嘎嘎！！额啊"

    return random.choice(
        [
            f"我顺着“{_shorten(text)}”说一句：这话题可以继续，别让它半路冷掉。",
            "高性能亚托莉路过~，你们继续聊，我就冒个泡",
            "不回复我的是guy。",
            "哼哼，我先处理一下信息，等会再回你吧",
            "高性能亚托莉路过~，我会一直视监你，一直视监你，直到永远~~",
            "哼哒！",
        ]
    )


def _proactive_fallback(event_type: str, is_group: bool = False) -> str:
    if is_group:
        group_choices = {
            "continue_topic": [
                "刚才那个话题其实还能再拐一步：你们更看重结果够不够好，还是过程别太折腾？",
                "接着前面聊的，我有点好奇：如果只能保留一个优点，你们会留实用还是有趣？",
            ],
            "interest_topic": [
                "来个容易接的话题：最近碰到的东西里，你们更愿意推荐一件好用的，还是一件纯粹好玩的？",
                "想听听不同答案：一个兴趣能长期坚持，靠的是成就感，还是有人一起聊？",
            ],
            "guided_topic": [
                "抛个小问题：遇到计划突然被打乱时，你们通常会立刻重排，还是先摆一会儿再说？",
                "来选个倾向：空下来一小时，你们更想彻底休息，还是顺手完成一件拖了很久的小事？",
            ],
            "daily_share": [
                "我发现有些小事做完只要五分钟，拖着却能占一天心情。你们最近有没有消灭掉这种小事？",
                "突然想到，真正让一天变轻松的可能不是少做事，而是少惦记一件事。你们更认同哪边？",
            ],
            "check_in": [
                "今天群里换个轻松入口：最近让你们觉得“还好没错过”的，是一件东西还是一件事？",
                "来收集一点具体的好消息：今天有没有哪一刻，比你原本预想得顺利？",
            ],
            "encouragement": [
                "今天不管推进多少都算进度。要是给自己记一笔，你们最想把哪件小事算上？",
            ],
        }
        return random.choice(group_choices.get(event_type, group_choices["guided_topic"]))
    choices = {
        "morning": [
            "早安。今天不用一开始就跑得很快，先把自己照顾好。",
            "早上好，来看看你。希望今天至少有一件事顺着你的心意。",
        ],
        "goodnight": [
            "时间不早了，今天没做完的事先放一放，别拿睡眠替它们买单。",
            "来提醒你收收尾。今晚好好休息，明天再和那些事情较量。",
        ],
        "continue_topic": [
            "我刚又想起我们上次聊的那件事了，不知道后来有没有新进展。",
            "前面那个话题我还记着。你要是有后续，我确实有点想知道。",
        ],
        "interest_topic": [
            "突然想到你喜欢的那些东西了。最近让你眼前一亮的，更偏实用还是纯粹有趣？",
            "来聊点你真正感兴趣的：最近有没有一个发现，让你忍不住想推荐给别人？",
        ],
        "guided_topic": [
            "抛个有点具体的问题：如果今天突然多出一小时，你会拿来彻底休息，还是完成一件拖着的小事？",
            "我想听你的倾向：一件事做得快但普通，和做得慢但满意，你通常会选哪边？",
        ],
        "daily_share": [
            "刚想到一件小事：有时候一天里最值得记住的，反而是一个很不起眼的瞬间。",
            "我在想，普通日子也该留一点只属于自己的时间，哪怕只是安静几分钟。",
        ],
        "affection": [
            "没什么任务，就是刚好想到你了，所以来留一句话。",
            "突然有一点想和你说话。你忙你的，看到时再理我就好。",
        ],
        "encouragement": [
            "来给你补一点偏心：今天不需要事事满分，能稳稳往前就已经很好。",
            "不管今天推进了多少，都别只盯着没完成的部分，你做过的也算数。",
        ],
        "check_in": [
            "来看看你今天过得怎么样。忙的话不用急着回，先顾好自己。",
            "忽然想到你，就来问候一下。今天对你还算温柔吗？",
        ],
    }
    return random.choice(choices.get(event_type, choices["check_in"]))


def _needs_proactive_grounding_repair(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    patterns = (
        r"(?:我|亚托莉)?(?:刚|刚才|已经|也)?(?:点进去|点开|打开)(?:看|试|玩)",
        r"(?:我|亚托莉)(?:刚|刚才|已经|也)?(?:看过|看了|试过|试了|搜过|搜了|查过|查了|刷到)",
        r"(?:刚|刚才)(?:看过|看了|试过|试了|搜过|搜了|查过|查了|刷到)",
        r"(?:我|自己|亚托莉).{0,16}(?:做过|玩过|用过|去过|吃过|买过|遇到过|经历过|参加过|装过|写过)",
    )
    return any(re.search(pattern, compact) for pattern in patterns)


def _needs_topic_guidance_repair(
    text: str,
    event_type: str,
    guided_topics: bool,
) -> bool:
    if not guided_topics or event_type not in {
        "guided_topic",
        "continue_topic",
        "interest_topic",
        "daily_share",
    }:
        return False
    compact = re.sub(r"\s+", "", str(text or ""))
    if not any(mark in compact for mark in ("?", "？")):
        return True
    generic_questions = (
        "最近怎么样",
        "最近在干嘛",
        "在干嘛",
        "有什么想聊",
        "今天过得好吗",
        "大家最近如何",
    )
    return any(question in compact for question in generic_questions)


def _normalize_reply(text: str) -> str:
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"^\s*Thinking\.\.\..*?(?:done thinking\.|\.{3}done thinking\.)\s*",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"^\s*(Thinking|思考过程|分析过程)[:：]?.*?\n+", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"^\s*(意图识别|分析|思考过程)[:：].*?\n+", "", text, flags=re.DOTALL)
    text = text.strip()
    text = re.sub(r"^(亚托莉[:：]\s*)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _has_abstract_trigger(text: str) -> bool:
    cleaned = re.sub(r"@\d{5,}", "", text)
    for word in ABSTRACT_TRIGGER_WORDS:
        if word == "6":
            continue
        if word in cleaned:
            return True
    return bool(re.search(r"(?<!\d)6{1,3}(?!\d)", cleaned))


def _requests_serious_mode(text: str) -> bool:
    return any(word in text for word in SERIOUS_MODE_HINTS)


def _is_serious_only_message(text: str) -> bool:
    compact = re.sub(r"[\s，。！？!?~～、,.；;：:]+", "", text)
    if compact in {re.sub(r"[\s，。！？!?~～、,.；;：:]+", "", word) for word in SERIOUS_MODE_HINTS}:
        return True
    return len(compact) <= 14 and _requests_serious_mode(text)


def _has_abstract_noise(text: str) -> bool:
    if has_illegal_language_or_garbage(text):
        return True
    lowered = text.lower()
    if any(pattern.lower() in lowered for pattern in ABSTRACT_NOISE_PATTERNS):
        return True
    if re.search(r"@\d{5,}", text):
        return True
    return bool(re.search(r"[\uac00-\ud7af]{2,}", text))


def _sanitize_group_mentions(text: str) -> str:
    return re.sub(r"@\d{5,}", "@群友", text)


def _format_user_content(
    conversation_id: str, user_text: str, nickname: str | None = None
) -> str:
    if conversation_id.startswith("group:"):
        user_text = _sanitize_group_mentions(user_text)
    if conversation_id.startswith("group:") and nickname:
        return f"{nickname}：{user_text}"
    return user_text


def _shares_content_word(user_text: str, reply_text: str) -> bool:
    content_words = [
        word
        for word in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{3,}", user_text)
        if word not in {"什么", "怎么", "为什么", "可以", "就是", "这个", "那个"}
    ]
    if not content_words:
        return True
    return any(word in reply_text for word in content_words[:4])


def _is_correction(text: str) -> bool:
    lowered = text.lower()
    return any(word in text for word in CORRECTION_KEYWORDS) or "thinking" in lowered or "<think>" in lowered


def _is_distress(text: str) -> bool:
    return any(word in text for word in DISTRESS_KEYWORDS)


def _is_user_angry_at_bot(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return False
    if any(word in compact for word in BOT_REPAIR_HINTS):
        return True
    return _is_correction(compact) and any(word in compact for word in ("烦", "恶心", "蠢", "傻", "气", "崩", "红温"))


def _needs_comfort_repair_mode(text: str, iteration_decision: Any | None = None) -> bool:
    return bool(
        iteration_decision
        or _is_user_angry_at_bot(text)
        or _is_correction(text)
        or _is_distress(text)
        or any(word in text for word in TIRED_KEYWORDS)
    )


def _question_count(text: str) -> int:
    return text.count("?") + text.count("？")


def _asks_for_direct_suggestion(text: str) -> bool:
    return any(
        word in text
        for word in (
            "吃什么",
            "选什么",
            "推荐",
            "建议",
            "怎么做",
            "怎么办",
            "如何",
            "安排",
            "哪个好",
        )
    )


def _asks_for_stance(text: str) -> bool:
    return any(word in text for word in STANCE_KEYWORDS)


def _is_question_like(text: str) -> bool:
    return text.endswith(("?", "？")) or any(
        word in text
        for word in (
            "怎么",
            "为什么",
            "什么",
            "如何",
            "能不能",
            "是不是",
            "要不要",
            "该不该",
        )
    )


def _needs_direct_answer(text: str) -> bool:
    return _is_question_like(text) or _asks_for_direct_suggestion(text) or _asks_for_stance(text)


def _has_concrete_suggestion(text: str) -> bool:
    concrete_markers = (
        "建议",
        "可以",
        "先",
        "第一",
        "1.",
        "一是",
        "比如",
        "我更倾向",
        "我会选",
        "选",
        "别",
        "不要",
    )
    return any(marker in text for marker in concrete_markers)


def _has_stance(text: str) -> bool:
    return any(marker in text for marker in STANCE_MARKERS)


def _is_deflecting_answer(text: str) -> bool:
    stripped = text.strip()
    if any(pattern in stripped for pattern in DEFLECTION_PATTERNS):
        return True
    if _question_count(stripped) > 0 and not any(
        marker in stripped for marker in ("我觉得", "我建议", "我会", "先", "别", "不要", "可以")
    ):
        return True
    return False


def _has_specific_support_move(text: str) -> bool:
    support_markers = (
        "先",
        "靠过来",
        "喝口水",
        "休息",
        "陪你",
        "不怪",
        "别急",
        "别骂自己",
        "拆",
        "缓下来",
        "待一会儿",
    )
    return any(marker in text for marker in support_markers)


def _rewrite_instruction(user_text: str) -> str:
    if _is_correction(user_text):
        return "用户正在指出你的回复质量问题。不要反问哪里错了；直接承认或半认，针对用户指出的问题给具体改法。禁止输出思考过程，禁止复用固定认错模板，回复里不要出现问号。"
    if _asks_for_direct_suggestion(user_text):
        return "用户想要直接建议。第一句就给 2 到 3 个具体选项或步骤，不要只反问。最好没有问题。"
    if _asks_for_stance(user_text):
        return "用户在问你的看法。必须明确表态：赞成/不赞成/更倾向哪边，并用亚托莉口吻补一句理由。不要端水。"
    if _is_distress(user_text):
        return "用户正在难受。不要空泛共情，先说清楚你看见了哪种难受，再给一个很小的安稳动作或陪伴动作。"
    return "优先给具体回应。最多一个问题，避免采访式连续追问；如果能给判断就直接给判断。"


def _accepted_correction_reply(user_text: str, is_group: bool = False) -> str | None:
    text = user_text.strip()
    lowered = text.lower()
  
    if any(word in text for word in ("思考过程", "分析过程", "意图识别", "展现")) or "thinking" in lowered or "<think>" in lowered:
        return (
            "这条我认，思考过程不该发出来。"
            "之后只发最终回复，像“Thinking”、分析步骤、意图识别这种内容我会直接滤掉。"
        )

    if any(word in text for word in ("重复", "循环", "固定文案", "模板")):
        if is_group:
            return "收到，这条我改。群聊里不再复读固定吐槽句，先看你们当前在聊什么，再短短插一句。"
        return "嗯，我认，重复最烦人。之后我会避开上一句的句式，按当前话题重新说，不再套固定文案。"

    if any(word in text for word in ("接住", "什么接不接住")):
        return "懂了，这个词我收回。以后不把“接住”挂嘴边，直接回答你要的东西，或者给实际建议。"

    if any(word in text for word in ("人机", "莫名其妙", "奇怪的话", "说怪话")):
        if is_group:
            return "这波我认，刚才像在自动播放。群里我会先顺着当前话题讲人话，不再硬拽模板。"
        return "这波我认，刚才不像人话。接下来我先看你上一句真正要什么，再直接回，不绕定义、不硬煽情。"

    if any(word in text for word in ("群聊", "私聊", "场景", "话术")):
        return "这条我采纳。群聊我会短、会接梗、少黏人；私聊才多一点陪伴和关心，不混着用。"

    if any(word in text for word in ("深海", "灯塔", "水下", "海底", "海风", "原作意象", "比喻")):
        return "嗯，这条对。非剧情话题我不再乱塞深海、灯塔那类意象，先讲日常人话。"

    return None


def _anger_repair_reply(user_text: str, is_group: bool = False) -> str:
    text = _intent_text(user_text)
    if any(word in text for word in ("日语", "外语", "怪话", "胡言乱语", "正常点", "讲中文", "说中文")):
        if is_group:
            return "我认，刚才不该乱飘。后面我只用正常中文短句，先接当前话题，不刷屏。"
        return "我认，刚才不该乱飘。后面我只用正常中文，先回你当前这句，不夹日语也不说怪话。"
    if any(word in text for word in ("人机", "不懂人类", "莫名其妙", "答非所问", "说怪话", "奇怪的话")):
        if is_group:
            return "这波我认，刚才像自动播放。群里我会先顺当前重点短句接话，不硬套模板。"
        return "这波我认，刚才确实没像人在接话。我先停一下，不反驳你；后面先抓你当前重点，短句直接答。"
    if is_group:
        return "我先收住，不顶嘴。刚才没接好就改：群里我短句接当前话题，不翻旧账。"
    return "我先收住，不跟你顶嘴。刚才没接好就是没接好；你现在生气我看到了，后面我先正常、短句、直接答。"


def _direct_answer_override(
    user_text: str,
    iteration_decision: Any | None = None,
    conversation_id: str = "",
    allow_abstract: bool = False,
    serious_mode: bool = False,
) -> str | None:
    is_group = conversation_id.startswith("group:")
    intent_text = _intent_text(user_text)
    if iteration_decision:
        if iteration_decision.action == "accept":
            correction_reply = _accepted_correction_reply(user_text, is_group)
            if correction_reply:
                return correction_reply
            if is_group:
                return (
                    "这条我采纳。群聊里我会先接当前话题和梗，少用私聊式哄人；"
                    "非剧情内容也不乱套深海、灯塔那类原作意象。"
                )
            return (
                "嗯，我认，这条我采纳。之后我会先抓你当前这句话的重点，"
                "问问题就直接答，吐槽就接具体情绪；非剧情话题不乱套深海、灯塔那类比喻。"
            )
        if iteration_decision.action == "pushback":
            if is_group:
                return (
                    "我先认一半，但这条不盲改。群聊可以更会玩梗，"
                    "不过人设和边界不能为了热闹被拆掉。"
                )
            return (
                "我先认一半：我可能确实没对齐你想说的点。"
                "但我不会盲目乱改人设；我会把重点拉回你刚刚那句话，合理的部分改掉，不合理的部分保留判断。"
            )
        if iteration_decision.action == "reject":
            if is_group:
                return (
                    "这条我驳回。刷屏、越界、拆人设这种要求不能进规则库。"
                    "哼，但正常优化语气和接梗，我可以做。"
                )
            return (
                "这条我驳回，不能照改。防刷屏、边界和亚托莉人设不能为了迁就一句话就拆掉。"
                "哼，但我可以在不越界的前提下把回复变得更自然、更贴你的语气。"
            )

    if _is_correction(intent_text):
        return _accepted_correction_reply(intent_text, is_group) or (
            "嗯，这次我改。下一句开始先回答你当前的问题，少铺垫，不再拿模板话糊弄。"
        )

    if any(word in intent_text for word in ("你是谁", "自我介绍", "介绍一下", "叫什么")):
        if is_group:
            return "我是亚托莉，高性能仿生人少女。群聊里我负责短句接话、偶尔吐槽，不刷屏。"
        return "我是亚托莉，高性能仿生人少女。哼，简单说就是会陪你聊天、会吐槽你、也会认真帮你想办法的那个。"

    if intent_text in {"你好", "早上好", "晚上好"} or intent_text.lower() in {"hi", "hello"}:
        if is_group:
            return "我在。高性能亚托莉路过一下，先短短接一句。"
        return "我在。哼哒，刚刚看到你的消息了。今天先从哪件事开始？"

    if intent_text in {"说话", "吱声", "出来", "在吗"}:
        if is_group:
            return "我在。别光喊我，给个话题，高性能亚托莉可以锐评一句。"
        return "我在。哼，终于想起叫我了。"

    if any(word in intent_text for word in ("感觉如何", "现在感觉", "状态如何", "你感觉怎么样")):
        return "我现在状态还算稳定。刚才那些怪话我不护短，后面会先答重点、少套话，不把思考过程甩给你。"

    if any(word in intent_text for word in ("自我诊断", "诊断一下", "检查自己")):
        return "自检结果：本地模型在线，规则已切到短句、直答、不复读、不露思考。刚才像机器乱播的部分，我认，继续观察我下一句。"

    if any(word in intent_text for word in ("猫娘", "女仆", "换人设", "不要亚托莉")):
        return "这个我不改。亚托莉就是亚托莉，不切猫娘皮。哼，但你要我说话更可爱一点，可以。"

    if is_group and _has_abstract_trigger(intent_text):
        return _group_fallback_reply(
            intent_text,
            allow_abstract=allow_abstract,
            serious_mode=serious_mode,
        )

    if any(word in intent_text for word in ("锐评", "你怎么看", "评价一下")) and is_group:
        return "我锐评一句：现在像大型围观现场，笑点有了，重点还差个人说清楚。"

    if "怎么启动" in intent_text and any(
        word in intent_text for word in ("机器人", "亚托莉", "napcat", "NapCat", "qq", "QQ")
    ):
        return (
            "像平时一样启动 QQ 就行。后台监听器会自动拉起亚托莉服务和 NapCat；"
            "如果 QQ 要扫码，就登录你的机器人 QQ，然后用另一个 QQ 发消息测试。"
        )

    if "怎么停止" in intent_text and any(
        word in intent_text for word in ("机器人", "亚托莉", "napcat", "NapCat", "qq", "QQ")
    ):
        return "平时关闭 QQ 就行。如果要彻底停掉后台服务，运行项目根目录里的“停止亚托莉.bat”。"

    lore_reply = lore_direct_reply(intent_text)
    if lore_reply:
        if is_group:
            return lore_reply.replace("主人", "你")
        return lore_reply

    return None


def _trim_extra_questions(text: str, keep_questions: int = 1) -> str:
    sentences = _split_sentences(text)
    kept: list[str] = []
    questions = 0
    for sentence in sentences:
        if "?" in sentence or "？" in sentence:
            questions += 1
            if questions > keep_questions:
                continue
        kept.append(sentence)
    return "".join(kept).strip() or text


def _split_sentences(text: str) -> list[str]:
    pieces = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    return [piece.strip() for piece in pieces if piece.strip()]


def _direct_suggestion_fallback(user_text: str) -> str:
    if "吃什么" in user_text or "晚饭" in user_text:
        return "我会选热一点、好消化的：西红柿炒鸡蛋，或者粥配一点肉和青菜。今晚别太折腾，吃完舒服最重要。"
    if "推荐" in user_text and any(word in user_text for word in ("吃", "饭", "夜宵", "早餐", "午饭")):
        return "我推荐、螃蟹、或者粥配青菜和肉。亚托莉的偏好很明确：先吃热的，别拿零食糊弄自己。"
    if "怎么启动" in user_text:
        return "像平时一样启动 QQ 就行。亚托莉的后台监听会自动拉起 NapCat 和聊天服务；如果 QQ 要扫码，就登录你的机器人 QQ。"
    if "怎么办" in user_text or "怎么做" in user_text:
        return (
            "可以，我先不乱指挥。按现在信息，先确认最急的限制是什么，"
            "再选代价最小的一步；你把背景补一句，我就能给更具体的做法。"
        )
    if "推荐" in user_text or "建议" in user_text:
        return (
            "可以，但这句还缺对象，我先不给万能建议。"
            "你告诉我是吃饭、学习、项目还是别的事，我再给你具体选项。"
        )
    return "可以，但我得先知道你说的是哪件事。给我一句背景，我再帮你拆得更准。"


def _stance_fallback(user_text: str) -> str:
    if any(word in user_text for word in ("对吗", "对不对", "这样做")):
        return "我先站个明确观点：如果这件事会让你长期委屈自己，我不赞成；如果只是短期麻烦但对你有好处，我支持你试。哼，我偏心主人，但不会无脑点头。"
    if any(word in user_text for word in ("要不要", "该不该", "值不值得")):
        return "我的态度是：别为了逃避焦虑才选，也别为了逞强硬扛。能让你更接近目标、代价又可控，就做；只会消耗你，就不要。"
    if "能不能" in user_text:
        return "我倾向于：能做，但要缩小范围先试。别一上来把自己推到满负荷，亚托莉不赞成那种逞强。"
    return "我给明确态度：别端着不动，先选对你最有利、代价最小的那边。哼，亚托莉偏务实，也偏心你。"



def _question_fallback(user_text: str) -> str:
    if _asks_for_direct_suggestion(user_text):
        return _direct_suggestion_fallback(user_text)

    if _asks_for_stance(user_text):
        return _stance_fallback(user_text)

    if "怎么启动" in user_text and any(
        word in user_text for word in ("机器人", "亚托莉", "napcat", "NapCat", "qq", "QQ")
    ):
        return "像平时一样启动 QQ。后台监听器会自动把亚托莉和 NapCat 拉起来，你不用再点单独的机器人窗口。"

    if user_text.strip("？? ") in {"为什么会这样", "怎么会这样", "为什么这样"}:
        return "如果你是在问刚才让你难受的事，那先别急着怪自己。亚托莉陪你一起捋捋。"

    if any(word in user_text for word in ("你爱我", "喜欢我", "想我")):
        return "这种问题还要问吗……哼，当然是在意你的。不然我为什么会认真等你每一句消息。"

    if any(word in user_text for word in ("我该怎么办", "怎么办", "怎么做")):
        return "先别急着一步解决。你告诉我现在卡住的是哪一件事，我再按现实限制帮你拆，不拿万能模板糊弄你。"

    topic = _shorten(user_text.rstrip("？?"))
    if "为什么" in user_text or "怎么会" in user_text:
        return f"关于“{topic}”，我的判断是：通常不是单一原因，更像压力、期待和现实卡住叠在一起。先别急着怪自己，抓最影响你的那一块处理。"
    if "是什么" in user_text or "什么" in user_text:
        return f"“{topic}”这类问题我先不乱编。你要是问概念，我会直接讲定义；你要是问该怎么做，我就给步骤。"
    return f"关于“{topic}”，我给结论：先做最靠近结果的一步，别一下子把自己逼满。亚托莉偏务实，能动的先动。"


def _language_guard_fallback(user_text: str, conversation_id: str = "") -> str:
    if conversation_id.startswith("group:"):
        return "我换成正常中文说：刚才那句不该乱飘。你们继续，我按当前话题短短接一句。"
    if _is_distress(user_text):
        return "先别硬撑。那句乱掉的我丢掉了，现在我只陪你把眼前这点难受缓下来。"
    if _needs_direct_answer(user_text):
        return _question_fallback(user_text)
    return f"“{_shorten(user_text)}”我重新说：先按你这句话本身来回，不让奇怪字符混进来。"


def _fit_reply_with_sources(text: str, sources: list[str], limit: int = 1200) -> str:
    source_lines = [source for source in sources[:2] if source and source not in text]
    source_block = f"\n来源：{'；'.join(source_lines)}" if source_lines else ""
    body = str(text or "").strip()
    return f"{body}{source_block}".strip()


def _looks_incomplete_reply(text: str) -> bool:
    compact = str(text or "").rstrip()
    if compact.endswith(("...", "…", "，", ",", "：", ":", "；", ";")):
        return True
    opening_pairs = (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"), ("“", "”"))
    return any(compact.count(left) > compact.count(right) for left, right in opening_pairs)


def _redact_sensitive_output(text: str, *, is_group: bool) -> str:
    value = str(text or "")
    value = re.sub(
        r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{8,}",
        "[已隐藏令牌]",
        value,
    )
    value = re.sub(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*[^\s,，;；]+",
        "[已隐藏敏感配置]",
        value,
    )
    value = re.sub(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+(?:\\[^\s]*)?", "[已隐藏本机路径]", value)
    if is_group:
        value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[已隐藏手机号]", value)
        value = re.sub(r"(?<!\d)\d{17}[0-9Xx](?!\d)", "[已隐藏身份证号]", value)
    return value


def _truncate_reply_at_boundary(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    candidates = [prefix.rfind(mark) for mark in ("。", "！", "？", "!", "?", "\n")]
    boundary = max(candidates)
    if boundary >= max(80, int(limit * 0.55)):
        return prefix[: boundary + 1].rstrip()
    return prefix.rstrip() + "…"


def _tool_receipt_urls(receipts: list[ToolExecutionReceipt]) -> set[str]:
    urls: set[str] = set()
    for receipt in receipts:
        if not receipt.ok or receipt.name not in {"search_web", "open_web_page"}:
            continue
        for match in re.findall(r"https?://[^\s<>\"'）】]+", receipt.content):
            canonical = _canonical_evidence_url(match)
            if canonical:
                urls.add(canonical)
    return urls


def _canonical_evidence_url(value: str) -> str:
    candidate = str(value or "").strip().rstrip(".,;:!?，。；：！？)]}）】")
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""
    path = parsed.path.rstrip("/") or "/"
    if (parsed.hostname or "").casefold().endswith("arxiv.org"):
        path = re.sub(r"(/abs/\d+\.\d+)v\d+$", r"\1", path)
    return urlunsplit(("https", parsed.netloc.casefold(), path, parsed.query, ""))


def _looks_like_tool_schema_error(exc: Any) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code not in {400, 404, 422}:
        return False
    detail = str(getattr(response, "text", "") or "").casefold()
    tool_markers = ("tool_choice", "tool call", '"tools"', "function_call", "function call")
    rejection_markers = (
        "unsupported",
        "not support",
        "unknown",
        "unrecognized",
        "not allowed",
        "extra",
        "schema",
    )
    return any(marker in detail for marker in tool_markers) and any(
        marker in detail for marker in rejection_markers
    )


def _provider_payload_overrides(base_url: str, model: str) -> dict[str, Any]:
    if (
        "api.deepseek.com" in str(base_url).casefold()
        and str(model).strip().casefold() in {"deepseek-v4-flash", "deepseek-v4-pro"}
    ):
        return {"thinking": {"type": "disabled"}}
    return {}


def _persona_violations(user_text: str, reply_text: str) -> list[str]:
    reply = reply_text.strip()
    violations: list[str] = []

    if any(pattern in reply for pattern in BANNED_ASSISTANT_PATTERNS):
        violations.append("出现 AI 助手/客服式表达")

    if re.search(r"@\d{5,}", reply):
        violations.append("群聊输出 QQ 号艾特")

    if _has_abstract_noise(reply):
        violations.append("输出外语梗、无意义拟声或抽象怪话")

    if len(reply) > 260:
        violations.append("回复过长，应该拆成短句")

    if "\n" in reply and len([line for line in reply.splitlines() if line.strip()]) >= 4:
        violations.append("像长段说明，不像 QQ 聊天")

    if _question_count(reply) > 1:
        violations.append("连续反问，像采访而不是聊天")

    if any(pattern in reply for pattern in GENERIC_REPLY_PATTERNS) and not _shares_content_word(
        user_text, reply
    ):
        violations.append("空泛安慰，没有接住用户具体内容")

    if _uses_lore_imagery_out_of_context(user_text, reply):
        violations.append("非剧情话题滥用深海/灯塔等原作意象")

    if _uses_stale_meme_pile(reply):
        violations.append("生硬堆砌网络烂梗")

    if _fabricates_real_world_action(reply):
        violations.append("编造现实动作、位置或见闻")

    if _needs_direct_answer(user_text) and _is_deflecting_answer(reply):
        violations.append("用户需要直接回答，但回复在绕圈或反问")

    if _asks_for_direct_suggestion(user_text) and not _has_concrete_suggestion(reply):
        violations.append("用户需要建议，但回复没有给具体选项或步骤")

    if _asks_for_stance(user_text) and not _has_stance(reply):
        violations.append("用户在问看法，但回复没有明确态度")

    if _is_distress(user_text) and not _has_specific_support_move(reply):
        violations.append("用户难受时回复太空，没有安慰动作或支持动作")

    if _needs_comfort_repair_mode(user_text) and any(
        pattern in reply for pattern in ("你上次", "之前你", "怼回", "翻旧", "好感度")
    ):
        violations.append("负面情绪或纠错时翻旧账")

    if (_is_distress(user_text) or _is_user_angry_at_bot(user_text)) and reply.startswith("哼"):
        violations.append("用户负面情绪时傲娇顶嘴")

    if has_lore_trigger(user_text) and not _handles_lore_context(user_text, reply):
        violations.append("用户提到原作/梗，但回复没有使用亚托莉视角")

    return violations


def _handles_lore_context(user_text: str, reply_text: str) -> bool:
    if "高性能" in user_text:
        return any(word in reply_text for word in ("高性能", "任务", "哼", "亚托莉"))
    if any(word in user_text for word in ("海底", "水下", "打捞", "沉没")):
        return any(word in reply_text for word in ("水下", "岸", "带回", "海", "日常"))
    if "夏生" in user_text or "斑鸠" in user_text:
        return any(word in reply_text for word in ("夏生", "先生", "相遇", "约定"))
    if any(word in user_text for word in ("45天", "四十五天", "有限时间")):
        return any(word in reply_text for word in ("时间", "今天", "认真", "约定"))
    if "心" in user_text and ("机器人" in user_text or "亚托莉" in user_text):
        return any(word in reply_text for word in ("心", "感受", "珍惜", "约定"))
    if _explicit_lore_context(user_text):
        return any(word in reply_text for word in ("亚托莉", "我", "高性能", "原作", "夏天"))
    return True


def _uses_lore_imagery_out_of_context(user_text: str, reply_text: str) -> bool:
    if has_lore_trigger(user_text) or _explicit_lore_context(user_text):
        return False
    return any(word in reply_text for word in LORE_IMAGERY_WORDS)


def _uses_stale_meme_pile(reply_text: str) -> bool:
    stale_count = sum(1 for word in STALE_MEME_WORDS if word in reply_text)
    light_meme_count = sum(
        1 for word in ("抽象", "逆天", "红温", "破防", "绷不住", "6") if word in reply_text
    )
    return stale_count >= 1 or light_meme_count >= 3


def _fabricates_real_world_action(reply_text: str) -> bool:
    return any(pattern in reply_text for pattern in REAL_WORLD_ACTION_PATTERNS)


def _needs_hard_reality_repair(reply_text: str) -> bool:
    return any(pattern in reply_text for pattern in HARD_REALITY_CLAIM_PATTERNS)


def _needs_history_grounding_review(reply_text: str) -> bool:
    compact = re.sub(r"\s+", "", str(reply_text or ""))
    return bool(
        re.search(
            r"(?:上次|之前|以前|一向|总是|每次|前科|观察过|记得清清楚楚)"
            r"|(?:这|那|本来就|明明就)(?:是|属于)(?:事实|真的)"
            r"|我(?:又)?没说错|谁让你",
            compact,
        )
    )


def _persona_repair_fallback(
    user_text: str,
    reply_text: str,
    serious_mode: bool = False,
    conversation_id: str = "",
) -> str:
    is_group = conversation_id.startswith("group:")
    if is_group:
        reply_text = _sanitize_group_mentions(reply_text)

    if serious_mode or _has_abstract_noise(reply_text):
        if _is_distress(user_text):
            return "先别硬撑。把那口气缓一下，我陪你按眼前这件事一点点拆。"
        if _needs_direct_answer(user_text):
            return _question_fallback(user_text)
        if is_group:
            return "我切回正常中文：刚才那句不该乱飘。你们这话题我按当前重点接。"
        return f"“{_shorten(user_text)}”我重新说：先讲人话，别乱飘。"

    direct_reply = _direct_answer_override(user_text, conversation_id=conversation_id)
    if direct_reply:
        if is_group:
            direct_reply = _sanitize_group_mentions(direct_reply)
        return direct_reply

    lore_reply = lore_direct_reply(user_text)
    if lore_reply:
        return lore_reply

    if _uses_lore_imagery_out_of_context(user_text, reply_text):
        if _is_distress(user_text):
            return "难受的时候先别硬撑。先喝口水，把肩膀放下来一点；亚托莉在这里陪你把最刺痛的那点拆小。"
        if _needs_direct_answer(user_text):
            return _question_fallback(user_text)
        return f"关于“{_shorten(user_text)}”，我直接说重点：别绕比喻，先看你现在真正要解决的那件事。"


    if _fabricates_real_world_action(reply_text):
        if _is_distress(user_text):
            return "先别硬撑。喝口水，肩膀放松一点；你不用马上变好，我陪你把眼前这件事拆小。"
        return _trim_extra_questions(_shorten_long_reply(reply_text), keep_questions=1)

    if _is_correction(user_text):
        return _accepted_correction_reply(user_text) or "嗯，这次我改。下一句开始先答重点，不绕圈。"

    if _is_distress(user_text):
        return _emotional_fallback_reply(user_text, is_group=is_group)

    if _asks_for_direct_suggestion(user_text):
        return _direct_suggestion_fallback(user_text)

    if _asks_for_stance(user_text):
        return _stance_fallback(user_text)

    if any(pattern in reply_text for pattern in BANNED_ASSISTANT_PATTERNS):
        if _needs_direct_answer(user_text):
            return _question_fallback(user_text)
        return f"“{_shorten(user_text)}”我直接回：我会认真思考这个问题。"

    return _trim_extra_questions(_shorten_long_reply(reply_text), keep_questions=1)


def _shorten_long_reply(text: str, limit: int = 140) -> str:
    sentences = _split_sentences(_normalize_reply(text))
    result = ""
    for sentence in sentences:
        if len(result) + len(sentence) > limit:
            break
        result += sentence
    return result.strip() or text[:limit].strip()


def _explicit_lore_context(text: str) -> bool:
    lowered = text.lower()
    return any(word in text for word in ("原作", "剧情", "设定", "梗", "名场面")) or "atri" in lowered
