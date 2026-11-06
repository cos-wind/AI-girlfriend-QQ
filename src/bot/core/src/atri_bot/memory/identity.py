"""Explicit identity extraction shared by foreground and background memory.

These are scoped user statements, never a source of account permissions.
"""
from __future__ import annotations

import re


_DEVELOPER_RELATION = re.compile(r"(?:亚托莉|ATRI|你|这个机器人)的开发者", re.I)


def is_developer_relationship(value: str) -> bool:
    return bool(_DEVELOPER_RELATION.fullmatch(value.strip()))


def identity_key(value: str) -> str:
    return "与亚托莉的关系" if is_developer_relationship(value) else "身份/专业"


def explicit_identity(text: str) -> str:
    match = re.search(
        r"(?:^|[，。！？!?；;\n])\s*(?:其实|现在|目前)?\s*"
        r"(?:我是|我的专业是|我的职业是)\s*([^，。！？!?；;\n]{2,24})", text,
    )
    if not match:
        return ""
    value = match[1].strip()
    if (match.end() < len(text) and text[match.end()] in "？?") or value.endswith(("吗", "么")):
        return ""
    if is_developer_relationship(value):
        return "亚托莉的开发者"
    if any(marker in value for marker in ("你", "亚托莉", "机器人", "一条消息")):
        return ""
    return value
