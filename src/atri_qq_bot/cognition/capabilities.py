from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .contracts import CapabilityProposal, CognitionSnapshot, MeaningFrame


@dataclass(frozen=True)
class CapabilityContract:
    """What a capability can achieve, without exposing implementation details."""

    name: str
    description: str
    read_only: bool
    has_side_effect: bool
    required_fields: tuple[str, ...]
    success_condition: str
    can_handle: Callable[[MeaningFrame, CognitionSnapshot], bool]


class CapabilityHub:
    """Select high-level abilities from semantic goals rather than keywords alone.

    Shadow mode only proposes a capability.  Existing OneBot adapters remain the
    sole owners of real side effects until replay coverage permits migration.
    """

    def __init__(self) -> None:
        self._contracts = _default_contracts()

    def resolve(
        self,
        meaning: MeaningFrame,
        state: CognitionSnapshot,
    ) -> CapabilityProposal:
        # 先尝试理解器给出的 action_domain，再按契约顺序兜底；能力契约只描述
        # “能做什么、需要哪些字段、什么算成功”，不暴露具体 HTTP/QQ 实现。
        exact = next(
            (contract for contract in self._contracts if contract.name == meaning.action_domain),
            None,
        )
        candidates = ([exact] if exact is not None else []) + [
            contract for contract in self._contracts if contract is not exact
        ]
        for contract in candidates:
            if not contract.can_handle(meaning, state):
                continue
            action = "retrieve" if contract.read_only and contract.name != "conversation" else "act"
            if contract.name == "conversation":
                action = "respond"
            missing = tuple(
                field for field in contract.required_fields if field in meaning.unresolved_slots
            )
            if missing:
                action = "clarify"
            return CapabilityProposal(
                action=action,
                capability=contract.name,
                objective=meaning.user_goal or meaning.literal_meaning,
                arguments={
                    "entities": list(meaning.referenced_entities),
                    "constraints": list(
                        dict.fromkeys(
                            meaning.inherited_constraints + meaning.new_constraints
                        )
                    ),
                    "missing": list(missing),
                },
                success_condition=contract.success_condition,
                reason=f"目标与能力契约 {contract.name} 匹配",
                confidence=meaning.confidence,
                has_side_effect=contract.has_side_effect,
            )
        return CapabilityProposal(
            action="respond",
            capability="conversation",
            objective=meaning.user_goal or meaning.literal_meaning,
            success_condition="用户当前话语被直接、完整、自然地回应",
            reason="不需要现实动作或外部证据",
            confidence=meaning.confidence,
        )

    @property
    def contracts(self) -> tuple[CapabilityContract, ...]:
        return tuple(self._contracts)


def _default_contracts() -> list[CapabilityContract]:
    return [
        CapabilityContract(
            name="music.sing",
            description="明确点歌后展示 data/music 歌单，用户确认歌名或序号后发送整首 QQ 语音",
            read_only=False,
            has_side_effect=True,
            required_fields=(),
            success_condition="用户从成品歌单确认歌曲，并收到该整首歌曲的 QQ 发送成功回执",
            can_handle=lambda meaning, state: _goal_contains(
                meaning, "唱", "歌", "换一首", "下一首", "来一首", "这首"
            )
            or meaning.action_domain == "music.sing"
            or state.goal.capability == "music.sing"
            and meaning.relation_to_previous in {"continue", "modify", "correct"},
        ),
        CapabilityContract(
            name="voice.speak",
            description="使用语音合成发送真实 QQ 语音",
            read_only=False,
            has_side_effect=True,
            required_fields=(),
            success_condition="语音合成成功且 QQ 发送返回成功回执",
            can_handle=lambda meaning, state: _goal_contains(
                meaning, "发语音", "语音说", "用日语说", "读出来", "念给我"
            ) or meaning.action_domain == "voice.speak",
        ),
        CapabilityContract(
            name="vision.understand",
            description="结合本轮 OCR 与视觉证据理解图片、表情包或视频画面",
            read_only=True,
            has_side_effect=False,
            required_fields=(),
            success_condition="结论仅使用本轮可见证据，并明确不确定部分",
            can_handle=lambda meaning, state: _goal_contains(
                meaning, "图片", "图里", "表情包", "视频", "画面", "这是谁"
            ) or meaning.action_domain == "vision.understand",
        ),
        CapabilityContract(
            name="weather.lookup",
            description="查询明确地点的实时天气和预报",
            read_only=True,
            has_side_effect=False,
            required_fields=("location",),
            success_condition="地点经过确认且天气数据具有明确时间",
            can_handle=lambda meaning, state: _goal_contains(
                meaning, "天气", "下雨", "温度", "气温", "降温"
            ) or meaning.action_domain == "weather.lookup",
        ),
        CapabilityContract(
            name="research.web",
            description="针对需要外部证据且没有专用数据能力的问题进行检索、阅读和来源核验",
            read_only=True,
            has_side_effect=False,
            required_fields=(),
            success_condition="关键结论得到强相关来源支持，或诚实说明没有可靠结论",
            can_handle=lambda meaning, state: meaning.action_domain == "research.web"
            or meaning.requires_external_evidence,
        ),
        CapabilityContract(
            name="document.read",
            description="读取本轮文档或文件的实际可见内容",
            read_only=True,
            has_side_effect=False,
            required_fields=(),
            success_condition="回答范围不超过实际读取到的文档证据",
            can_handle=lambda meaning, state: _goal_contains(
                meaning, "文档", "文件", "PDF", "表格", "总结这个"
            ) or meaning.action_domain == "document.read",
        ),
        CapabilityContract(
            name="conversation",
            description="自然对话、情感回应、观点表达和关系延续",
            read_only=True,
            has_side_effect=False,
            required_fields=(),
            success_condition="用户当前话语得到完整而不重复的回应",
            can_handle=lambda meaning, state: meaning.action_domain == "conversation",
        ),
    ]


def _goal_contains(meaning: MeaningFrame, *terms: str) -> bool:
    text = f"{meaning.literal_meaning} {meaning.user_goal}".casefold()
    return any(term.casefold() in text for term in terms)


__all__ = ["CapabilityContract", "CapabilityHub"]
