from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..application import ArtifactEvidence, ConversationTurnRequest, TurnTrace
from .capabilities import CapabilityHub
from .contracts import (
    AffectiveState,
    CognitionDecision,
    CognitionSnapshot,
    GoalState,
    SelfState,
    WorldState,
)
from .graph import build_cognitive_graph
from .store import CognitionStateStore
from .understanding import SemanticUnderstanding


LOGGER = logging.getLogger("atri.cognition")


class CognitionKernel:
    """ATRI's persistent cognition loop in safe shadow mode.

    The kernel owns semantic continuity, affect, self continuity and capability
    proposals.  It does not send QQ messages or execute side-effecting tools.
    This is the migration seam: once a capability has replay coverage, its
    proposal can be connected to an adapter without changing cognition.
    """

    def __init__(
        self,
        store: CognitionStateStore,
        *,
        shadow_log: Path | None = None,
        understanding: SemanticUnderstanding | None = None,
        capabilities: CapabilityHub | None = None,
    ) -> None:
        self.store = store
        self.understanding = understanding or SemanticUnderstanding()
        self.capabilities = capabilities or CapabilityHub()
        self.graph = build_cognitive_graph(self.understanding, self.capabilities)
        self.shadow_log = Path(shadow_log) if shadow_log else None

    async def deliberate(
        self,
        request: ConversationTurnRequest,
        evidence: tuple[ArtifactEvidence, ...] = (),
        *,
        profile: dict[str, Any] | None = None,
        trace: TurnTrace | None = None,
    ) -> CognitionDecision:
        import asyncio

        return await asyncio.to_thread(
            self._deliberate_sync,
            request,
            evidence,
            profile,
            trace,
        )

    def _deliberate_sync(
        self,
        request: ConversationTurnRequest,
        evidence: tuple[ArtifactEvidence, ...] = (),
        profile: dict[str, Any] | None = None,
        trace: TurnTrace | None = None,
    ) -> CognitionDecision:
        # 认知内核只产生“理解、状态变化和能力提案”，不直接发 QQ 消息或执行副作用。
        # 因此可以先以 shadow 模式回放和验证，稳定后再接入生产回复链路。
        turn_trace = trace or TurnTrace(request.turn_id)
        thread_id = _thread_id(request)
        state = self.store.load(thread_id)
        turn_trace.record("cognition_loaded", thread_id=thread_id, turn_count=state.world.turn_count)

        # LangGraph 通过显式状态字段连接理解节点和能力提案节点，便于测试和回放。
        graph_state = self.graph.invoke(
            {
                "request": request,
                "previous": state,
                "evidence": evidence,
                "profile": profile or {},
            },
            {"configurable": {"thread_id": thread_id}},
        )
        meaning = graph_state["meaning"]
        turn_trace.record(
            "meaning_understood",
            relation=meaning.relation_to_previous,
            action_domain=meaning.action_domain,
            external=meaning.requires_external_evidence,
            action=meaning.requires_real_action,
        )
        proposal = graph_state["proposal"]
        turn_trace.record(
            "capability_proposed",
            capability=proposal.capability,
            action=proposal.action,
            side_effect=proposal.has_side_effect,
        )
        updated = _evolve_state(state, request, meaning, proposal, evidence)
        self.store.save(updated)
        experience = _experience_summary(request, meaning, proposal)
        self.store.add_experience(
            thread_id,
            request.turn_id,
            experience,
            importance=_experience_importance(meaning, proposal),
        )
        strategy = _response_strategy(updated, meaning, proposal, evidence)
        decision = CognitionDecision(
            turn_id=request.turn_id,
            thread_id=thread_id,
            meaning=meaning,
            proposal=proposal,
            state=updated,
            response_strategy=strategy,
            shadow=True,
        )
        self._log_shadow(decision, trace=turn_trace)
        return decision

    def status(self) -> dict[str, Any]:
        payload = self.store.status()
        payload.update(
            {
                "enabled": True,
                "mode": "shadow",
                "capabilities": [item.name for item in self.capabilities.contracts],
            }
        )
        return payload

    def _log_shadow(self, decision: CognitionDecision, *, trace: TurnTrace) -> None:
        if self.shadow_log is None:
            return
        event = decision.to_dict()
        event["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        event["trace"] = [
            {"stage": item.stage, "elapsed_ms": item.elapsed_ms, "fields": item.fields}
            for item in trace.snapshot()
        ]
        try:
            self.shadow_log.parent.mkdir(parents=True, exist_ok=True)
            with self.shadow_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError as exc:
            LOGGER.warning("认知影子日志写入失败：%s", exc)


def _thread_id(request: ConversationTurnRequest) -> str:
    # In a group the personal thought thread follows the actor.  The public
    # group scene remains available through request.conversation_id.
    return request.profile_id or request.conversation_id


def _evolve_state(
    state: CognitionSnapshot,
    request: ConversationTurnRequest,
    meaning: Any,
    proposal: Any,
    evidence: tuple[ArtifactEvidence, ...],
) -> CognitionSnapshot:
    now = time.time()
    topic = _topic_from_goal(meaning.user_goal)
    world = WorldState(
        topic=topic or state.world.topic,
        previous_topic=state.world.topic if topic and topic != state.world.topic else state.world.previous_topic,
        last_user_goal=meaning.user_goal,
        unresolved_questions=tuple(meaning.unresolved_slots),
        salient_entities=tuple(dict.fromkeys(state.world.salient_entities + meaning.referenced_entities))[-12:],
        last_action=proposal.action,
        last_capability=proposal.capability,
        turn_count=state.world.turn_count + 1,
    )
    goal_status = "waiting" if proposal.action == "clarify" else "active"
    if proposal.action == "respond" and not meaning.requires_real_action:
        goal_status = "completed"
    constraints = tuple(
        dict.fromkeys(meaning.inherited_constraints + meaning.new_constraints)
    )[-12:]
    goal = GoalState(
        objective=meaning.user_goal,
        status=goal_status,
        capability=proposal.capability,
        constraints=constraints,
        completed_steps=state.goal.completed_steps if meaning.relation_to_previous != "new_topic" else (),
        missing_information=tuple(meaning.unresolved_slots),
        last_user_text=request.user_text[:300],
        updated_at=now,
    )
    affect = _evolve_affect(state.affect, meaning.user_emotion, meaning.social_intent, now)
    experience = _compact_experience(request, proposal)
    experiences = tuple(item for item in state.self_state.recent_experiences if item != experience)
    if experience:
        experiences = (experiences + (experience,))[-8:]
    thought = _current_thought(meaning, proposal, evidence)
    self_state = SelfState(
        identity="ATRI，高性能仿生人少女；保有原作个性、价值观与经历连续性",
        current_concern=_current_concern(meaning, proposal),
        current_thought=thought,
        values=state.self_state.values,
        recent_experiences=experiences,
        commitments=state.self_state.commitments[-8:],
        updated_at=now,
    )
    return CognitionSnapshot(
        thread_id=state.thread_id,
        world=world,
        goal=goal,
        affect=affect,
        self_state=self_state,
        updated_at=now,
        version=max(1, state.version),
    )


def _evolve_affect(
    old: AffectiveState,
    user_emotion: str,
    social_intent: str,
    now: float,
) -> AffectiveState:
    targets = {
        "happy": ("happy", 0.72, 0.58),
        "sad": ("concerned", -0.18, 0.36),
        "angry": ("hurt", -0.24, 0.62),
        "anxious": ("concerned", -0.08, 0.48),
        "neutral": ("curious", 0.22, 0.32),
    }
    emotion, target_valence, target_arousal = targets.get(user_emotion, targets["neutral"])
    valence = _blend(old.valence, target_valence, 0.42)
    arousal = _blend(old.arousal, target_arousal, 0.38)
    mood = _mood_label(valence, arousal)
    trust_delta = 0.015 if social_intent in {"relationship", "seek_support"} else 0.0
    return AffectiveState(
        emotion=emotion,
        mood=mood,
        valence=valence,
        arousal=arousal,
        trust=max(0.0, min(1.0, old.trust + trust_delta)),
        intensity=max(0.1, min(1.0, abs(target_valence - old.valence) + target_arousal * 0.5)),
        cause=f"用户表现为 {user_emotion}，互动意图为 {social_intent}",
        updated_at=now,
    )


def _blend(previous: float, target: float, weight: float) -> float:
    return round(previous * (1.0 - weight) + target * weight, 4)


def _mood_label(valence: float, arousal: float) -> str:
    if valence < -0.2:
        return "low" if arousal < 0.5 else "upset"
    if valence > 0.48:
        return "bright" if arousal > 0.45 else "content"
    return "gentle" if arousal < 0.5 else "lively"


def _topic_from_goal(goal: str) -> str:
    compact = re.sub(r"[，。！？!?；;：:\s]+", " ", str(goal or "")).strip()
    return compact[:80]


def _current_thought(meaning: Any, proposal: Any, evidence: tuple[ArtifactEvidence, ...]) -> str:
    evidence_note = f"，已有 {len(evidence)} 份本轮证据" if evidence else ""
    return (
        f"用户的当前目标是“{meaning.user_goal}”；它与上一轮的关系是"
        f"{meaning.relation_to_previous}。下一步应通过 {proposal.capability} "
        f"完成，不能把提案假装成已经执行{evidence_note}。"
    )[:500]


def _current_concern(meaning: Any, proposal: Any) -> str:
    if meaning.social_intent == "repair_understanding":
        return "承认并修正刚才的理解，直接完成用户最新目标"
    if meaning.social_intent == "seek_support":
        return "先接住用户的情绪，再给具体而不过度承诺的回应"
    if proposal.has_side_effect:
        return "准确理解用户要执行的真实功能，并等待成功回执"
    return "自然承接当前话题，不重复询问已经知道的信息"


def _compact_experience(request: ConversationTurnRequest, proposal: Any) -> str:
    text = " ".join(str(request.user_text or "").split())[:80]
    return f"和{request.nickname or '这位用户'}聊到“{text}”，准备使用 {proposal.capability}"


def _experience_summary(request: ConversationTurnRequest, meaning: Any, proposal: Any) -> str:
    return (
        f"用户说“{' '.join(request.user_text.split())[:120]}”；"
        f"理解为{meaning.relation_to_previous}，目标是“{meaning.user_goal[:140]}”，"
        f"下一步能力为 {proposal.capability}。"
    )


def _experience_importance(meaning: Any, proposal: Any) -> float:
    score = 0.35
    if meaning.relation_to_previous in {"correct", "modify"}:
        score += 0.2
    if meaning.social_intent in {"relationship", "seek_support"}:
        score += 0.2
    if proposal.has_side_effect:
        score += 0.1
    return min(1.0, score)


def _response_strategy(
    state: CognitionSnapshot,
    meaning: Any,
    proposal: Any,
    evidence: tuple[ArtifactEvidence, ...],
) -> str:
    parts = [
        "先回应当前具体目标",
        f"保持 {state.affect.mood}/{state.affect.emotion} 的自然语气",
    ]
    if meaning.relation_to_previous in {"correct", "modify"}:
        parts.append("明确采用用户最新修正，废弃冲突的旧理解")
    if proposal.action == "clarify":
        parts.append("只询问一个无法从上下文推断的必要信息")
    elif proposal.has_side_effect:
        parts.append("在真实执行成功前不声称已经完成")
    elif proposal.capability == "research.web":
        parts.append("只根据实际检索证据下结论")
    if evidence:
        parts.append("不超出本轮证据可见范围")
    parts.append("不重复上一轮已经回答或询问过的内容")
    return "；".join(parts)


__all__ = ["CognitionKernel"]
