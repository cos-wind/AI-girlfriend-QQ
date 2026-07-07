from __future__ import annotations

import re

from .patterns import (
    ASCII_SYMBOL_RE,
    ASCII_TOKEN_RE,
    BOX_OR_TECH_SYMBOL_RE,
    COMBINING_GARBAGE_RE,
    ILLEGAL_SCRIPT_RE,
    LATIN_EXTENDED_RE,
    PAD_TOKEN_RE,
    SYMBOL_GARBAGE_RE,
    VIETNAMESE_MARK_RE,
)


def has_illegal_language_or_garbage(text: str) -> bool:
    sample = str(text or "")
    if not sample.strip():
        return False
    if PAD_TOKEN_RE.search(sample):
        return True
    script_sample = sample.replace("ω", "").replace("Ω", "")
    if ILLEGAL_SCRIPT_RE.search(script_sample):
        return True
    if LATIN_EXTENDED_RE.search(sample):
        return True
    if VIETNAMESE_MARK_RE.search(sample):
        return True
    if COMBINING_GARBAGE_RE.search(sample):
        return True
    if BOX_OR_TECH_SYMBOL_RE.search(sample):
        return True
    if _has_symbol_garbage(sample):
        return True
    if _has_ascii_garbage_without_chinese(sample):
        return True
    return False


def _has_symbol_garbage(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    if SYMBOL_GARBAGE_RE.search(compact):
        return True
    symbolish = len(re.findall(r"[^\w\u4e00-\u9fff\u3040-\u30ff\s]", compact))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", compact))
    kana = len(re.findall(r"[\u3040-\u30ff]", compact))
    return len(compact) >= 16 and cjk == 0 and kana <= 2 and symbolish / max(1, len(compact)) >= 0.5


def _has_ascii_garbage_without_chinese(text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    return any(_is_ascii_garbage_token(token) for token in ASCII_TOKEN_RE.findall(text))


def _is_ascii_garbage_token(token: str) -> bool:
    if re.fullmatch(r"[A-Fa-f0-9]{24,}", token):
        return True
    if token.startswith(("http://", "https://")):
        return False
    symbol_count = len(ASCII_SYMBOL_RE.findall(token))
    if symbol_count >= 3 or symbol_count / max(1, len(token)) >= 0.18:
        return True
    digit_count = len(re.findall(r"\d", token))
    letter_count = len(re.findall(r"[A-Za-z]", token))
    return len(token) >= 24 and digit_count >= 8 and letter_count >= 3
