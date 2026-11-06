"""应用层的数据契约。

这些 dataclass 是适配层、Agent 和交付层之间的稳定边界。它们不依赖 QQ、
HTTP 或具体模型，因此可以用纯单元测试验证数据流和失败条件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ConversationKind = Literal["private", "group", "proactive"]
DeliveryKind = Literal["text", "record", "image", "face", "call_invite"]
EvidenceLevel = Literal["full_content", "partial", "ocr_only", "metadata_only", "unavailable"]


@dataclass(frozen=True)
class ConversationTurnRequest:
    """一次对话轮次的规范输入。

    `conversation_id` 表示上下文容器，`profile_id` 表示应该写入的用户档案；
    群聊因此可以共享场景上下文，同时把个人特征写入发言者自己的档案。
    """

    turn_id: str
    conversation_id: str
    profile_id: str
    kind: ConversationKind
    user_text: str
    nickname: str | None = None
    actor_id: str | None = None
    quoted_text: str = ""
    reply_focus_source: str = ""
    reply_focus_text: str = ""
    addressed_to_bot: bool = True
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
    """模型可以使用的证据，以及限制模型越界推断的证据等级。"""

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
        # 空回复即使没有抛异常也属于失败；这样发送层不会静默丢消息。
        return bool(self.reply_text.strip()) and not self.failure_reason
