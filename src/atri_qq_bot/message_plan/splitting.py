from __future__ import annotations

import re


def split_reply_text(text: str, max_chars: int = 44, max_parts: int = 4) -> list[str]:
    text = _compact_reply_text(text)
    if not text:
        return []

    raw_sentences = _sentence_chunks(text)
    pieces: list[str] = []
    for sentence in raw_sentences:
        pieces.extend(_hard_wrap(sentence, max_chars))

    merged: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if merged and len(merged[-1]) + len(piece) <= max_chars and not _ends_with_strong_punctuation(merged[-1]):
            merged[-1] = f"{merged[-1]}{piece}"
        else:
            merged.append(piece)

    if len(merged) <= max_parts:
        return merged

    kept = merged[: max_parts - 1]
    tail = "".join(merged[max_parts - 1 :])
    kept.append(_truncate_tail(tail, max_chars * 2))
    return kept


def _compact_reply_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text.strip())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _sentence_chunks(text: str) -> list[str]:
    chunks = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    cleaned = [chunk.strip() for chunk in chunks if chunk.strip()]
    return cleaned or [text]


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    remaining = text
    soft_marks = "，,、 "
    while len(remaining) > max_chars:
        split_at = max(remaining.rfind(mark, 0, max_chars + 1) for mark in soft_marks)
        if split_at < max_chars // 2:
            split_at = max_chars
        part = remaining[: split_at + 1].strip()
        remaining = remaining[split_at + 1 :].strip()
        if part:
            parts.append(part)
    if remaining:
        parts.append(remaining)
    return parts


def _ends_with_strong_punctuation(text: str) -> bool:
    return text.endswith(("。", "！", "？", "!", "?", "；", ";"))


def _truncate_tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"
