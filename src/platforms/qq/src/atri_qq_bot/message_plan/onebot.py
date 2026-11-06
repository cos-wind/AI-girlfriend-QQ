from __future__ import annotations

from typing import Any

from .schema import OutgoingMessage


def outgoing_to_onebot_message(message: OutgoingMessage) -> str | list[dict[str, Any]]:
    if message.kind == "text":
        return message.content
    if message.kind == "face":
        face_id: int | str = int(message.content) if message.content.isdigit() else message.content
        return [{"type": "face", "data": {"id": face_id}}]
    if message.kind == "record":
        return [{"type": "record", "data": {"file": message.content, "cache": 0}}]
    if message.kind == "sticker":
        return [
            {
                "type": "image",
                "data": {
                    "file": message.content,
                    "cache": 0,
                    "sub_type": message.sub_type or 1,
                    "summary": message.summary or "[动画表情]",
                },
            }
        ]
    return [{"type": "image", "data": {"file": message.content, "cache": 0}}]
