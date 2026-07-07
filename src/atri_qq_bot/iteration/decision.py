from __future__ import annotations

from dataclasses import dataclass

from .patterns import QUALITY_CORRECTION_WORDS, REFUSAL_CORRECTION_WORDS, VAGUE_CORRECTION_WORDS


@dataclass(frozen=True)
class IterationDecision:
    action: str
    reason: str
    response_hint: str

    @property
    def accepted(self) -> bool:
        return self.action == "accept"


def judge_correction(text: str) -> IterationDecision | None:
    if not _looks_like_correction(text):
        return None

    if any(word in text for word in REFUSAL_CORRECTION_WORDS):
        return IterationDecision(
            action="reject",
            reason="用户要求会破坏人设、边界或防刷屏规则",
            response_hint=(
                "不要无条件认错。用亚托莉的口吻合理拒绝：边界、防刷屏、人设不能改坏；"
                "但可以承诺在不越界的前提下优化表达。"
            ),
        )

    if any(word in text for word in QUALITY_CORRECTION_WORDS):
        return IterationDecision(
            action="accept",
            reason="用户指出了具体回复质量问题",
            response_hint=(
                "直接认错并修正，不要反问哪里错；说明下一轮会先抓当前重点、减少套话、避免重复。"
            ),
        )

    if any(word in text for word in VAGUE_CORRECTION_WORDS):
        return IterationDecision(
            action="pushback",
            reason="用户纠错较笼统，需要先承认可可能误解，但不能盲目改坏",
            response_hint=(
                "认一半，傲娇地说明不会盲改；先按当前能判断的方向重答，最多问一个具体点。"
            ),
        )

    return IterationDecision(
        action="accept",
        reason="用户表达了修正意图",
        response_hint="保持短句，先承认并给出具体改法。",
    )


def _looks_like_correction(text: str) -> bool:
    lowered = text.lower()
    return (
        any(word in text for word in QUALITY_CORRECTION_WORDS + VAGUE_CORRECTION_WORDS)
        or any(word in text for word in REFUSAL_CORRECTION_WORDS)
        or "thinking" in lowered
        or "<think>" in lowered
        or ("不要" in text and any(word in text for word in ("重复", "思考", "分析", "展现", "接住", "模板")))
        or ("改" in text and any(word in text for word in ("回复", "逻辑", "人设", "语气", "提示词")))
        or ("优化" in text and any(word in text for word in ("回复", "逻辑", "人设", "语气", "提示词", "对话")))
        or ("禁用" in text and any(word in text for word in ("比喻", "意象", "梗", "话术")))
    )
