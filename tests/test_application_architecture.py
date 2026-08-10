from __future__ import annotations

import asyncio
from types import SimpleNamespace

from atri_qq_bot.application import (
    ActionProposal,
    AgentRunResult,
    ArtifactEvidence,
    ConversationTurn,
    ConversationTurnRequest,
    DeliveryPlan,
    TurnTrace,
)
from atri_qq_bot.application.automatic_tool_runner import AutomaticToolRunner
from atri_qq_bot.llm_tools.registry import ToolRegistry
from atri_qq_bot.llm_tools.tool_loop import ToolExecutionReceipt, append_tool_results


def test_artifact_evidence_blocks_visual_claims_without_full_evidence() -> None:
    evidence = ArtifactEvidence(
        source="image:fixture",
        level="ocr_only",
        findings=("独立 OCR 文字：你好",),
    )

    assert not evidence.may_describe_visual_content
    assert ConversationTurnRequest(
        turn_id="turn-1",
        conversation_id="private:1",
        profile_id="person:1",
        kind="private",
        user_text="图片写了什么？",
    ).profile_id == "person:1"


def test_turn_trace_keeps_ordered_turn_local_events() -> None:
    trace = TurnTrace("turn-1")
    trace.record("intake", conversation_id="private:1")
    trace.record("tool", name="search_web", ok=True)

    events = trace.snapshot()

    assert [event.stage for event in events] == ["intake", "tool"]
    assert events[1].fields["ok"] is True


def test_conversation_turn_owns_sequence_and_plans_a_text_fallback() -> None:
    async def assemble(request: ConversationTurnRequest) -> tuple[ArtifactEvidence, ...]:
        return (ArtifactEvidence(source="image", level="ocr_only"),)

    async def run(
        request: ConversationTurnRequest,
        evidence: tuple[ArtifactEvidence, ...],
        trace: TurnTrace,
    ) -> AgentRunResult:
        assert not evidence[0].may_describe_visual_content
        trace.record("tool", name="search_web", ok=True)
        return AgentRunResult(reply_text="我只确认到了图片里的文字。")

    def empty_plan(
        request: ConversationTurnRequest,
        result: AgentRunResult,
    ) -> DeliveryPlan:
        return DeliveryPlan(actions=())

    request = ConversationTurnRequest(
        turn_id="turn-2",
        conversation_id="private:1",
        profile_id="person:1",
        kind="private",
        user_text="这张图写了什么？",
    )
    trace = TurnTrace(request.turn_id)
    outcome = asyncio.run(ConversationTurn(assemble, run, empty_plan).execute(request, trace))

    assert outcome.succeeded
    assert outcome.delivery.actions == (ActionProposal("text", outcome.reply_text),)
    assert [event.stage for event in trace.snapshot()] == [
        "intake", "context_ready", "tool", "agent_finished", "delivery_planned"
    ]


def test_tool_registry_can_replace_a_live_tool_with_a_test_adapter() -> None:
    async def fake_search(arguments: dict[str, object], config: object) -> str:
        assert arguments == {"query": "ATRI"}
        assert config is not None
        return "fixture search result"

    config = SimpleNamespace(web_search_enabled=True)
    registry = ToolRegistry(config, handlers={"search_web": fake_search})

    assert asyncio.run(registry.execute("search_web", {"query": "ATRI"})) == "fixture search result"
    assert "search_web" in registry.names


def test_tool_loop_uses_registry_and_keeps_legacy_message_shape() -> None:
    async def fixture_tool(arguments: dict[str, object], config: object) -> str:
        return f"fixture:{arguments['value']}"

    config = SimpleNamespace(llm_tool_max_calls=2, web_search_enabled=True)
    messages: list[dict[str, object]] = []
    receipts: list[ToolExecutionReceipt] = []
    executed = asyncio.run(
        append_tool_results(
            messages,
            {"content": "", "tool_calls": []},
            [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "fixture", "arguments": '{"value":"ok"}'},
                }
            ],
            config,
            registry=ToolRegistry(config, handlers={"fixture": fixture_tool}),
            receipts=receipts,
        )
    )

    assert executed == 1
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "fixture",
        "content": "fixture:ok",
    }
    assert receipts[0].ok is True


def test_automatic_tool_runner_keeps_legacy_followup_order() -> None:
    payloads: list[dict[str, object]] = []
    messages: list[dict[str, object]] = [{"role": "user", "content": "几点"}]

    async def request_model(payload: dict[str, object]) -> dict[str, object]:
        payloads.append(payload)
        if len(payloads) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "time-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_current_time",
                                        "arguments": '{"timezone":"Asia/Shanghai"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "现在是下午。"}}
            ]
        }

    runner = AutomaticToolRunner(
        SimpleNamespace(llm_tool_max_calls=1),
        request_model,
        lambda text: text,
    )

    result = asyncio.run(
        runner.run(messages, {"model": "test", "messages": messages, "tools": [{"x": 1}]})
    )

    assert result.reply_text == "现在是下午。"
    assert result.tool_receipts[0].name == "get_current_time"
    assert any(item.get("role") == "tool" for item in payloads[1]["messages"])
    assert "tools" not in payloads[1]
