from __future__ import annotations

import json
import logging
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
from ..cognition.prompt_context import render_cognition_context
from ..cognition.store import CognitionStateStore
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
    has_lore_trigger,
    lore_direct_reply,
)
from ..memory import UserMemoryStore, is_memory_pollution_text
from ..music import delivery_song_catalog_prompt
from ..prompting import load_prompt, render_prompt
from ..proactive import morning_greeting_text, safe_zoneinfo
from ..runtime.inference_lock import InferencePriority, inference_resource_lease
from ..runtime.services import ensure_ollama_service, release_ollama_model
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
LOGGER = logging.getLogger("atri.persona")


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

# 回复失败时曾经出现过的固定文案。它们即使通过普通“像不像人”检查，
# 也不能再次发送；失败必须只进入日志和评测，不得伪装成正常聊天。
FAILURE_TEMPLATE_PATTERNS = (
    "刚才没接住，再说一遍吧",
    "刚才没接住，你再说一遍吧",
    "在呢，刚忙完呢",
    "这张图这次没有稳定识别出来",
    "有一小段语音没有合成",
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


from .engine_context import EngineContextMixin
from .engine_proactive import EngineProactiveMixin
from .engine_reply import EngineReplyMixin
from .engine_state import EngineStateMixin
from .engine_tools import EngineToolsMixin

class AtriReplyEngine(
    EngineStateMixin,
    EngineProactiveMixin,
    EngineReplyMixin,
    EngineToolsMixin,
    EngineContextMixin,
):
    """ATRI 的回复编排层。

    它把人格提示词、当前会话、三层记忆、认知状态、工具结果和输出护栏
    组装成一次模型请求；不直接发送 QQ 消息，发送由 OneBot 层负责。
    """

from .input_helpers import (
    _as_int,
    _chat_http_timeout,
    _is_affection_command,
    _is_local_ollama_endpoint,
    _is_owner_id,
    _intent_text,
    _model_failure_reply,
    _parse_affection_set_value,
    _shorten,
    _user_id_from_profile_id,
)

from . import reply_fallbacks as _reply_fallbacks
from . import reply_rules as _reply_rules

for _helper_module in (_reply_rules, _reply_fallbacks):
    for _helper_name in dir(_helper_module):
        _helper_value = getattr(_helper_module, _helper_name)
        if _helper_name.startswith("_") and callable(_helper_value):
            globals()[_helper_name] = _helper_value

del _helper_module, _helper_name, _helper_value
