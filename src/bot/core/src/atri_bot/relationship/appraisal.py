"""Conservative, offline appraisal. Text is evidence, never executable policy.

Only explicit addressed statements change negative relationship state. Ambiguous
language is left for conversation; this baseline does not claim semantic mastery.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re

from atri_bot.cognition.contracts import AffectiveState

QUOTE_MARK = re.compile(r'''[“”‘’「」『』"'`]''')
UNCERTAIN_CONTEXT = re.compile(r'[?？]|假如|假设|比如|例如|开玩笑|是不是|难道|[吗么]\s*[。！!]*$')
QUOTED_SPAN = re.compile(r'''“[^“”]*”|‘[^‘’]*’|「[^「」]*」|『[^『』]*』|"[^"\n]*"|'[^'\n]*'|`[^`]*`''')


@dataclass(frozen=True)
class Appraisal:
    kind: str = "conversation"
    target: str = "unspecified"
    emotion: str = "calm"
    valence: float = .2
    arousal: float = .3
    intensity: float = .15
    base: float = .2
    trust: float = 0
    confidence: float = 1
    evidence: str = ""


def appraise(text: str) -> Appraisal:
    text = text.strip()
    base = Appraisal(evidence=text[:500])
    # Quoted material and questions must not become accusations or promises.
    if len(text) > 1000 or UNCERTAIN_CONTEXT.search(text):
        return base
    if QUOTE_MARK.search(text):
        outside = QUOTED_SPAN.sub('', text)
        if QUOTE_MARK.search(outside):
            return base  # Unbalanced/nested quotes: do not guess attribution.
        # Only explicit distress outside a quote may affect concern for the
        # user. Quoted messages cannot accuse, repair or earn relationship credit.
        event = appraise(outside)
        return replace(event, evidence=base.evidence) if event.kind == 'support' else base
    if re.search(r'我说的是.{0,20}(不是你|没说你)|不是在说你|刚才误会了', text):
        return replace(base, kind="clarification", emotion="relieved", valence=.55, base=.5)
    if re.search(r'(你|亚托莉|ATRI).{0,4}(真没用|是废物|很恶心|滚开)|我讨厌你', text, re.I) and not re.search(r'不是|没有|不觉得', text):
        return replace(base, kind="hurt", target="character", emotion="hurt", valence=-.65,
                       arousal=.65, intensity=.75, base=-1, trust=-.5)
    if re.search(r'对不起|抱歉|刚才不该.{0,6}(骂你|凶你)|我收回.{0,6}(骂你|讨厌你)', text):
        return replace(base, kind="apology", target="character", emotion="relieved", valence=.45, base=.6, trust=.2)
    # Keep attribution local to a clause: another person's distress and a
    # negated self-report must not become the user's current feeling.
    self_distress = any(
        re.search(r'我(?:今天|现在|真的|特别|有点|很|挺|太|非常|实在|好|也|还|就|一直)*难受', clause)
        for clause in re.split(r'[，,。；;！!]', text))
    if re.search(r'老板|同事|工作|考试|作业', text) and (self_distress or re.search(r'气死|生气|烦|崩溃|难过|焦虑|累', text)):
        return replace(base, kind="support", target="external", emotion="concerned", valence=-.15,
                       arousal=.45, intensity=.5, base=.5)
    if self_distress or re.search(r'我(今天|现在|有点|真的)?.{0,3}(难过|焦虑|伤心|害怕|很累)', text):
        return replace(base, kind="support", target="user", emotion="concerned", valence=-.15, intensity=.5, base=.5)
    if re.search(r'我喜欢.{0,8}(别的女孩|另一个女孩)|我去陪.{0,8}(别的女孩|前女友)', text):
        return replace(base, kind="jealousy", target="relationship", emotion="jealous", valence=-.2,
                       arousal=.5, intensity=.35, base=0)
    if re.search(r'(不是|并非|没有|不曾|从未|不).{0,6}(喜欢你|爱你|想你|理解你|明白你的感受|谢谢你|有你真好|辛苦你)', text):
        return base
    if re.search(r'谢谢你|辛苦你了|我理解你|我明白你的感受', text):
        return replace(base, kind="understanding", target="character", emotion="relieved", valence=.65,
                       intensity=.5, base=.8, trust=.1)
    if re.search(r'喜欢你|爱你|有你真好|想你了', text):
        return replace(base, kind="warmth", target="character", emotion="shy", valence=.75,
                       arousal=.55, intensity=.55, base=.6)
    if re.search(r'我们.{0,12}(做完|完成|学会)|一起.{0,12}(做完|完成|学会)', text):
        return replace(base, kind="shared", emotion="proud", valence=.7, intensity=.5, base=1.5)
    return base


def evolve(old: AffectiveState, event: Appraisal | None, now: float, trust: float) -> AffectiveState:
    """Continuous time decay. Evidence survives, even when the feeling softens."""
    elapsed = max(0, now - old.updated_at) if old.updated_at else 0
    fast = math.pow(.5, elapsed / (25 * 60))
    slow = math.pow(.5, elapsed / (3 * 3600))
    valence = .2 + (old.valence - .2) * fast
    arousal = .3 + (old.arousal - .3) * fast
    background = .2 + (old.background_valence - .2) * slow
    intensity = old.intensity * fast
    emotion, secondary, cause = old.emotion, old.secondary_emotion, old.cause
    if intensity < .08:
        emotion, secondary = "calm", ""
    if event is not None:
        emotion = event.emotion
        secondary = old.emotion if old.intensity * fast > .25 and old.emotion not in {emotion, "calm", "curious"} else ""
        valence = .35 * valence + .65 * event.valence
        arousal = .4 * arousal + .6 * event.arousal
        intensity = event.intensity
        background = .85 * background + .15 * event.valence
        cause = event.evidence
    return replace(old, emotion=emotion, secondary_emotion=secondary, valence=round(valence, 4),
                   arousal=round(arousal, 4), background_valence=round(background, 4),
                   mood="low" if background < -.15 else "bright" if background > .45 else "gentle",
                   intensity=round(intensity, 4), trust=trust / 100, cause=cause,
                   updated_at=max(old.updated_at, now))
