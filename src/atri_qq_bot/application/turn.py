from __future__ import annotations

from typing import Protocol

from .contracts import (
    ActionProposal,
    AgentRunResult,
    ArtifactEvidence,
    ConversationTurnRequest,
    DeliveryPlan,
    TurnOutcome,
)
from .trace import TurnTrace


class ContextAssembler(Protocol):
    async def __call__(
        self,
        request: ConversationTurnRequest,
    ) -> tuple[ArtifactEvidence, ...]: ...


class AgentRunner(Protocol):
    async def __call__(
        self,
        request: ConversationTurnRequest,
        evidence: tuple[ArtifactEvidence, ...],
        trace: TurnTrace,
    ) -> AgentRunResult: ...


class DeliveryPlanner(Protocol):
    def __call__(
        self,
        request: ConversationTurnRequest,
        result: AgentRunResult,
    ) -> DeliveryPlan: ...


class ConversationTurn:
    """Owns one complete turn's ordering without knowing any edge adapter.

    The module accepts only three narrow collaborators. This keeps OneBot,
    model-provider, multimodal and delivery implementations replaceable while
    making the sequence and failure invariants testable in one place.
    """

    def __init__(
        self,
        context_assembler: ContextAssembler,
        agent_runner: AgentRunner,
        delivery_planner: DeliveryPlanner,
    ) -> None:
        self._context_assembler = context_assembler
        self._agent_runner = agent_runner
        self._delivery_planner = delivery_planner

    async def execute(
        self,
        request: ConversationTurnRequest,
        trace: TurnTrace | None = None,
    ) -> TurnOutcome:
        turn_trace = trace or TurnTrace(request.turn_id)
        turn_trace.record(
            "intake",
            conversation_id=request.conversation_id,
            kind=request.kind,
        )
        evidence = await self._context_assembler(request)
        turn_trace.record(
            "context_ready",
            evidence_count=len(evidence),
            visual_evidence=sum(item.may_describe_visual_content for item in evidence),
        )
        result = await self._agent_runner(request, evidence, turn_trace)
        turn_trace.record(
            "agent_finished",
            tool_calls=len(result.tool_receipts),
            proposed_actions=len(result.proposed_actions),
            failed=bool(result.failure_reason),
        )
        if result.failure_reason or not result.reply_text.strip():
            reason = result.failure_reason or "agent returned an empty reply"
            turn_trace.record("failed", reason=reason)
            return TurnOutcome(
                request=request,
                reply_text="",
                delivery=DeliveryPlan(actions=()),
                tool_receipts=result.tool_receipts,
                evidence=evidence,
                failure_reason=reason,
            )

        delivery = self._delivery_planner(request, result)
        if not delivery.actions:
            delivery = DeliveryPlan(
                actions=(ActionProposal("text", result.reply_text),),
                fallback_text=result.reply_text,
            )
        turn_trace.record("delivery_planned", actions=len(delivery.actions))
        return TurnOutcome(
            request=request,
            reply_text=result.reply_text,
            delivery=delivery,
            tool_receipts=result.tool_receipts,
            evidence=evidence,
        )
