from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OutgoingMessage:
    kind: Literal["text", "image", "sticker", "face", "record"]
    content: str
    # NapCat uses image sub_type=1 to build an animated/custom sticker element.
    sub_type: int = 0
    summary: str = ""
