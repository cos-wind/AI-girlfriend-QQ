from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ConversationKind = Literal["private", "group", "proactive"]
DeliveryKind = Literal["text", "record", "image", "face", "call_invite"]
EvidenceLevel = Literal["full_content", "partial", "ocr_only", "metadata_only", "unavailable"]


@dataclass(frozen=True)
class ConversationTurnRequest:
    """The stable interface for one inbound or proactive conversation turn."""

    turn_id: str
    conversation_id: str
    profile_id: str
    kind: ConversationKind
    user_text: str
    nickname: str | None = None
    actor_id: str | None = None
    raw_event: dict[str, Any] | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolReceipt:
    call_id: str
    name: str
    arguments: dict[str, Any]
    ok: bool
    content: str
    elapsed_ms: int


@dataclass(frozen=True)
class ArtifactEvidence:
    """Facts an LLM may use, with the limits that keep it grounded."""

    source: str
    level: EvidenceLevel
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    urls: tuple[str, ...] = ()

    @property
    def may_describe_visual_content(self) -> bool:
        return self.level == "full_content"


@dataclass(frozen=True)
class ActionProposal:
    """A model-proposed action; delivery remains outside the agent loop."""

    kind: DeliveryKind
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryPlan:
    actions: tuple[ActionProposal, ...]
    fallback_text: str = ""


@dataclass(frozen=True)
class AgentRunResult:
    reply_text: str
    tool_receipts: tuple[ToolReceipt, ...] = ()
    proposed_actions: tuple[ActionProposal, ...] = ()
    failure_reason: str = ""


@dataclass(frozen=True)
class TurnOutcome:
    request: ConversationTurnRequest
    reply_text: str
    delivery: DeliveryPlan
    tool_receipts: tuple[ToolReceipt, ...] = ()
    evidence: tuple[ArtifactEvidence, ...] = ()
    failure_reason: str = ""

    @property
    def succeeded(self) -> bool:
        return bool(self.reply_text.strip()) and not self.failure_reason
