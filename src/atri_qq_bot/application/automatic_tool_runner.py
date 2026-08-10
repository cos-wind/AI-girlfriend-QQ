from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .contracts import AgentRunResult, ToolReceipt
from ..llm_tools.registry import ToolRegistry
from ..llm_tools.tool_loop import append_tool_results, tool_calls_from_message


ModelRequest = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolExecutor = Callable[[str, dict[str, Any], Any], Awaitable[str | None]]
ReplyNormalizer = Callable[[str], str]


class AutomaticToolRunner:
    """Run the legacy automatic tool loop behind one small, testable interface.

    This deliberately models only the non-agent-protocol path. The stricter
    final-answer protocol has additional grounding invariants and remains in
    its legacy adapter until it has equivalent replay coverage.

    The runner owns the loop ordering: model response -> bounded tool calls ->
    follow-up response. Its caller retains provider transport, persona prompt
    construction and context-specific tools such as voice delivery.
    """

    def __init__(
        self,
        config: Any,
        request_model: ModelRequest,
        normalize_reply: ReplyNormalizer,
        *,
        tool_executor: ToolExecutor | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self._config = config
        self._request_model = request_model
        self._normalize_reply = normalize_reply
        self._tool_executor = tool_executor
        self._registry = registry

    async def run(
        self,
        messages: list[dict[str, Any]],
        payload: dict[str, Any],
        *,
        context_id: str = "",
    ) -> AgentRunResult:
        message = self._message_from_response(await self._request_model(payload))
        remaining_tool_calls = max(
            1,
            int(getattr(self._config, "llm_tool_max_calls", 2) or 2),
        )
        receipts: list[ToolReceipt] = []

        while remaining_tool_calls > 0:
            tool_calls = tool_calls_from_message(message)
            if not tool_calls:
                break
            executed = await append_tool_results(
                messages,
                message,
                tool_calls,
                self._config,
                executor=self._tool_executor,
                max_calls=remaining_tool_calls,
                context_id=context_id,
                receipts=receipts,
                registry=self._registry,
            )
            remaining_tool_calls -= executed
            followup_payload = dict(payload)
            followup_payload["messages"] = messages
            if remaining_tool_calls <= 0:
                followup_payload.pop("tools", None)
                followup_payload.pop("tool_choice", None)
            message = self._message_from_response(
                await self._request_model(followup_payload)
            )

        content = self._normalize_reply(str(message.get("content") or "")).strip()
        return AgentRunResult(
            reply_text=content[:1200],
            tool_receipts=tuple(receipts),
        )

    @staticmethod
    def _message_from_response(data: dict[str, Any]) -> dict[str, Any]:
        # Preserve the legacy adapter's strict provider response contract:
        # malformed provider payloads still surface to its existing fallback.
        return data["choices"][0]["message"]
