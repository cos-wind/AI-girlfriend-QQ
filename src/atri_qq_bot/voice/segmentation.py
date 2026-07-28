from __future__ import annotations

import re


_SENTENCE_PATTERN = re.compile(r".+?(?:[。！？!?；;\n]+|$)", re.DOTALL)
_CLAUSE_PATTERN = re.compile(r".+?(?:[，,、：:]|$)", re.DOTALL)
_SPOKEN_UNIT_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9]")
_EXPRESSIVE_REPEAT_PATTERN = re.compile(
    r"(?P<run>(?P<char>[\u3040-\u30ff\u3400-\u9fffA-Za-z])(?P=char){2,})"
)
_BRACKETED_DIRECTION_PATTERN = re.compile(
    r"[\(（\[【]\s*(?P<direction>[^\)）\]】]{1,80})\s*[\)）\]】]"
)
_DIRECTION_CUES = (
    "轻声",
    "小声",
    "低声",
    "柔声",
    "语气",
    "语调",
    "笑着",
    "微笑",
    "叹气",
    "轻咳",
    "清嗓",
    "停顿",
    "撒娇",
    "哭腔",
    "讲故事",
)


def split_spoken_text(
    text: str,
    *,
    maximum_units: int = 34,
    minimum_units: int = 8,
) -> list[str]:
    """Split speech at semantic punctuation before falling back to hard limits."""

    value = _clean_segmentation_text(str(text or ""))
    value = re.sub(r"\s*\n+\s*", "。", value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    if not value:
        return []

    maximum = max(12, int(maximum_units))
    minimum = max(2, min(int(minimum_units), maximum // 2))
    expressive_segments = _split_expressive_runs(value, maximum, minimum)
    if len(expressive_segments) > 1:
        return expressive_segments
    total_units = spoken_unit_count(value)
    if total_units <= maximum:
        return [value]
    leading_interjection = re.match(r"^(嗯|唔|诶|哎)[，,]\s*(.+)$", value, re.DOTALL)
    if leading_interjection:
        interjection, remainder = leading_interjection.groups()
        return [
            f"{interjection}。",
            *split_spoken_text(
                remainder,
                maximum_units=maximum,
                minimum_units=minimum,
            ),
        ]

    segments: list[str] = []
    sentences = [
        match.group(0).strip()
        for match in _SENTENCE_PATTERN.finditer(value)
        if match.group(0).strip()
    ]
    for sentence in sentences:
        if spoken_unit_count(sentence) <= maximum:
            segments.append(sentence)
            continue
        segments.extend(_split_long_sentence(sentence, maximum))
    return _merge_short_segments(segments, maximum, minimum)


def _split_expressive_runs(text: str, maximum: int, minimum: int) -> list[str]:
    if _EXPRESSIVE_REPEAT_PATTERN.search(text) is None:
        return [text]
    marked = _EXPRESSIVE_REPEAT_PATTERN.sub(
        lambda match: f"\n{match.group('run')}\n",
        text,
    )
    segments = []
    for raw_part in marked.splitlines():
        part = re.sub(r"^[，,、：:。；;]+|[，,、：:。；;]+$", "", raw_part).strip()
        if not part:
            continue
        if (
            _EXPRESSIVE_REPEAT_PATTERN.fullmatch(part)
            or spoken_unit_count(part) <= maximum
        ):
            segments.append(part)
        else:
            segments.extend(
                split_spoken_text(
                    part,
                    maximum_units=maximum,
                    minimum_units=minimum,
                )
            )
    return segments or [text]


def _clean_segmentation_text(text: str) -> str:
    def remove_direction(match: re.Match[str]) -> str:
        direction = match.group("direction")
        return " " if any(cue in direction for cue in _DIRECTION_CUES) else direction

    value = _BRACKETED_DIRECTION_PATTERN.sub(remove_direction, text)
    return re.sub(r"[\(\)（）\[\]【】]", " ", value)


def spoken_unit_count(text: str) -> int:
    return len(_SPOKEN_UNIT_PATTERN.findall(str(text or "")))


def _split_long_sentence(sentence: str, maximum: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    clauses = [
        match.group(0).strip()
        for match in _CLAUSE_PATTERN.finditer(sentence)
        if match.group(0).strip()
    ]
    for clause in clauses:
        if spoken_unit_count(clause) > maximum:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(clause, maximum))
            continue
        candidate = f"{current}{clause}"
        if current and spoken_unit_count(candidate) > maximum:
            chunks.append(current)
            current = clause
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _hard_split(text: str, maximum: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    units = 0
    for index, char in enumerate(text):
        if _SPOKEN_UNIT_PATTERN.fullmatch(char):
            units += 1
        if units < maximum:
            continue
        chunks.append(text[start : index + 1].strip())
        start = index + 1
        units = 0
    remainder = text[start:].strip()
    if remainder:
        chunks.append(remainder)
    return [chunk for chunk in chunks if chunk]


def _merge_short_segments(
    segments: list[str],
    maximum: int,
    minimum: int,
) -> list[str]:
    merged: list[str] = []
    for segment in segments:
        if (
            merged
            and spoken_unit_count(segment) < minimum
            and spoken_unit_count(merged[-1] + segment) <= maximum
        ):
            merged[-1] += segment
        else:
            merged.append(segment)
    if (
        len(merged) > 1
        and spoken_unit_count(merged[0]) < minimum
        and spoken_unit_count(merged[0] + merged[1]) <= maximum
    ):
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged
