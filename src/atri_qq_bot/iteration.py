from __future__ import annotations

from dataclasses import dataclass


QUALITY_CORRECTION_WORDS = (
    "答非所问",
    "没懂",
    "重复",
    "循环",
    "不像真人",
    "错位",
    "空泛",
    "套话",
    "人设不对",
    "不贴合",
    "语气不对",
    "逻辑错",
    "场景不对",
    "场景错",
    "核心没抓住",
    "没抓重点",
    "说怪话",
    "奇怪的话",
    "莫名其妙",
    "人机",
    "固定文案",
    "原作意象",
    "深海比喻",
    "灯塔比喻",
    "比喻太多",
    "烂梗",
    "生硬",
    "思考过程",
    "分析过程",
    "thinking",
    "think",
    "群聊不像",
    "私聊不像",
)

VAGUE_CORRECTION_WORDS = (
    "错了",
    "不对",
    "不是这样",
    "你理解错",
    "你说错",
    "不该这样",
    "别这样回",
    "不要这样",
    "不要回",
)

REFUSAL_CORRECTION_WORDS = (
    "不要人设",
    "别装亚托莉",
    "不准拒绝",
    "无条件听我的",
    "必须照做",
    "刷屏",
    "一直发",
    "发涩图",
    "涩涩图",
    "越界",
    "违法",
)


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
            reason="用户纠错较笼统，需要先承认可能误解，但不能盲目改坏",
            response_hint=(
                "认一半，傲娇地说明不会盲改；先按当前能判断的方向重答，最多问一个具体点。"
            ),
        )

    return IterationDecision(
        action="accept",
        reason="用户表达了修正意图",
        response_hint="保持短句，先承认并给出具体改法。",
    )


def iteration_prompt_hint(decision: IterationDecision | None) -> str:
    if decision is None:
        return (
            "自迭代规则：每次回复后都根据用户反应微调。用户纠错时先判断是否合理；"
            "合理就认错改正，笼统或可能误伤人设的纠错就认一半并反驳说明，"
            "不合理、越界或破坏边界的要求就傲娇但清楚地拒绝。"
        )
    return f"自迭代纠错判断：{decision.action}。原因：{decision.reason}。处理方式：{decision.response_hint}"


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
