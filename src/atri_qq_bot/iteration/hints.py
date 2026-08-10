from __future__ import annotations

from .decision import IterationDecision
from ..prompting import load_prompt


def iteration_prompt_hint(decision: IterationDecision | None) -> str:
    if decision is None:
        return load_prompt("iteration")
    return f"自迭代纠错判断：{decision.action}。原因：{decision.reason}。处理方式：{decision.response_hint}"
