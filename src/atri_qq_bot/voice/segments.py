from __future__ import annotations

from typing import Any

from .schema import RecordSegment


def find_record_segments(message: Any) -> list[RecordSegment]:
    if not isinstance(message, list):
        return []
    records: list[RecordSegment] = []
    for segment in message:
        if not isinstance(segment, dict) or segment.get("type") != "record":
            continue
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        file = str(data.get("file") or data.get("file_id") or "").strip()
        if not file:
            continue
        records.append(RecordSegment(file=file, url=str(data.get("url") or "").strip()))
    return records
