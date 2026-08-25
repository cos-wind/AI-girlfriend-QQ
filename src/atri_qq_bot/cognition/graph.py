from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..application import ArtifactEvidence, ConversationTurnRequest
from .capabilities import CapabilityHub
from .contracts import CapabilityProposal, CognitionSnapshot, MeaningFrame
from .understanding import SemanticUnderstanding


class CognitiveGraphState(TypedDict, total=False):
    request: ConversationTurnRequest
    previous: CognitionSnapshot
    evidence: tuple[ArtifactEvidence, ...]
    profile: dict[str, Any]
    meaning: MeaningFrame
    proposal: CapabilityProposal


def build_cognitive_graph(
    understanding: SemanticUnderstanding,
    capabilities: CapabilityHub,
) -> Any:
    """Build the stable understand -> decide graph used by live and replay modes.

    Execution and observation nodes are intentionally introduced capability by
    capability.  In shadow mode, side effects stop at a proposal, preserving
    the exact same state shape that active execution will later consume.
    """

    # 图节点保持无副作用：节点只读输入并返回局部状态，状态持久化由 kernel 统一完成。
    def understand_node(state: CognitiveGraphState) -> dict[str, Any]:
        meaning = understanding.understand(
            state["request"],
            state["previous"],
            profile=state.get("profile") or {},
        )
        return {"meaning": meaning}

    def decide_node(state: CognitiveGraphState) -> dict[str, Any]:
        return {
            "proposal": capabilities.resolve(state["meaning"], state["previous"])
        }

    # 当前图只有两个节点，但保留 LangGraph 的显式拓扑，后续增加规划/反思节点时
    # 不需要把逻辑重新塞回一个巨型函数。
    builder = StateGraph(CognitiveGraphState)
    builder.add_node("understand", understand_node)
    builder.add_node("decide", decide_node)
    builder.add_edge(START, "understand")
    builder.add_edge("understand", "decide")
    builder.add_edge("decide", END)
    return builder.compile()


__all__ = ["CognitiveGraphState", "build_cognitive_graph"]
