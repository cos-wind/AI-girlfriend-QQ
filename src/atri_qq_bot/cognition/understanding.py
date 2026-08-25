from __future__ import annotations

import re
from typing import Any

from ..application import ConversationTurnRequest
from .contracts import CognitionSnapshot, MeaningFrame


_CORRECTION = ("不是", "不对", "我说的是", "你理解错", "不是这个", "搞错了")
_CONTINUATION = ("继续", "然后呢", "接着", "下一段", "下一首", "再来", "还有呢")
_MODIFICATION = ("换一个", "换一首", "别这个", "不要这个", "改成", "算了", "重来")
_EXTERNAL = (
    "最新", "今天", "新闻", "现在", "目前", "刚刚", "价格", "版本", "政策",
    "官方", "研究现状", "有没有定论", "世界观", "设定", "资料", "查一下", "搜一下",
)
_ACTION = ("唱", "发语音", "查", "搜索", "打开", "发送", "读", "分析图片", "看看视频")


class SemanticUnderstanding:
    """Fast semantic baseline used before the optional LLM understanding adapter.

    It resolves conversational relations and inherited goals deterministically.
    A model adapter may enrich entities and implications later, but failure of
    that adapter can never erase the ongoing goal.
    """

    def understand(
        self,
        request: ConversationTurnRequest,
        state: CognitionSnapshot,
        *,
        profile: dict[str, Any] | None = None,
    ) -> MeaningFrame:
        # 先用确定性规则恢复“这句话和上一句是什么关系”，再决定目标和能力领域。
        # 即使可选的 LLM 理解器超时，继续/纠正/换一个等上下文也不会丢失。
        text = " ".join(str(request.user_text or "").split())
        relation = _relation(text, state)
        inherited_goal = state.goal.objective if state.goal.status in {"active", "waiting"} else ""
        goal = _goal_text(text, inherited_goal, relation)
        user_emotion = _user_emotion(text)
        external = any(term in text for term in _EXTERNAL)
        real_action = any(term in text for term in _ACTION)
        entities = _entities(text)
        action_domain = _action_domain(text, state, relation, external)
        if action_domain in {"music.sing", "voice.speak"}:
            real_action = True
        inherited_constraints = state.goal.constraints if relation in {"continue", "modify", "correct"} else ()
        new_constraints: list[str] = []
        if any(term in text for term in ("换一个", "换一首", "别这个", "不要这个")):
            new_constraints.append("排除上一轮使用的对象")
        if "随便" in text or "你挑" in text:
            new_constraints.append("允许亚托莉自主选择")
        if request.quoted_text:
            new_constraints.append("优先回应用户明确引用的消息")
        literal = text or "用户发来了一条没有附加文字的消息"
        confidence = 0.86 if relation != "new_topic" or real_action else 0.68
        return MeaningFrame(
            literal_meaning=literal,
            user_goal=goal,
            action_domain=action_domain,
            relation_to_previous=relation,
            referenced_entities=entities,
            inherited_constraints=tuple(inherited_constraints),
            new_constraints=tuple(new_constraints),
            unresolved_slots=_unresolved_slots(text, goal),
            user_emotion=user_emotion,
            social_intent=_social_intent(text, user_emotion),
            dialogue_act=_dialogue_act(text, relation),
            requires_external_evidence=external,
            requires_real_action=real_action,
            confidence=confidence,
        )


def _relation(text: str, state: CognitionSnapshot) -> str:
    if any(term in text for term in _CORRECTION):
        return "correct"
    if any(term in text for term in _MODIFICATION):
        return "modify"
    if any(term in text for term in _CONTINUATION):
        return "continue"
    if len(text) <= 12 and state.goal.status in {"active", "waiting"} and _looks_elliptical(text):
        return "continue"
    return "new_topic"


def _action_domain(
    text: str,
    state: CognitionSnapshot,
    relation: str,
    external: bool,
) -> str:
    """用少量能力领域替代不断膨胀的业务意图标签。"""

    if any(term in text for term in ("唱", "歌曲", "来一首", "换一首", "下一首")):
        return "music.sing"
    if any(term in text for term in ("发语音", "语音说", "读出来", "念给我", "用日语说")):
        return "voice.speak"
    if any(term in text for term in ("图片", "图里", "表情包", "视频", "画面", "这是谁")):
        return "vision.understand"
    if any(term in text for term in ("天气", "下雨", "温度", "气温", "降温")):
        return "weather.lookup"
    if any(term in text for term in ("文档", "文件", "PDF", "表格", "总结这个")):
        return "document.read"
    if relation in {"continue", "modify", "correct"} and state.goal.capability != "conversation":
        return state.goal.capability
    if external:
        return "research.web"
    return "conversation"


def _goal_text(text: str, inherited: str, relation: str) -> str:
    if relation == "continue" and inherited:
        return f"继续完成：{inherited}；用户补充：{text}"
    if relation in {"modify", "correct"} and inherited:
        return f"修正当前目标：{inherited}；以用户最新要求“{text}”为准"
    return text


def _looks_elliptical(text: str) -> bool:
    return bool(text) and not re.search(r"[。！？!?]$", text) and len(text) <= 12


def _entities(text: str) -> tuple[str, ...]:
    quoted = re.findall(r"[《\"“]([^》\"”]{1,40})[》\"”]", text)
    ascii_names = re.findall(r"\b[A-Za-z][A-Za-z0-9_.+-]{2,32}\b", text)
    return tuple(dict.fromkeys(quoted + ascii_names))[:8]


def _unresolved_slots(text: str, goal: str) -> tuple[str, ...]:
    if any(term in goal for term in ("天气", "气温", "下雨", "降温")):
        if not re.search(r"(?:在|查|看)([\u4e00-\u9fff]{2,8})(?:的)?(?:天气|气温)", text):
            return ("location",)
    return ()


def _user_emotion(text: str) -> str:
    if any(term in text for term in ("难受", "伤心", "想哭", "孤独", "委屈")):
        return "sad"
    if any(term in text for term in ("气死", "烦死", "离谱", "服了", "生气")):
        return "angry"
    if any(term in text for term in ("哈哈", "开心", "太好了", "喜欢", "可爱")):
        return "happy"
    if any(term in text for term in ("怕", "担心", "焦虑", "怎么办")):
        return "anxious"
    return "neutral"


def _social_intent(text: str, emotion: str) -> str:
    if emotion in {"sad", "anxious"}:
        return "seek_support"
    if any(term in text for term in _CORRECTION):
        return "repair_understanding"
    if any(term in text for term in ("喜欢你", "抱抱", "想你", "陪我")):
        return "relationship"
    return "conversation"


def _dialogue_act(text: str, relation: str) -> str:
    if relation == "correct":
        return "correct"
    if relation == "modify":
        return "modify"
    if relation == "continue":
        return "continue"
    if any(term in text for term in ("为什么", "怎么", "什么", "吗", "？", "?")):
        return "ask"
    if any(term in text for term in _ACTION):
        return "request_action"
    return "inform"


__all__ = ["SemanticUnderstanding"]
