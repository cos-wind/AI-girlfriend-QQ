from __future__ import annotations

import re


ILLEGAL_SCRIPT_RE = re.compile(
    "["
    "\u0370-\u03ff"  # Greek
    "\u1f00-\u1fff"
    "\u0400-\u04ff"  # Cyrillic
    "\u0500-\u052f"
    "\u0590-\u05ff"  # Hebrew
    "\u0600-\u06ff"  # Arabic
    "\u0750-\u077f"
    "\u08a0-\u08ff"
    "\u0e00-\u0e7f"  # Thai
    "\u1100-\u11ff"  # Hangul Jamo
    "\u3130-\u318f"  # Hangul Compatibility Jamo
    "\uac00-\ud7af"  # Hangul syllables
    "]"
)

LATIN_EXTENDED_RE = re.compile(r"[\u00c0-\u024f]")
VIETNAMESE_MARK_RE = re.compile(
    "["
    "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝ"
    "àáâãèéêìíòóôõùúý"
    "ĂăĐđĨĩŨũƠơƯư"
    "Ạ-ỹ"
    "]"
)

PAD_TOKEN_RE = re.compile(r"\[PAD\d+\]", re.IGNORECASE)
COMBINING_GARBAGE_RE = re.compile(r"[\u0300-\u036f]{3,}")
BOX_OR_TECH_SYMBOL_RE = re.compile(r"[\u2300-\u23ff\u27c0-\u27ef]")
SYMBOL_GARBAGE_RE = re.compile(r"(?=[^\u4e00-\u9fff]{12,})[^\w\s\u4e00-\u9fff\u3040-\u30ff]{8,}")
ASCII_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_:/\\|+=\-*#@$%^&{}[\]().,;!?~`'\"]{18,}\b")
ASCII_SYMBOL_RE = re.compile(r"[_:/\\|+=\-*#@$%^&{}[\]().,;!?~`'\"]")


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
