from __future__ import annotations

from .builder import _append_light_emoji, build_outgoing_messages
from .onebot import outgoing_to_onebot_message
from .schema import OutgoingMessage
from .splitting import (
    _compact_reply_text,
    _ends_with_strong_punctuation,
    _hard_wrap,
    _sentence_chunks,
    _truncate_tail,
    split_reply_text,
)

__all__ = [
    "OutgoingMessage",
    "build_outgoing_messages",
    "outgoing_to_onebot_message",
    "split_reply_text",
    "_append_light_emoji",
    "_compact_reply_text",
    "_ends_with_strong_punctuation",
    "_hard_wrap",
    "_sentence_chunks",
    "_truncate_tail",
]
