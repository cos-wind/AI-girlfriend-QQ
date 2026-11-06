from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from pypinyin import Style, lazy_pinyin


ORAL_PARTICLE_TRANSLATION = str.maketrans(
    {
        "唔": "嗯",
        "欸": "诶",
        "哎": "诶",
        "啦": "了",
        "呀": "啊",
    }
)


@dataclass(frozen=True)
class SpeechQualityReport:
    passed: bool
    expected: str
    transcribed: str
    error_rate: float
    character_error_rate: float
    phonetic_error_rate: float | None = None

    def public_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "passed": self.passed,
            "expected": self.expected,
            "transcribed": self.transcribed,
            "error_rate": round(self.error_rate, 4),
            "character_error_rate": round(self.character_error_rate, 4),
        }
        if self.phonetic_error_rate is not None:
            result["phonetic_error_rate"] = round(self.phonetic_error_rate, 4)
        return result


def evaluate_transcript_quality(
    expected: str,
    transcribed: str,
    *,
    maximum_error_rate: float,
) -> SpeechQualityReport:
    normalized_expected = normalize_quality_text(expected)
    normalized_actual = normalize_quality_text(transcribed)
    if not normalized_expected:
        return SpeechQualityReport(
            True,
            normalized_expected,
            normalized_actual,
            0.0,
            0.0,
        )
    distance = _levenshtein(normalized_expected, normalized_actual)
    character_error_rate = distance / max(1, len(normalized_expected))
    phonetic_error_rate = _mandarin_phonetic_error_rate(
        normalized_expected,
        normalized_actual,
    )
    error_rate = min(
        character_error_rate,
        phonetic_error_rate
        if phonetic_error_rate is not None
        else character_error_rate,
    )
    return SpeechQualityReport(
        passed=bool(normalized_actual) and error_rate <= maximum_error_rate,
        expected=normalized_expected,
        transcribed=normalized_actual,
        error_rate=error_rate,
        character_error_rate=character_error_rate,
        phonetic_error_rate=phonetic_error_rate,
    )


def normalize_quality_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = "".join(char for char in value if char.isalnum())
    return normalized.translate(ORAL_PARTICLE_TRANSLATION)


def _mandarin_phonetic_error_rate(
    expected: str,
    actual: str,
) -> float | None:
    if not _contains_han(expected) or not _contains_han(actual):
        return None
    expected_pinyin = _pinyin_tokens(expected)
    actual_pinyin = _pinyin_tokens(actual)
    if not expected_pinyin or not actual_pinyin:
        return None
    return _levenshtein(expected_pinyin, actual_pinyin) / max(
        1,
        len(expected_pinyin),
    )


def _pinyin_tokens(text: str) -> list[str]:
    return [
        token.casefold()
        for token in lazy_pinyin(
            text,
            style=Style.TONE3,
            neutral_tone_with_five=True,
            errors=lambda value: list(value),
        )
        if str(token).strip()
    ]


def _contains_han(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _levenshtein(left: Sequence[str] | str, right: Sequence[str] | str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
