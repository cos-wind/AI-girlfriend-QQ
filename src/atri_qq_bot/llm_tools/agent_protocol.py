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
                        "description": "立即发送给用户的完整回复。前沿或未解问题要区分已知、研究现状和未知。",
                        "maxLength": limit,
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 4,
                        "description": (
                            "本轮使用搜索或网页阅读时，列出实际工具结果中出现的来源 URL；"
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
