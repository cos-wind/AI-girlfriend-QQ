from __future__ import annotations

import json
import re
from typing import Any


def extract_plain_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()

    if not isinstance(message, list):
        return str(message).strip()

    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue

        segment_type = segment.get("type")
        data = segment.get("data") or {}

        if segment_type == "text":
            parts.append(str(data.get("text", "")))
        elif segment_type == "at":
            qq = str(data.get("qq", ""))
            parts.append("@全体成员" if qq == "all" else "@群友")
        elif segment_type == "face":
            face_id = data.get("id") or data.get("face_id")
            parts.append(f"[QQ表情:{face_id}]" if face_id else "[QQ表情]")
        elif segment_type in {"mface", "marketface"}:
            summary = data.get("summary") or data.get("text") or data.get("name") or data.get("emoji_id")
            parts.append(f"[动画表情:{summary}]" if summary else "[动画表情]")
        elif segment_type == "image":
            summary = data.get("summary") or data.get("sub_type") or data.get("file") or data.get("url")
            if summary:
                parts.append(f"[表情包/图片:{summary}]")
            else:
                parts.append("[表情包/图片]")
        elif segment_type == "record":
            parts.append("[语音]")
        elif segment_type == "video":
            summary = data.get("summary") or data.get("title") or data.get("name") or data.get("file") or data.get("url")
            parts.append(f"[视频:{summary}]" if summary else "[视频]")
        elif segment_type == "file":
            summary = (
                data.get("name")
                or data.get("file_name")
                or data.get("filename")
                or data.get("file")
                or data.get("url")
                or data.get("file_id")
            )
            parts.append(f"[文件:{summary}]" if summary else "[文件]")
        elif segment_type in {"json", "xml", "share"}:
            summary = _share_segment_summary(data)
            parts.append(f"[分享:{summary}]" if summary else "[分享]")

    return "".join(parts).strip()


def _share_segment_summary(data: dict[str, Any]) -> str:
    raw = data.get("data") if "data" in data else data
    values: list[Any] = [data, raw]
    parsed = _parse_json_text(raw)
    if parsed is not None:
        values.append(parsed)

    title = _first_nested_text(values, {"title", "prompt", "desc", "summary"})
    url = _first_nested_url(values)
    if title and url:
        return f"{title} {url}"
    return title or url


def _parse_json_text(value: Any) -> Any | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _first_nested_text(values: list[Any], keys: set[str]) -> str:
    for value in values:
        result = _find_nested_text(value, keys)
        if result:
            return _compact_summary(result)
    return ""


def _find_nested_text(value: Any, keys: set[str]) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in keys and isinstance(item, (str, int, float)):
                text = str(item).strip()
                if text and not text.startswith(("http://", "https://")):
                    return text
            result = _find_nested_text(item, keys)
            if result:
                return result
    elif isinstance(value, list):
        for item in value:
            result = _find_nested_text(item, keys)
            if result:
                return result
    elif isinstance(value, str):
        match = re.search(r"<(?:title|summary|desc)[^>]*>(.*?)</(?:title|summary|desc)>", value, re.I | re.S)
        if match:
            return match.group(1)
    return ""


def _first_nested_url(values: list[Any]) -> str:
    for value in values:
        result = _find_nested_url(value)
        if result:
            return result
    return ""


def _find_nested_url(value: Any) -> str:
    if isinstance(value, dict):
        for item in value.values():
            result = _find_nested_url(item)
            if result:
                return result
    elif isinstance(value, list):
        for item in value:
            result = _find_nested_url(item)
            if result:
                return result
    elif isinstance(value, str):
        match = re.search(r"https?://[^\s<>\]）)\"']+", value)
        if match:
            return match.group(0).rstrip("，。！？!?")
    return ""


def _compact_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:120]
