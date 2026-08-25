from __future__ import annotations

from .contracts import CognitionSnapshot
from .store import CognitionStateStore


_MOOD_LABELS = {
    "gentle": "平静而温柔",
    "lively": "精神很好、想多聊一点",
    "content": "安心而满足",
    "bright": "明快开心",
    "low": "有些低落，但仍愿意认真交流",
    "upset": "有些受伤或不安",
}

_EMOTION_LABELS = {
    "curious": "好奇",
    "happy": "开心",
    "concerned": "担心",
    "hurt": "有些委屈",
}


def render_cognition_context(
    store: CognitionStateStore | None,
    thread_id: str,
) -> str:
    """把可公开使用的持续状态压缩为提示词，不暴露隐藏推理过程。"""

    if store is None or not thread_id:
        return ""
    try:
        snapshot = store.load(thread_id)
    except Exception:
        return ""
    if snapshot.world.turn_count <= 0:
        return ""
    return _render_snapshot(snapshot)


def _render_snapshot(snapshot: CognitionSnapshot) -> str:
    mood = _MOOD_LABELS.get(snapshot.affect.mood, snapshot.affect.mood)
    emotion = _EMOTION_LABELS.get(snapshot.affect.emotion, snapshot.affect.emotion)
    goal = snapshot.goal.objective or snapshot.world.last_user_goal or "自然承接当前交流"
    constraints = "、".join(snapshot.goal.constraints[-4:]) or "无新增限制"
    recent = "；".join(snapshot.self_state.recent_experiences[-3:]) or "暂无"
    concern = snapshot.self_state.current_concern or "认真理解正在和我说话的人"
    return (
        "以下是你跨回合保持的当前状态，只用于维持连续性，不要逐项复述给用户，"
        "也不要声称它是隐藏推理：\n"
        f"- 当前心情：{mood}；眼前情绪：{emotion}\n"
        f"- 正在延续的目标：{goal}\n"
        f"- 已知约束：{constraints}\n"
        f"- 当前关注：{concern}\n"
        f"- 近期共同经历：{recent}\n"
        "若用户本轮明确修正目标，以最新表达为准；自然表现心情，不要戏剧化或每轮自报状态。"
    )


__all__ = ["render_cognition_context"]
