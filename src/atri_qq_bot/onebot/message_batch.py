from __future__ import annotations

from typing import Any


def _merge_message_batch(
    batch: list[tuple[Any, dict[str, Any]]],
) -> tuple[Any, dict[str, Any]]:
    if not batch:
        raise ValueError("empty message batch")
    if len(batch) == 1:
        return batch[0]

    websocket = batch[-1][0]
    merged = dict(batch[-1][1])
    segments: list[dict[str, Any]] = []
    for _, event in batch:
        segments.extend(_message_to_segments(event.get("message")))
        segments.append({"type": "text", "data": {"text": "\n"}})
    if segments and segments[-1].get("type") == "text":
        text = str((segments[-1].get("data") or {}).get("text") or "")
        if text == "\n":
            segments.pop()
    merged["message"] = segments
    return websocket, merged


def _message_to_segments(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, list):
        return [dict(segment) for segment in message if isinstance(segment, dict)]
    if message is None:
        return []
    return [{"type": "text", "data": {"text": str(message)}}]
