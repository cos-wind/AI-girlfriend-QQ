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
