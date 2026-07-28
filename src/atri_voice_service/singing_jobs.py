from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from atri_qq_bot.voice import VoiceRequest

from .original_library import OriginalVoiceLibrary
from .providers import ProviderError
from .singing import OriginalSingingProvider
from .singing_pipeline import ExternalSingingProvider, SingingJobRequest


FINAL_STATES = {"succeeded", "failed", "cancelled"}


@dataclass
class SingingJob:
    id: str
    request: SingingJobRequest
    state: str = "queued"
    progress: int = 0
    message: str = "等待处理"
    audio_path: str = ""
    source: str = ""
    quality: dict[str, Any] | None = None
    error: str = ""
    created_at: str = field(default_factory=lambda: _now())
    started_at: str = ""
    finished_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "audio_path": self.audio_path,
            "source": self.source,
            "quality": self.quality,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "request": {
                "text": self.request.text,
                "source_audio_path": (
                    str(self.request.source_audio_path)
                    if self.request.source_audio_path
                    else ""
                ),
                "reference_audio_path": (
                    str(self.request.reference_audio_path)
                    if self.request.reference_audio_path
                    else ""
                ),
                "language": self.request.language,
                "profile": self.request.profile,
                "preview_seconds": self.request.preview_seconds,
                "pitch_shift": self.request.pitch_shift,
                "prefer_original": self.request.prefer_original,
            },
        }


class SingingJobManager:
    def __init__(
        self,
        originals: OriginalVoiceLibrary,
        original_provider: OriginalSingingProvider,
        external_provider: ExternalSingingProvider | None,
        *,
        maximum_jobs: int = 50,
    ) -> None:
        self.originals = originals
        self.original_provider = original_provider
        self.external_provider = external_provider
        self.maximum_jobs = max(10, int(maximum_jobs))
        self._jobs: dict[str, SingingJob] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def status(self) -> dict[str, Any]:
        jobs = list(self._jobs.values())
        return {
            "queued": sum(job.state == "queued" for job in jobs),
            "running": sum(job.state == "running" for job in jobs),
            "completed": sum(job.state in FINAL_STATES for job in jobs),
            "external_pipeline": (
                self.external_provider.status() if self.external_provider else None
            ),
        }

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = SingingJobRequest.from_payload(payload)
        self._prune()
        job = SingingJob(id=uuid.uuid4().hex, request=request)
        self._jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run(job))
        return job.public_dict()

    def get(self, job_id: str) -> dict[str, Any]:
        return self._require_job(job_id).public_dict()

    def list(self) -> list[dict[str, Any]]:
        return [
            job.public_dict()
            for job in sorted(
                self._jobs.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
        ]

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._require_job(job_id)
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if job.state not in FINAL_STATES:
            job.state = "cancelled"
            job.message = "任务已取消"
            job.finished_at = _now()
        return job.public_dict()

    async def _run(self, job: SingingJob) -> None:
        job.state = "running"
        job.started_at = _now()
        job.progress = 1
        job.message = "查找完整原声"
        try:
            request = job.request
            match = self.originals.match(
                request.text,
                request.language,
                singing_only=True,
            )
            if request.prefer_original and match is not None:
                result = await self.original_provider.synthesize(
                    VoiceRequest(
                        text=request.text,
                        language=request.language,
                        mode="singing",
                    )
                )
            else:
                if self.external_provider is None:
                    raise ProviderError(
                        "没有匹配的完整歌声，实验歌声转换管线也尚未配置"
                    )
                result = await self.external_provider.synthesize(
                    request,
                    lambda progress, message: self._set_progress(job, progress, message),
                )
            job.state = "succeeded"
            job.progress = 100
            job.message = "歌声已生成"
            job.audio_path = str(result.audio_path)
            job.source = result.source
            job.quality = result.quality
        except asyncio.CancelledError:
            job.state = "cancelled"
            job.message = "任务已取消"
            raise
        except Exception as exc:
            job.state = "failed"
            job.error = str(exc)
            job.message = "歌声生成失败"
        finally:
            job.finished_at = _now()
            self._tasks.pop(job.id, None)

    def _set_progress(self, job: SingingJob, progress: int, message: str) -> None:
        job.progress = max(job.progress, min(99, max(0, int(progress))))
        job.message = str(message)

    def _require_job(self, job_id: str) -> SingingJob:
        job = self._jobs.get(str(job_id or "").strip())
        if job is None:
            raise KeyError("唱歌任务不存在")
        return job

    def _prune(self) -> None:
        if len(self._jobs) < self.maximum_jobs:
            return
        completed = sorted(
            (job for job in self._jobs.values() if job.state in FINAL_STATES),
            key=lambda item: item.finished_at or item.created_at,
        )
        for job in completed[: max(1, len(self._jobs) - self.maximum_jobs + 1)]:
            self._jobs.pop(job.id, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
