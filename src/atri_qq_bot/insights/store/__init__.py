"""SQLite 持久层。

每个方法使用短连接，配合 WAL 和 busy_timeout，可安全地被 asyncio 工作线程与
WebUI 的 ThreadingHTTPServer 同时调用；模块不依赖 OneBot 或 WebUI。
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value)) if value not in {None, ""} else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _percentile(values: list[float], percentile: float) -> float | None:
    """线性插值百分位数；样本少时仍比只看最小/最大值稳定。"""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 4)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 4)


def _trend_bucket(day: str, values: list[float], previous_average: float | None) -> dict[str, Any]:
    average = sum(values) / len(values)
    median = _percentile(values, 0.5)
    p25 = _percentile(values, 0.25)
    p75 = _percentile(values, 0.75)
    # 质量指数兼顾中心趋势和低分尾部，比单纯平均分更容易暴露质量退化。
    quality_index = 0.5 * float(median or average) + 0.3 * average + 0.2 * float(p25 or average)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return {
        "day": day,
        "average": round(average, 4),
        "median": median,
        "p25": p25,
        "p75": p75,
        "minimum": round(min(values), 4),
        "maximum": round(max(values), 4),
        "samples": len(values),
        "quality_index": round(quality_index, 4),
        "volatility": round(variance ** 0.5, 4),
        "low_score_rate": round(sum(1 for value in values if value < 3.5) / len(values), 4),
        "delta": round(average - previous_average, 4) if previous_average is not None else None,
    }




from .delivery import DeliveryMixin
from .evaluations import EvaluationsMixin
from .groups import GroupsMixin
from .state import StateMixin
from .summaries import SummariesMixin


class InsightsStore(StateMixin, EvaluationsMixin, DeliveryMixin, GroupsMixin, SummariesMixin):
    """Stable SQLite interface assembled from domain-specific implementations."""


__all__ = ["InsightsStore", "utc_now"]
