"""认知子系统的稳定公共入口。

较重的 LangGraph 依赖按需导入。这样即使开发者尚未安装认知扩展，原有
OneBot/回复链路也不会仅因导入模块而中断。
"""

from importlib import import_module
from typing import Any

from .contracts import (
    AffectiveState,
    CapabilityProposal,
    CognitionDecision,
    CognitionSnapshot,
    GoalState,
    MeaningFrame,
    SelfState,
    WorldState,
)
from .store import CognitionStateStore

__all__ = [
    "AffectiveState",
    "CapabilityContract",
    "CapabilityHub",
    "CapabilityProposal",
    "CognitionDecision",
    "CognitionKernel",
    "CognitionSnapshot",
    "CognitionStateStore",
    "CognitionShadowRunner",
    "GoalState",
    "MeaningFrame",
    "SelfState",
    "SemanticUnderstanding",
    "WorldState",
    "evidence_from_tool_context",
]


_LAZY_EXPORTS = {
    "CapabilityContract": (".capabilities", "CapabilityContract"),
    "CapabilityHub": (".capabilities", "CapabilityHub"),
    "CognitionKernel": (".kernel", "CognitionKernel"),
    "CognitionShadowRunner": (".shadow", "CognitionShadowRunner"),
    "SemanticUnderstanding": (".understanding", "SemanticUnderstanding"),
    "evidence_from_tool_context": (".shadow", "evidence_from_tool_context"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
