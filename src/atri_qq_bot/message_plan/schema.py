from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OutgoingMessage:
    kind: Literal["text", "image", "face"]
    content: str
