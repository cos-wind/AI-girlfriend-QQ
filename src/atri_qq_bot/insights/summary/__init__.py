"""群聊归档分析、话题聚类和结构化总结。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections import Counter, defaultdict
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable

from ..config import InsightsConfig
from ..embeddings import SemanticEncoder
from ..image_report import group_summary_image_path, render_group_summary_image
from ..llm import StructuredLLMClient
from ..store import InsightsStore


LOGGER = logging.getLogger("atri.insights.summary")
WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+.#-]{2,30}")
MEDIA_MARKER_RE = re.compile(r"\[(?:表情包/图片|动画表情|图片)(?::[^\r\n]*?)?\]\]?", re.I)
STOP_WORDS = {
    "这个", "那个", "然后", "就是", "可以", "不是", "什么", "怎么", "还是", "感觉",
    "一个", "一下", "没有", "我们", "你们", "他们", "因为", "所以", "但是", "如果",
    "真的", "现在", "今天", "明天", "昨天", "哈哈", "哈哈哈", "知道", "时候", "已经",
    "here", "that", "this", "with", "from", "have", "will", "just",
    "图片", "表情", "表情包", "群友", "先生", "用户", "atri", "亚托莉",
    "可是", "突然", "不过", "jpg", "jpeg", "png", "gif", "动画", "self", "cx",
    "高性能", "机体", "呆毛", "红瞳", "双手", "眼睛",
}




from . import preprocessing, prompts, service, topics

_SUMMARY_MODULES = (preprocessing, topics, prompts, service)
for _module in _SUMMARY_MODULES:
    for _name, _value in vars(_module).items():
        if not _name.startswith("__"):
            globals()[_name] = _value
for _module in _SUMMARY_MODULES:
    for _name, _value in vars().copy().items():
        if not _name.startswith("__"):
            setattr(_module, _name, _value)

__all__ = ["GroupSummaryService", "summary_markdown"]
