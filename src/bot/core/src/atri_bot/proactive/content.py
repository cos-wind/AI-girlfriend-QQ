"""Source selection and deterministic checks for proactive conversation starters.

These limits apply to opening a topic, not normal chat recall or stored memory.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any


SOURCE_MAX_AGE_SECONDS = 86400
REPEAT_MAX_AGE_SECONDS = 7 * 86400
CONTEXT_FREE_EVENTS = {"morning", "goodnight", "affection"}


def _age(entry: dict[str, Any], now: datetime) -> float:
    try:
        age = now.timestamp() - float(entry.get("at") or 0)
        return age if math.isfinite(age) else float("inf")
    except (ValueError, TypeError):
        return float("inf")


def proactive_context(history, recent_messages, now, *, is_group, limit):
    """Keep user evidence separate from bot text which is only for avoidance."""
    sources = [entry for entry in history
               if entry.get("role") == "user" and str(entry.get("text") or "").strip()
               and 0 <= _age(entry, now) <= SOURCE_MAX_AGE_SECONDS]
    sources = sorted(sources, key=lambda entry: float(entry["at"]))[-max(1, limit):]
    lines = []
    for entry in sources:
        timestamp = datetime.fromtimestamp(float(entry["at"]), now.tzinfo).strftime("%Y-%m-%d %H:%M")
        speaker = f"用户（群友 {entry.get('nickname') or '未署名'}）" if is_group else "用户"
        lines.append(f"[{timestamp}] {speaker}：{str(entry['text'])[:240]}")

    bot_entries = [entry for entry in history if entry.get("role") == "assistant"]
    bot_entries.extend(entry for entry in recent_messages if isinstance(entry, dict))
    # Use persisted texts, not an engine-local cache, so restarts cannot bypass it.
    bot_texts = list(dict.fromkeys(str(entry.get("text") or "").strip()
        for entry in bot_entries if 0 <= _age(entry, now) <= REPEAT_MAX_AGE_SECONDS
        and str(entry.get("text") or "").strip()))
    return sources, "\n".join(lines), bot_texts


def _compact(text: str) -> str:
    return "".join(char for char in str(text).casefold() if char.isalnum())


def proactive_content_rejection(text: str, bot_texts, sources) -> str:
    """Reject demonstrable repetition/false quotations; do not claim semantic QA."""
    compact = _compact(text)
    if not compact:
        return ""
    for previous in bot_texts:
        old = _compact(previous)
        if not old:
            continue
        if compact == old:
            return "repeated-content"
        if min(len(compact), len(old)) < 12:
            continue
        matcher = SequenceMatcher(None, compact, old, autojunk=False)
        shared = matcher.find_longest_match().size
        if matcher.ratio() >= 0.74 or (shared >= 24 and shared >= min(len(compact), len(old)) * 0.45):
            return "repeated-content"

    # A quotation attributed to a person must actually occur in user evidence.
    # In particular, a prior bot sentence cannot become "you said ...".
    quotations = re.findall(
        r"你(?:们)?(?:之前|上次|昨天|刚才|最近)?(?:说过|说|提到过|提到)[^。！？\n]{0,12}?[‘“\"「]([^’”\"」]{4,100})[’”\"」]",
        text,
    )
    user_texts = [_compact(str(entry.get("text") or "")) for entry in sources]
    if any(not any(_compact(quote) in source for source in user_texts) for quote in quotations):
        return "unsupported-user-quote"
    return ""
