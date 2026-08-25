from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from ..application import ArtifactEvidence, ConversationTurnRequest, TurnTrace
from ..runtime.paths import PROJECT_ROOT
from .kernel import CognitionKernel
from .store import CognitionStateStore


LOGGER = logging.getLogger("atri.cognition.shadow")


class CognitionShadowRunner:
    """Non-blocking migration adapter for the live OneBot message path."""

    def __init__(
        self,
        kernel: CognitionKernel,
        *,
        timeout_seconds: float = 2.0,
        max_concurrency: int = 2,
        max_pending: int = 48,
        comparison_log: Path | None = None,
    ) -> None:
        self.kernel = kernel
        self.timeout_seconds = max(0.2, float(timeout_seconds))
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._max_pending = max(4, int(max_pending))
        self._tasks: set[asyncio.Task[Any]] = set()
        self._comparison_log = Path(comparison_log) if comparison_log else None
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._dropped = 0
        self._last_error = ""
        self._last_completed_at = 0.0

    @classmethod
    def from_config(cls, config: Any) -> "CognitionShadowRunner":
        state_path = Path(getattr(config, "cognition_state_path"))
        # 日志始终落在项目目录；自定义数据库路径不应改变日志归属。
        log_path = PROJECT_ROOT / "logs" / "cognition-shadow.jsonl"
        kernel = CognitionKernel(
            CognitionStateStore(state_path),
            shadow_log=log_path,
        )
        return cls(
            kernel,
            timeout_seconds=float(getattr(config, "cognition_shadow_timeout_seconds", 2.0)),
            max_concurrency=int(getattr(config, "cognition_shadow_max_concurrency", 2)),
            comparison_log=PROJECT_ROOT / "logs" / "cognition-comparison.jsonl",
        )

    def submit(
        self,
        request: ConversationTurnRequest,
        evidence: tuple[ArtifactEvidence, ...] = (),
        *,
        profile: dict[str, Any] | None = None,
    ) -> bool:
        if len(self._tasks) >= self._max_pending:
            self._dropped += 1
            return False
        self._submitted += 1
        task = asyncio.create_task(
            self._run(request, evidence, profile),
            name=f"atri-cognition-shadow:{request.turn_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run(
        self,
        request: ConversationTurnRequest,
        evidence: tuple[ArtifactEvidence, ...],
        profile: dict[str, Any] | None,
    ) -> None:
        try:
            async with self._semaphore:
                await asyncio.wait_for(
                    self.kernel.deliberate(
                        request,
                        evidence,
                        profile=profile,
                        trace=TurnTrace(request.turn_id),
                    ),
                    timeout=self.timeout_seconds,
                )
            self._completed += 1
            self._last_completed_at = time.time()
        except Exception as exc:
            self._failed += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:240]
            LOGGER.warning("认知影子回合失败：turn=%s error=%s", request.turn_id, exc)

    def record_live_outcome(
        self,
        turn_id: str,
        *,
        reply_text: str,
        delivered_text: str,
        voice_mode: str = "",
    ) -> None:
        if self._comparison_log is None:
            return
        event = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "turn_id": turn_id,
            "legacy_reply": str(reply_text or "")[:1200],
            "delivered_reply": str(delivered_text or "")[:1200],
            "voice_mode": str(voice_mode or ""),
        }
        try:
            self._comparison_log.parent.mkdir(parents=True, exist_ok=True)
            with self._comparison_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            return

    def status(self) -> dict[str, Any]:
        payload = self.kernel.status()
        payload.update(
            {
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "dropped": self._dropped,
                "pending": len(self._tasks),
                "last_error": self._last_error,
                "last_completed_at": self._last_completed_at,
            }
        )
        return payload

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def evidence_from_tool_context(tool_context: Any | None) -> tuple[ArtifactEvidence, ...]:
    """Convert runtime multimodal objects to immutable, persistable evidence."""

    context = tool_context
    while context is not None:
        findings = tuple(
            str(item)[:800]
            for item in (getattr(context, "findings", None) or ())
            if str(item).strip()
        )
        limitations = tuple(
            str(item)[:500]
            for item in (getattr(context, "limitations", None) or ())
            if str(item).strip()
        )
        sources = tuple(
            str(item)[:300]
            for item in (getattr(context, "sources", None) or ())
            if str(item).strip()
        )
        if findings or limitations or sources:
            raw_level = str(getattr(context, "read_level", "unavailable") or "unavailable")
            level = {
                "full_content": "full_content",
                "partial_content": "partial",
                "ocr_only": "ocr_only",
                "metadata_only": "metadata_only",
            }.get(raw_level, "unavailable")
            return (
                ArtifactEvidence(
                    source=sources[0] if sources else "current_material",
                    level=level,
                    findings=findings[:12],
                    limitations=limitations[:8],
                ),
            )
        context = getattr(context, "material_context", None)
    return ()


__all__ = ["CognitionShadowRunner", "evidence_from_tool_context"]
