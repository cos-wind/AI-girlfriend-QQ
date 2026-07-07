from __future__ import annotations

from .decision import IterationDecision


def iteration_prompt_hint(decision: IterationDecision | None) -> str:
    if decision is None:
        return (
            "自迭代规则：每次回复后都根据用户反应微调。用户纠错时先判断是否合理；"
            "合理就认错改正，笼统或可能误伤人设的纠错就认一半并反驳说明，"
            "不合理、越界或破坏边界的要求就傲娇但清楚地拒绝。"
        )
    return f"自迭代纠错判断：{decision.action}。原因：{decision.reason}。处理方式：{decision.response_hint}"
