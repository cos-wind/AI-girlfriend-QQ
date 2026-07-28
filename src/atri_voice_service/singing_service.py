from __future__ import annotations

from typing import Any

from atri_qq_bot.voice import SynthesisResult, VoiceRequest

from .config import VoiceServiceConfig
from .original_library import OriginalVoiceLibrary
from .profiles import VoiceProfileStore
from .providers import ProviderError
from .resources import InferenceResourceManager
from .singing import OriginalSingingProvider
from .singing_jobs import SingingJobManager
from .singing_pipeline import ExternalSingingProvider


class SingingService:
    """Keeps song retrieval and long-running singing conversion out of TTS."""

    def __init__(
        self,
        config: VoiceServiceConfig,
        *,
        originals: OriginalVoiceLibrary,
        profiles: VoiceProfileStore,
        resources: InferenceResourceManager,
    ) -> None:
        self.config = config
        self.profiles = profiles
        self.original_provider = OriginalSingingProvider(
            originals,
            enabled=config.singing_enabled,
        )
        external_provider = (
            ExternalSingingProvider(
                config.singing_pipeline_manifest,
                config.cache_dir,
                resources,
            )
            if config.singing_enabled
            else None
        )
        self.jobs = SingingJobManager(
            originals,
            self.original_provider,
            external_provider,
            maximum_jobs=config.singing_maximum_jobs,
        )

    def status(self) -> dict[str, Any]:
        return {
            "clips": self.original_provider.status(),
            "jobs": self.jobs.status(),
        }

    async def synthesize_clip(self, request: VoiceRequest) -> SynthesisResult:
        if request.mode != "singing":
            raise ProviderError("唱歌能力只接受歌唱请求")
        return await self.original_provider.synthesize(request)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.singing_enabled:
            raise ProviderError("歌唱功能未启用")
        resolved = dict(payload)
        profile_id = str(resolved.get("profile") or "atri")
        if resolved.get("source_audio_path") and not resolved.get(
            "reference_audio_path"
        ):
            profile = self.profiles.load(profile_id)
            resolved["reference_audio_path"] = profile.reference_audio
        return self.jobs.submit(resolved)

    def get(self, job_id: str) -> dict[str, Any]:
        return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        return self.jobs.list()

    async def cancel(self, job_id: str) -> dict[str, Any]:
        return await self.jobs.cancel(job_id)
