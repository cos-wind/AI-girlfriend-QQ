from __future__ import annotations

import re
from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_hhmm(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value)
    if not match:
        raise ValueError("time must use HH:MM format")

    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("time must use HH:MM format")
    return hour, minute


def safe_zoneinfo(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name in {"Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "Asia/Urumqi", "CST"}:
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        return timezone.utc
