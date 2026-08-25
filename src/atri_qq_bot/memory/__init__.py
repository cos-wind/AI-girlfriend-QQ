from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import rules as _memory_core
from .ingestion import (
    MemoryExtractionRequest,
    MemoryExtractionResult,
    MemoryExtractionWorker,
    deterministic_operations as _memory_core_deterministic_operations,
)
from ..retrieval import ContextRetrievalPlanner, RetrievalSettings

from ..proactive import parse_hhmm, safe_zoneinfo


LOGGER = logging.getLogger("atri.memory")

# 记忆保存发生在消息处理链路中，不能因为一次内存不足就让整条回复任务失败。
# 失败后采用短暂退避，避免在系统内存紧张时每条消息都重复创建序列化缓冲区。
SAVE_RETRY_MIN_SECONDS = 5.0
SAVE_RETRY_MAX_SECONDS = 60.0
MAX_MEMORY_TEXT_CHARS = 2000
MEMORY_BACKFILL_VERSION = 1


def _locked_mutation(method):
    """为主消息写入与后台整合共用一把进程内可重入锁。"""
    def wrapped(self, *args, **kwargs):
        with self._memory_state_lock:
            return method(self, *args, **kwargs)
    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped


TOPIC_STOPWORDS = _memory_core.TOPIC_STOPWORDS
CORRECTION_HINTS = _memory_core.CORRECTION_HINTS
DIRECT_HINTS = _memory_core.DIRECT_HINTS
COMFORT_HINTS = _memory_core.COMFORT_HINTS
ABSTRACT_HINTS = _memory_core.ABSTRACT_HINTS
HISTORY_LIMIT = _memory_core.HISTORY_LIMIT
MEMORY_VERSION = _memory_core.MEMORY_VERSION
L1_CONFIRMATIONS_REQUIRED = _memory_core.L1_CONFIRMATIONS_REQUIRED
L2_SLEEP_THRESHOLD = _memory_core.L2_SLEEP_THRESHOLD
L2_DAILY_DECAY = _memory_core.L2_DAILY_DECAY
DEFAULT_AFFECTION = _memory_core.DEFAULT_AFFECTION
OWNER_INITIAL_AFFECTION = _memory_core.OWNER_INITIAL_AFFECTION
GROUP_ACTIVITY_DEFAULT = _memory_core.GROUP_ACTIVITY_DEFAULT
GROUP_ACTIVITY_DAILY_DECAY = _memory_core.GROUP_ACTIVITY_DAILY_DECAY
OWNER_AFFECTION_COEFFICIENT = _memory_core.OWNER_AFFECTION_COEFFICIENT
NORMAL_AFFECTION_COEFFICIENT = _memory_core.NORMAL_AFFECTION_COEFFICIENT
PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS = _memory_core.PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS
PRIVATE_AFFECTION_IDLE_DAILY_DECAY = _memory_core.PRIVATE_AFFECTION_IDLE_DAILY_DECAY
OWNER_AFFECTION_IDLE_DAILY_DECAY = _memory_core.OWNER_AFFECTION_IDLE_DAILY_DECAY
PRIVATE_NUDGE_STOP_AFFECTION = _memory_core.PRIVATE_NUDGE_STOP_AFFECTION
PRIVATE_NUDGE_SLOW_AFFECTION = _memory_core.PRIVATE_NUDGE_SLOW_AFFECTION
PRIVATE_NUDGE_CLOSE_AFFECTION = _memory_core.PRIVATE_NUDGE_CLOSE_AFFECTION
PRIVATE_NUDGE_SLOW_MULTIPLIER = _memory_core.PRIVATE_NUDGE_SLOW_MULTIPLIER
PRIVATE_NUDGE_NORMAL_MULTIPLIER = _memory_core.PRIVATE_NUDGE_NORMAL_MULTIPLIER
MAJOR_POSITIVE_HINTS = _memory_core.MAJOR_POSITIVE_HINTS
MAJOR_NEGATIVE_HINTS = _memory_core.MAJOR_NEGATIVE_HINTS
MEDIUM_POSITIVE_HINTS = _memory_core.MEDIUM_POSITIVE_HINTS
MEDIUM_NEGATIVE_HINTS = _memory_core.MEDIUM_NEGATIVE_HINTS
ACTIONABLE_STYLE_HINTS = _memory_core.ACTIONABLE_STYLE_HINTS
AGGRESSIVE_QUALITY_HINTS = _memory_core.AGGRESSIVE_QUALITY_HINTS
DAILY_POSITIVE_HINTS = _memory_core.DAILY_POSITIVE_HINTS
NEGATIVE_MOOD_HINTS = _memory_core.NEGATIVE_MOOD_HINTS
MEMORY_POLLUTION_PATTERNS = _memory_core.MEMORY_POLLUTION_PATTERNS
NOISY_MEMORY_HINTS = _memory_core.NOISY_MEMORY_HINTS
MEMORY_TOPIC_BLOCKLIST = _memory_core.MEMORY_TOPIC_BLOCKLIST
EVENT_HINTS = _memory_core.EVENT_HINTS
TIME_HINT_PATTERN = _memory_core.TIME_HINT_PATTERN
IMPLICIT_INTEREST_HINTS = _memory_core.IMPLICIT_INTEREST_HINTS





from .extraction import MemoryExtractionMixin
from .observation import MemoryObservationMixin
from .proactive import MemoryProactiveMixin
from .state import MemoryStateMixin


class UserMemoryStore(
    MemoryStateMixin,
    MemoryObservationMixin,
    MemoryProactiveMixin,
    MemoryExtractionMixin,
):
    """对外保持原有记忆存储入口，内部按职责拆分实现。"""


from . import helpers as _memory_helpers

for _name, _value in vars(_memory_helpers).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


__all__ = [
    "UserMemoryStore",
    "is_memory_pollution_text",
    "MemoryExtractionRequest",
    "MemoryExtractionResult",
    "MemoryExtractionWorker",
]
