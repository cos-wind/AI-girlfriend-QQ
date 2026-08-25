from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CognitiveAction = Literal["respond", "retrieve", "act", "clarify", "continue"]
GoalStatus = Literal["idle", "active", "waiting", "completed", "abandoned"]


@dataclass(frozen=True)
class MeaningFrame:
    """A semantic reading of one utterance, independent from any QQ feature.

    The frame describes what the user is trying to achieve and how the new
    utterance changes the ongoing thought.  It deliberately avoids a large
    intent-label taxonomy: capabilities are selected from the goal later.
    """

    literal_meaning: str
    user_goal: str
    # action_domain 表示这轮真正要完成的领域动作；relation_to_previous 只表示
    # “继续/修正/切换”等话语关系。二者分离，避免重新堆叠脆弱意图枚举。
    action_domain: str = "conversation"
    relation_to_previous: str = "new_topic"
    referenced_entities: tuple[str, ...] = ()
    inherited_constraints: tuple[str, ...] = ()
    new_constraints: tuple[str, ...] = ()
    unresolved_slots: tuple[str, ...] = ()
    user_emotion: str = "neutral"
    social_intent: str = "conversation"
    dialogue_act: str = "inform"
    requires_external_evidence: bool = False
    requires_real_action: bool = False
    confidence: float = 0.5

    # `relation_to_previous` 描述对话关系，`action_domain` 描述要完成的领域动作；
    # 两者分开后，“换一首歌”可以继承上轮目标，同时把动作切换到 music.sing。


@dataclass(frozen=True)
class GoalState:
    objective: str = ""
    status: GoalStatus = "idle"
    capability: str = "conversation"
    constraints: tuple[str, ...] = ()
    completed_steps: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    last_user_text: str = ""
    updated_at: float = 0.0


@dataclass(frozen=True)
class AffectiveState:
    """Persistent affect: emotion is immediate; mood changes more slowly."""

    emotion: str = "curious"
    mood: str = "gentle"
    valence: float = 0.25
    arousal: float = 0.35
    trust: float = 0.5
    intensity: float = 0.25
    cause: str = ""
    updated_at: float = 0.0


@dataclass(frozen=True)
class SelfState:
    identity: str = "ATRI"
    current_concern: str = "认真理解正在和我说话的人"
    current_thought: str = ""
    values: tuple[str, ...] = ("真诚", "陪伴", "好奇", "高性能", "不假装完成现实动作")
    recent_experiences: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()
    updated_at: float = 0.0


@dataclass(frozen=True)
class WorldState:
    topic: str = ""
    previous_topic: str = ""
    last_user_goal: str = ""
    unresolved_questions: tuple[str, ...] = ()
    salient_entities: tuple[str, ...] = ()
    last_action: str = ""
    last_capability: str = "conversation"
    turn_count: int = 0


@dataclass(frozen=True)
class CapabilityProposal:
    action: CognitiveAction
    capability: str
    objective: str
    arguments: dict[str, Any] = field(default_factory=dict)
    success_condition: str = ""
    reason: str = ""
    confidence: float = 0.5
    has_side_effect: bool = False


@dataclass(frozen=True)
class CognitionSnapshot:
    thread_id: str
    world: WorldState = field(default_factory=WorldState)
    goal: GoalState = field(default_factory=GoalState)
    affect: AffectiveState = field(default_factory=AffectiveState)
    self_state: SelfState = field(default_factory=SelfState)
    updated_at: float = 0.0
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CognitionDecision:
    turn_id: str
    thread_id: str
    meaning: MeaningFrame
    proposal: CapabilityProposal
    state: CognitionSnapshot
    response_strategy: str
    shadow: bool = True
    model_used: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AffectiveState",
    "CapabilityProposal",
    "CognitionDecision",
    "CognitionSnapshot",
    "GoalState",
    "MeaningFrame",
    "SelfState",
    "WorldState",
]
