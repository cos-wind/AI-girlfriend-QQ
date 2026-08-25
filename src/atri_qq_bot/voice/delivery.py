from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import replace
from typing import Literal

from .schema import VoiceRequest


DeliveryMode = Literal["speech", "singing"]

_NEGATED_VOICE_PATTERNS = (
    re.compile(r"(?:不要|不用|别|无需|不必).{0,4}(?:语音|声音|朗读|念)"),
    re.compile(r"(?:不要|不用|别|无需|不必).{0,1}唱"),
    re.compile(r"(?:语音|声音).{0,3}(?:关掉|关闭|停用)"),
)
_SINGING_PATTERNS = (
    re.compile(r"(?:给我|为我|帮我|可以|能不能|能|请)?唱(?:一首|首|一段|段|两句|几句|歌)?"),
    re.compile(r"(?:来|整)(?:一首|首|一段|段|两句|几句)(?:歌)?"),
)
_SPEECH_PATTERNS = (
    re.compile(r"(?:用|发|改成|换成).{0,4}语音(?:回复|回答|说|回|消息)?"),
    re.compile(r"语音(?:回复|回答|说|回|发|消息)"),
    re.compile(r"(?:读|念)(?:一遍|一下|出来|给我听|给.*听)"),
    re.compile(r"(?:说|讲)给我听"),
    re.compile(r"(?:不要|别)打字.{0,6}(?:说|回复|回答)"),
)
_EXPLICIT_SPEECH_CONTENT_PATTERNS = (
    re.compile(
        r"(?:用|发)(?:一条|个)?语音(?:回复)?(?:来)?"
        r"(?:说|念|读)(?:一句|一遍|一下)?[，,:： ]*(?P<text>.+)$"
    ),
    re.compile(
        r"(?:用|发)(?:一条|个)?语音(?:回复)?(?:来)?"
        r"讲(?:一句|一遍|一下)?[，,:：]\s*(?P<text>.+)$"
    ),
    re.compile(r"(?:用语音)?(?:和|跟)我说[，,:： ]*(?P<text>.+)$"),
    re.compile(r"用语音把(?P<text>.+?)(?:说|讲|念|读)出来(?:吧)?$"),
)
_LEADING_STAGE_DIRECTION = re.compile(
    r"^\s*[\(（\[【]\s*(?P<direction>[^\)）\]】]{1,80})\s*[\)）\]】]\s*"
)
_STAGE_DIRECTION_CUES = (
    "轻声",
    "小声",
    "低声",
    "柔声",
    "语气",
    "语调",
    "调子",
    "带着",
    "笑着",
    "微笑",
    "叹气",
    "停顿",
    "认真地",
    "温柔地",
    "开心地",
    "难过地",
    "害羞地",
    "惊讶地",
    "困倦地",
    "撒娇",
    "哭腔",
    "讲故事",
)
_BRACKETED_NON_SPEECH = re.compile(
    r"[\(（\[【][^\)）\]】\r\n]{0,240}[\)）\]】]"
)
_STARRED_NON_SPEECH = re.compile(r"(?<!\w)\*[^*\r\n]{1,240}\*(?!\w)")
_THOUGHT_BLOCK = re.compile(
    r"<\s*(?:think|thought|analysis)\s*>.*?<\s*/\s*(?:think|thought|analysis)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_THOUGHT_LINE = re.compile(
    r"(?:^|[。！？!?\n])\s*(?:内心独白|内心|心想|思考|分析|动作|旁白|OS)\s*[：:]\s*[^\n。！？!?]*"
)
_VOICE_SHORT_LIMIT = 80


@dataclass(frozen=True)
class ExplicitDeliveryIntent:
    mode: DeliveryMode
    reason: str = "explicit_request"


def detect_explicit_delivery_intent(text: str) -> ExplicitDeliveryIntent | None:
    value = re.sub(r"\s+", "", str(text or "")).strip()
    if not value or any(pattern.search(value) for pattern in _NEGATED_VOICE_PATTERNS):
        return None
    if any(pattern.search(value) for pattern in _SINGING_PATTERNS):
        return ExplicitDeliveryIntent("singing")
    if any(pattern.search(value) for pattern in _SPEECH_PATTERNS):
        return ExplicitDeliveryIntent("speech")
    return None


def build_explicit_voice_fallback(
    user_text: str,
    reply_text: str,
    *,
    max_chars: int,
) -> VoiceRequest | None:
    intent = detect_explicit_delivery_intent(user_text)
    requested = extract_explicit_spoken_text(user_text, max_chars=max_chars)
    spoken = requested or _limit_spoken_text(
        _clean_reply_text(reply_text), max_chars=max_chars
    )
    if intent is None or not spoken:
        return None
    return VoiceRequest(
        text=spoken,
        emotion=_infer_emotion(user_text, spoken),
        intensity=0.68 if intent.mode == "singing" else 0.58,
        language="auto",
        reason="explicit_request",
        mode=intent.mode,
        song_title="",
        segment_index=None,
        segment_hint="",
    )


def build_autonomous_voice_fallback(
    user_text: str,
    reply_text: str,
    *,
    max_chars: int,
    reason: str = "autonomous",
) -> VoiceRequest | None:
    raw_reply = str(reply_text or "")
    if (
        not raw_reply.strip()
        or "```" in raw_reply
        or re.search(r"https?://\S+", raw_reply)
        or re.search(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", raw_reply)
    ):
        return None
    spoken = _clean_reply_text(raw_reply)
    limit = max(1, int(max_chars))
    spoken = _limit_spoken_text(spoken, max_chars=limit)
    if not spoken:
        return None
    return VoiceRequest(
        text=spoken,
        emotion=_infer_emotion(user_text, spoken),
        intensity=0.52,
        language="auto",
        reason=reason if reason in {"autonomous", "voice_reply"} else "autonomous",
        mode="speech",
    )


def extract_explicit_spoken_text(user_text: str, *, max_chars: int) -> str:
    value = re.sub(r"@\S+\s*", "", str(user_text or "")).strip()
    for pattern in _EXPLICIT_SPEECH_CONTENT_PATTERNS:
        match = pattern.search(value)
        if match is None:
            continue
        spoken = _clean_reply_text(match.group("text")).strip()
        if spoken.endswith("吧") and len(spoken) > 1:
            spoken = spoken[:-1].rstrip()
        if spoken and spoken not in {"这个", "那个", "它", "这句", "这句话"}:
            return _limit_spoken_text(spoken, max_chars=max_chars)
    return ""


def stabilize_explicit_voice_request(
    user_text: str,
    request: VoiceRequest,
    *,
    max_chars: int,
) -> VoiceRequest:
    intent = detect_explicit_delivery_intent(user_text)
    requested = extract_explicit_spoken_text(user_text, max_chars=max_chars)
    if intent is None or not requested:
        return request
    return replace(
        request,
        text=requested,
        emotion=_infer_emotion(user_text, requested),
        reason="explicit_request",
        mode=intent.mode,
    )


def sanitize_voice_request(request: VoiceRequest, *, max_chars: int) -> VoiceRequest:
    """Remove non-spoken roleplay content before anything reaches GPT-SoVITS."""

    if request.mode != "speech":
        return request
    spoken = _limit_spoken_text(_clean_reply_text(request.text), max_chars=max_chars)
    return replace(request, text=spoken)


def _clean_reply_text(text: str) -> str:
    value = re.sub(r"https?://\S+", "", str(text or ""))
    value = _THOUGHT_BLOCK.sub(" ", value)
    value = _THOUGHT_LINE.sub(" ", value)
    # Markdown 加粗是正文格式；先拆掉双星号，避免被误判成 *动作*。
    value = re.sub(r"\*{2}", "", value)
    value = _STARRED_NON_SPEECH.sub(" ", value)
    value = _BRACKETED_NON_SPEECH.sub(" ", value)
    value = re.sub(r"[*_~`#]+", "", value)
    value = _remove_leading_stage_directions(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _limit_spoken_text(text: str, *, max_chars: int) -> str:
    value = str(text or "").strip()
    limit = max(1, min(int(max_chars), _VOICE_SHORT_LIMIT))
    if len(value) <= limit:
        return value
    boundary = max(
        (value.rfind(mark, 0, limit + 1) for mark in "。！？!?；;"),
        default=-1,
    )
    if boundary >= max(8, limit // 3):
        return value[: boundary + 1].strip()
    return value[:limit].rstrip("，,、：:；; ") + "。"


def _remove_leading_stage_directions(text: str) -> str:
    value = text
    while True:
        match = _LEADING_STAGE_DIRECTION.match(value)
        if match is None:
            return value
        if not any(cue in match.group("direction") for cue in _STAGE_DIRECTION_CUES):
            return value
        value = value[match.end() :]


def _infer_emotion(user_text: str, reply_text: str) -> str:
    user = re.sub(r"\s+", "", str(user_text or ""))
    reply = re.sub(r"\s+", "", str(reply_text or ""))
    value = f"{user} {reply}"
    if any(
        word in user
        for word in (
            "难受",
            "伤心",
            "不开心",
            "想哭",
            "委屈",
            "崩溃",
            "焦虑",
            "害怕",
            "疼",
            "抱抱",
        )
    ):
        return "gentle"
    if any(word in value for word in ("晚安", "困", "睡")):
        return "sleepy"
    if any(
        word in reply
        for word in ("害羞", "才不是", "笨蛋", "不好意思", "别看", "撒娇")
    ):
        return "shy"
    if any(
        word in reply
        for word in ("诶？", "欸？", "啊？", "真的吗", "真的假的", "居然", "竟然", "没想到")
    ):
        return "surprised"
    if any(word in reply for word in ("难过", "伤心", "失落", "想哭", "寂寞")):
        return "sad"
    if any(
        word in value
        for word in ("认真", "严肃", "重要", "注意", "不可以", "不能", "务必", "先听我说")
    ):
        return "serious"
    if any(
        word in value
        for word in ("开心", "高兴", "太好了", "早上好", "嘿嘿", "哈哈", "好耶", "成功")
    ):
        return "happy"
    return "gentle"
