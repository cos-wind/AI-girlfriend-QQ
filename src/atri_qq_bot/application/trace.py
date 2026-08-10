from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TurnTraceEvent:
    stage: str
    elapsed_ms: int
    fields: dict[str, Any] = field(default_factory=dict)


class TurnTrace:
    """In-memory trace for one turn; sinks are deliberately an outer adapter."""

    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self._started = time.perf_counter()
        self._events: list[TurnTraceEvent] = []

    def record(self, stage: str, **fields: Any) -> TurnTraceEvent:
        event = TurnTraceEvent(
            stage=stage,
            elapsed_ms=round((time.perf_counter() - self._started) * 1000),
            fields=dict(fields),
        )
        self._events.append(event)
        return event

    def snapshot(self) -> tuple[TurnTraceEvent, ...]:
        return tuple(self._events)
