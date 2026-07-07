from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any


WEEKDAYS = "一二三四五六日"


def get_current_time(arguments: dict[str, Any] | None = None, now: datetime | None = None) -> str:
    args = arguments or {}
    timezone_name = str(args.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    tz = _timezone_for(timezone_name)
    current = (now or datetime.now(tz)).astimezone(tz)
    weekday = WEEKDAYS[current.weekday()]
    return (
        f"当前时间：{current:%Y-%m-%d %H:%M:%S}\n"
        f"星期：星期{weekday}\n"
        f"时区：{_timezone_label(timezone_name, tz)}"
    )


def _timezone_for(value: str) -> timezone:
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered in {"asia/shanghai", "china", "cn", "utc+8", "gmt+8", "+8", "+08:00"}:
        return timezone(timedelta(hours=8))
    if lowered in {"utc", "gmt", "z"}:
        return timezone.utc

    match = re.fullmatch(r"(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", lowered)
    if match:
        sign = 1 if match.group(1) == "+" else -1
        hours = min(14, int(match.group(2)))
        minutes = min(59, int(match.group(3) or 0))
        return timezone(sign * timedelta(hours=hours, minutes=minutes))

    return timezone(timedelta(hours=8))


def _timezone_label(value: str, tz: timezone) -> str:
    if value.strip().lower() in {"asia/shanghai", "china", "cn"}:
        return "Asia/Shanghai"
    offset = tz.utcoffset(None) or timedelta()
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return f"UTC{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"
