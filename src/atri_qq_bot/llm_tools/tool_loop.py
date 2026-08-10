from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..application.contracts import ToolReceipt as ToolExecutionReceipt
from .web_search_tool import search_web
from .registry import ToolRegistry


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
    executor: Callable[[str, dict[str, Any], Any], Awaitable[str | None]] | None = None,
    max_calls: int | None = None,
    context_id: str = "",
    receipts: list[ToolExecutionReceipt] | None = None,
    registry: ToolRegistry | None = None,
) -> int:
    call_limit = (
        max(1, int(getattr(config, "llm_tool_max_calls", 2) or 2))
        if max_calls is None
        else max(1, int(max_calls))
    )
    selected_calls = tool_calls[:call_limit]
    tool_registry = registry or _runtime_tool_registry(config)
    messages.append(_assistant_tool_call_message(assistant_message, selected_calls))

    executed = 0
    for call in selected_calls:
        name = _tool_name(call)
        arguments, arguments_error = _parse_tool_arguments(call)
        started = time.perf_counter()
        if arguments_error:
            content = f"工具参数无效：{arguments_error}。请修正参数后重新调用，不要编造结果。"
        else:
            try:
                content = await executor(name, arguments, config) if executor is not None else None
                if content is None:
                    content = await tool_registry.execute(name, arguments)
            except Exception as exc:
                content = f"工具执行失败：{_short_error(exc)}。不要编造工具结果。"
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        ok = not _tool_result_failed(content)
        _log_tool_event(
            context_id=context_id,
            name=name,
            arguments=arguments,
            content=content,
            elapsed_seconds=elapsed_ms / 1000,
        )
        messages.append(_tool_message(call, name, content))
        if receipts is not None:
            receipts.append(
                ToolExecutionReceipt(
                    call_id=str(call.get("id") or "tool-call"),
                    name=name,
                    arguments=arguments,
                    ok=ok,
                    content=content,
                    elapsed_ms=elapsed_ms,
                )
            )
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
    arguments, _ = _parse_tool_arguments(call)
    return arguments


def _parse_tool_arguments(call: dict[str, Any]) -> tuple[dict[str, Any], str]:
    function = call.get("function")
    raw = function.get("arguments") if isinstance(function, dict) else {}
    if isinstance(raw, dict):
        return raw, ""
    if not isinstance(raw, str) or not raw.strip():
        return {}, ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}, "参数不是合法 JSON"
    if not isinstance(parsed, dict):
        return {}, "参数必须是 JSON 对象"
    return parsed, ""


async def _execute_tool(name: str, arguments: dict[str, Any], config: Any) -> str:
    """Compatibility shim for callers that still target the legacy helper."""
    return await _runtime_tool_registry(config).execute(name, arguments)


def _runtime_tool_registry(config: Any) -> ToolRegistry:
    """Keep the historic module patch seam while moving execution to a registry."""
    return ToolRegistry(
        config,
        handlers={
            "search_web": _web_search_handler,
        },
    )


async def _web_search_handler(arguments: dict[str, Any], config: Any) -> str:
    if not bool(getattr(config, "web_search_enabled", True)):
        return "联网搜索未启用。不要编造实时信息，可以说明当前不能搜索网页。"
    return await search_web(arguments, config)


def _tool_result_failed(content: str) -> bool:
    text = str(content or "")
    return text.startswith(
        (
            "工具执行失败",
            "工具参数无效",
            "搜索失败",
            "天气查询失败",
            "网页读取失败",
            "未知工具",
        )
    ) or any(marker in text for marker in ("当前未启用", "未获允许"))


def _log_tool_event(
    context_id: str,
    name: str,
    arguments: dict[str, Any],
    content: str,
    elapsed_seconds: float,
) -> None:
    if not context_id:
        return
    failed = _tool_result_failed(content)
    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "context_id": context_id,
        "tool": name,
        "arguments": _safe_log_arguments(name, arguments),
        "status": "failed" if failed else "ok",
        "elapsed_ms": round(elapsed_seconds * 1000),
        "result_preview": " ".join(content.split())[:240],
    }
    try:
        log_path = Path(__file__).resolve().parents[3] / "logs" / "llm-tools.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        return


def _safe_log_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "speak_as_atri":
        return {
            key: value
            for key, value in arguments.items()
            if key in {"emotion", "intensity", "language", "reason", "mode"}
        }
    return {key: str(value)[:160] for key, value in arguments.items()}


def _short_error(exc: Exception) -> str:
    return " ".join((str(exc).strip() or exc.__class__.__name__).split())[:180]
