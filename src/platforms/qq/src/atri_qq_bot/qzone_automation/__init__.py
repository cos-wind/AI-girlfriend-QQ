from __future__ import annotations

import json
import hashlib
import random
import re
import sqlite3
import threading
import time
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

MAX_RECENT_COMMENT_FEEDS = 3
POST_WRITING_ANGLES = (
    "从一个今天的具体小观察出发，解释它为什么值得注意",
    "对一个看似正确的日常判断提出一个温和但明确的追问",
    "把一个体验拆成原因、代价和更好的选择",
    "用一个生活细节连接到更大的问题，但不要写成空泛鸡汤",
    "比较两种常见做法，给出有依据的取舍观点",
    "从一个小发现推导出一个可实践、可验证的结论",
    "写一个没有标准答案的问题，并先给出自己的暂时答案",
    "把今天的情绪转化成具体的认知，而不是只描述情绪",
    "从人与工具、效率与体验之间的张力切入，保持轻松自然",
    "从一个反常或容易被忽略的细节切入，形成清晰的转折",
    "把一个熟悉的场景换个角度看，说明这个角度改变了什么",
    "留下一个有内容的开放问题，让读者可以分享观点而非只说早安晚安",
)
POST_WRITING_FORMS = (
    "微型叙事：用一个具体场景和一次转折收束，不讲大道理，不以提问结尾",
    "观点短评：先给明确判断，再写一个理由和一个边界条件，不使用鸡汤式升华",
    "小型科普：说清一个可核验事实、背后的机制及它和普通人的关系",
    "抽象乐子：设置一本正经的前提，再用反差或错位制造包袱，不强行总结意义",
    "情感切片：写清触发情绪的细节和真实矛盾，允许留白，不虚构现实亲历",
    "角色对白：用两三句有动作感的对白推进原作相关小片段，保持人物设定",
    "清单或对照：用两到三个短项比较选择，最后给出直接取舍",
    "问题实验：提出一个能验证的问题，写出暂时答案和验证方法，不泛泛而谈",
)

_UNRELIABLE_FACT_HOSTS = {"baike.baidu.com", "baidu.com", "rili.com.cn", "wannianli.tianqi.com", "calendar.8s8s.com"}
_TRUSTED_FACT_HOST_SUFFIXES = ("gov.cn", "news.cn", "xinhuanet.com", "people.com.cn", "cas.cn", "edu.cn", "arxiv.org", "nature.com", "science.org", "nasa.gov", "who.int", "un.org", "github.com")
_UNRELIABLE_FACT_MARKERS = ("百度百科", "历史上的今天", "黄历", "万年历", "距离中秋", "距离春节", "距离国庆")
LEGACY_TOPIC_ROTATION = ["今天的生活趣事", "今天的思考与感悟", "原作剧情与角色", "热点事件的看法", "季节天气与身边观察", "学习或技术上的小发现"]
DEFAULT_TOPIC_ROTATION = ["日常趣事与小插曲", "人生哲理与反常识思考", "情感、关系与内心矛盾", "抽象乐子与反差幽默", "某个领域的前沿新闻与科普", "原作剧情、角色对白与世界观", "季节天气与身边观察", "学习或技术上的小发现"]
DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False, "post_enabled": False, "like_enabled": False, "comment_enabled": False,
    "post_mode": "window", "period_days": 1, "posts_per_period": 1, "post_start_hour": 8,
    "post_end_hour": 23, "topic_rotation": DEFAULT_TOPIC_ROTATION, "timezone": "Asia/Shanghai",
    "visibility": 1, "post_auto_generate": False,
    "post_prompt": "根据当前记忆和情绪，写一条自然、简短、带一点亚托莉口吻的 QQ 空间动态。",
    "post_model_profile_id": "", "like_rule": "target", "like_keywords": [],
    "comment_rule": "target", "comment_keywords": [], "comment_text": "看到啦，感觉很有意思～",
    "comment_use_pool": True, "feed_limit": 20, "max_likes_per_run": 10, "max_comments_per_run": 2,
    "last_post_at": 0.0, "next_post_at": 0.0, "schedule_signature": "", "last_scheduler_at": 0.0,
    "schedule_slots": [], "schedule_period_start": "",
}

from . import rules as _qzone_rules
from .automation import QZoneAutomationMixin
from .store import QZoneStoreMixin


class QZoneAutomationStore(QZoneStoreMixin):
    """Stable SQLite interface for QZone automation state."""


class QZoneAutomation(QZoneAutomationMixin):
    """Stable automation interface assembled from store and scheduling modules."""


for _name, _value in vars(_qzone_rules).items():
    if not _name.startswith("__"):
        globals()[_name] = _value
for _name, _value in vars().copy().items():
    if not _name.startswith("__"):
        vars(_qzone_rules)[_name] = _value

__all__ = ["QZoneAutomationStore", "QZoneAutomation", "content_quality_issues", "next_window_time", "schedule_times"]
