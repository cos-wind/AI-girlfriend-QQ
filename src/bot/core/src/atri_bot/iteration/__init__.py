from __future__ import annotations

from atri_bot.iteration.decision import IterationDecision, _looks_like_correction, judge_correction
from atri_bot.iteration.hints import iteration_prompt_hint
from atri_bot.iteration.patterns import QUALITY_CORRECTION_WORDS, REFUSAL_CORRECTION_WORDS, VAGUE_CORRECTION_WORDS

__all__ = [
    "IterationDecision",
    "QUALITY_CORRECTION_WORDS",
    "REFUSAL_CORRECTION_WORDS",
    "VAGUE_CORRECTION_WORDS",
    "judge_correction",
    "iteration_prompt_hint",
    "_looks_like_correction",
]
