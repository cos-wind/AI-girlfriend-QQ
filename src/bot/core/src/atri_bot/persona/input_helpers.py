from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

def _shorten(text: str, limit: int = 28) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _model_failure_reply(error: Exception) -> str:
    # 保留兼容函数签名；详细诊断由调用层写日志，用户侧始终静默。
    return ""


def _is_local_ollama_endpoint(base_url: str) -> bool:
    parsed = urlsplit(str(base_url or "").strip())
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == 11434


def _chat_http_timeout(config: Any) -> float:
    """所有聊天子调用共享同一延迟预算，防止审校或重写无限拖长。"""

    return max(
        5.0,
        min(60.0, float(getattr(config, "chat_request_timeout_seconds", 25.0))),
    )


def _intent_text(text: str) -> str:
    cleaned = re.sub(r"@\d+", "", text)
    cleaned = cleaned.replace("@群友", "").replace("@全体成员", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_owner_id(value: Any, owner_qqs: tuple[int, ...]) -> bool:
    user_id = _as_int(value)
    return user_id is not None and user_id in set(owner_qqs)


def _is_affection_command(text: str) -> bool:
    return str(text or "").strip().lower().startswith("/affection")


def _user_id_from_profile_id(profile_id: str | None) -> int | None:
    if not profile_id:
        return None
    private_match = re.fullmatch(r"private:(\d+)", profile_id)
    if private_match:
        return int(private_match.group(1))
    group_member_match = re.fullmatch(r"group:[^:]+:user:(\d+)", profile_id)
    if group_member_match:
        return int(group_member_match.group(1))
    return None


def _parse_affection_set_value(text: str) -> float | None:
    normalized = text.strip().lower()
    if "偏高" in normalized or "很高" in normalized or "亲近" in normalized:
        return 78.0
    if "普通" in normalized or "正常" in normalized or "中等" in normalized:
        return 55.0
    if "偏低" in normalized or "冷淡" in normalized or "低" in normalized:
        return 32.0
    match = re.search(r"(-?\d+(?:\.\d+)?)", normalized)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None



