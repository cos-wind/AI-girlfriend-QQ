from __future__ import annotations

import json
from typing import Any

from .time_tool import get_current_time
from .web_search_tool import search_web


def tool_calls_from_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    if isinstance(calls, list):
        return [call for call in calls if isinstance(call, dict)]

    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        return [
            {
                "id": "legacy-function-call",
                "type": "function",
                "function": function_call,
            }
        ]
    return []


async def append_tool_results(
    messages: list[dict[str, Any]],
    assistant_message: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    config: Any,
) -> int:
    max_calls = max(1, int(getattr(config, "llm_tool_max_calls", 2) or 2))
    selected_calls = tool_calls[:max_calls]
    messages.append(_assistant_tool_call_message(assistant_message, selected_calls))

    executed = 0
    for call in selected_calls:
        name = _tool_name(call)
        arguments = _tool_arguments(call)
        content = await _execute_tool(name, arguments, config)
        messages.append(_tool_message(call, name, content))
        executed += 1
    return executed


def _assistant_tool_call_message(
    assistant_message: dict[str, Any], tool_calls: list[dict[str, Any]]
) -> dict[str, Any]:
    message = {
        "role": "assistant",
        "content": assistant_message.get("content") or "",
        "tool_calls": tool_calls,
    }
    return message


def _tool_message(call: dict[str, Any], name: str, content: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": str(call.get("id") or "tool-call"),
        "name": name,
        "content": content,
    }


def _tool_name(call: dict[str, Any]) -> str:
    function = call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "").strip()
    return ""


def _tool_arguments(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function")
    raw = function.get("arguments") if isinstance(function, dict) else {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _execute_tool(name: str, arguments: dict[str, Any], config: Any) -> str:
    if name == "get_current_time":
        return get_current_time(arguments)
    if name == "search_web":
        if not bool(getattr(config, "web_search_enabled", True)):
            return "联网搜索未启用。不要编造实时信息，可以说明当前不能搜索网页。"
        return await search_web(arguments, config)
    return f"未知工具：{name}。不要编造这个工具的结果。"
