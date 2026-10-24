from __future__ import annotations

import json
import re
from typing import Any

from ..prompting import load_prompt


FINAL_ANSWER_TOOL_NAME = "final_answer"


# 工具行动规则统一由 docs/prompts/tool_use.md 维护。
AGENT_ACTION_PROMPT = load_prompt("tool_use")

_DEFERRED_ACTION_PATTERNS = (
    re.compile(r"(?:我)?(?:正在|正帮你|这就|马上|现在就)(?:去)?(?:搜|搜索|查|查询|翻|找|检索)"),
    re.compile(r"(?:稍等|等我(?:一下|一会儿|会儿)|你等(?:一下|一会儿|会儿))"),
    re.compile(r"(?:马上|一会儿|稍后)(?:就)?(?:给你|告诉你|发你).{0,10}(?:结果|答案|资料|链接)"),
    re.compile(r"(?:找到|查到|搜到)(?:后|了以后).{0,10}(?:告诉|发给|给)你"),
    re.compile(r"(?:过|等)?\s*[一二两三四五六七八九十\d]+\s*分钟后.{0,12}(?:找你|告诉你|回复你|发给你)"),
)


def final_answer_schema(max_chars: int = 1200) -> dict[str, Any]:
    limit = max(80, min(4000, int(max_chars or 1200)))
    return {
        "type": "function",
        "function": {
            "name": FINAL_ANSWER_TOOL_NAME,
            "description": (
                "提交现在就能发送给用户的最终回复。只有已经掌握足够上下文，或已完成必要的搜索/阅读后才能使用；"
                "不得用它表示正在搜索、稍后处理或尚未执行的动作。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "立即发送给用户的完整回复。按亚托莉本人的口吻直接讲清楚结论和关键信息，"
                            "不要罗列“能确认什么、不能确认什么”，不要交代自己看到了哪些材料、"
                            "也不要输出思考过程或括号备注。"
                        ),
                        "maxLength": limit,
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 4,
                        "description": (
                            "本轮使用搜索或网页阅读时，列出实际工具结果中出现的来源 URL"
                            "（只需 host 和路径正确，不必带分享或追踪参数）；"
                            "没有使用外部资料时传空数组。不得编造 URL。"
                        ),
                    },
                },
                "required": ["text", "sources"],
                "additionalProperties": False,
            },
        },
    }


def final_answer_from_call(call: dict[str, Any]) -> str:
    return str(final_answer_payload_from_call(call).get("text") or "").strip()


def final_answer_payload_from_call(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function")
    if not isinstance(function, dict) or str(function.get("name") or "") != FINAL_ANSWER_TOOL_NAME:
        return {}
    raw = function.get("arguments")
    if isinstance(raw, dict):
        arguments = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        arguments = parsed if isinstance(parsed, dict) else {}
    else:
        arguments = {}
    sources = arguments.get("sources")
    return {
        "text": str(arguments.get("text") or "").strip(),
        "sources": [str(item).strip() for item in sources if str(item).strip()]
        if isinstance(sources, list)
        else [],
    }


def has_unsupported_deferred_action(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _DEFERRED_ACTION_PATTERNS)


def has_unverified_research_claim(text: str, successful_tools: set[str]) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return False
    claimed_search = bool(
        re.search(r"(?:我)?(?:搜索到|搜到|查到|检索到|根据搜索|搜索结果(?:显示|表明))", normalized)
    )
    claimed_page = bool(re.search(r"(?:我)?(?:打开|读了|看了).{0,8}(?:网页|页面|原文)", normalized))
    if claimed_page and "open_web_page" not in successful_tools:
        return True
    return claimed_search and not ({"search_web", "open_web_page"} & successful_tools)


# 明确要求联网的说法，命中即必须取证。
_EXPLICIT_SEARCH_MARKERS = (
    "搜一下", "搜搜", "搜索一下", "帮我搜", "帮我查", "查一下", "查查", "百度一下",
    "网上查", "上网查", "联网查",
)
# 会随时间变化、模型训练记忆不可靠的事实标记。
_TIME_SENSITIVE_MARKERS = (
    "最新", "最近", "目前", "今年", "本月", "本周", "版本", "更新", "发布", "发售",
    "上市", "上线", "价格", "多少钱", "涨价", "降价", "汇率", "政策", "规定",
    "新闻", "排名", "股价", "销量", "赛事", "比赛结果", "新角色", "新皮肤",
    "新版本", "更新内容", "预约", "官宣", "爆料",
)
# 专业/领域知识标记：容易超出小模型可靠范围、值得取证后回答。
_DOMAIN_MARKERS = (
    "算法", "原理", "机制", "架构", "框架", "api", "接口", "语法", "编译", "运行时",
    "并发", "并行", "线程", "协程", "进程", "内存", "数据库", "索引", "缓存", "网络",
    "协议", "正则", "类型", "继承", "指针", "汇编", "微积分", "统计", "概率",
    "电路", "化学", "物理", "法律", "合同", "税", "医学", "药物", "论文", "模型",
    "训练", "推理", "参数", "调参", "部署", "容器", "加密", "证书", "漏洞", "渗透",
    "asyncio", "python", "rust", "java", "docker", "kubernetes", "sql", "git",
)
_ASKING_RE = re.compile(r"[?？]|吗|呢|什么|哪|几|多少|是不是|有没有|值不值|该用|怎么|如何|为什么|区别|对比|优缺点|哪个好|原理")


def needs_fresh_evidence(text: str) -> bool:
    """判断这条提问是否必须先联网取证再回答。

    分两类：明确要求搜索，或"时效性事实/专业领域知识 + 在提问"的组合。
    刻意要求同时出现"在提问"信号，避免把普通闲聊（"你现在开心吗"）误判成搜索。
    """
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in _EXPLICIT_SEARCH_MARKERS):
        return True
    if not _ASKING_RE.search(normalized):
        return False
    if any(marker in normalized for marker in _TIME_SENSITIVE_MARKERS):
        return True
    return any(marker in normalized for marker in _DOMAIN_MARKERS)


def rejected_final_answer_messages(call: dict[str, Any], reason: str) -> list[dict[str, Any]]:
    call_id = str(call.get("id") or "final-answer")
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [call],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": FINAL_ANSWER_TOOL_NAME,
            "content": (
                "最终回答未通过校验："
                f"{reason}。需要资料就现在调用真实工具；否则立即给出诚实、完整的 final_answer。"
            ),
        },
    ]
