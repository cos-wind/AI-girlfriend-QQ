from __future__ import annotations

from pathlib import Path
from typing import Any

from atri_qq_bot.voice import VoiceRequest

from .config import VoiceServiceConfig
from .model_registry import install_candidate_profiles
from .original_library import OriginalVoiceLibrary
from .profiles import VoiceProfileStore
from .providers import GptSovitsProvider, ProviderError, create_asr_provider
from .resources import InferenceResourceManager
from .singing_service import SingingService
from .speech_pipeline import (
    ConversationSpeechPipeline,
    SpeechSynthesisOptions,
    synthesize_with_quality,
)


class SpeechApplication:
    def __init__(self, config: VoiceServiceConfig) -> None:
        self.config = config
        self.profiles = VoiceProfileStore(config.profiles_dir)
        self.profiles.ensure_default()
        install_candidate_profiles(self.profiles)
        self.asr = create_asr_provider(config)
        self.tts = GptSovitsProvider(
            config.cache_dir,
            pronunciation_path=config.tts_pronunciation_path,
            postprocess_enabled=config.tts_postprocess_enabled,
            target_rms_dbfs=config.tts_target_rms_dbfs,
            max_gain_db=config.tts_max_gain_db,
        )
        self.originals = OriginalVoiceLibrary(
            config.original_library_dir,
            config.cache_dir,
        )
        self.resources = InferenceResourceManager()
        self.conversation_speech = ConversationSpeechPipeline(
            config,
            tts=self.tts,
            asr=self.asr,
            originals=self.originals,
            profiles=self.profiles,
            resources=self.resources,
        )
        self.singing_service = SingingService(
            config,
            originals=self.originals,
            profiles=self.profiles,
            resources=self.resources,
        )
        # Compatibility aliases for the existing WebUI and local integrations.
        self.singing = self.singing_service.original_provider
        self.singing_jobs = self.singing_service.jobs
        self._last_quality: dict[str, Any] | None = None

    def health(self) -> dict[str, Any]:
        profiles = [profile.public_dict() for profile in self.profiles.list()]
        asr_status = self.asr.status()
        conversation_status = self.conversation_speech.status()
        singing_status = self.singing_service.status()
        return {
            "ok": True,
            "service": "atri-voice",
            "asr": asr_status,
            "tts": self.tts.status(),
            "original_library": self.originals.status(),
            "conversation_speech": conversation_status,
            "quality_gate": conversation_status["quality_gate"],
            "singing": singing_status["clips"],
            "singing_jobs": singing_status["jobs"],
            "inference_resources": self.resources.status(),
            "profiles": profiles,
            "ready": bool(asr_status.get("dependency_available"))
            and bool(asr_status.get("loaded"))
            and not bool(asr_status.get("load_error"))
            and any(profile["ready"] for profile in profiles),
        }

    async def warmup_asr(self) -> None:
        try:
            async with self.resources.lease("asr:warmup"):
                await self.asr.warmup()
        except ProviderError:
            # The error remains visible through /health; a later request can retry.
            return

    async def transcribe(self, payload: dict[str, Any]) -> dict[str, Any]:
        audio_path = Path(str(payload.get("audio_path") or "")).expanduser().resolve()
        if not audio_path.is_file():
            raise ProviderError("待识别语音文件不存在")
        async with self.resources.lease("asr"):
            result = await self.asr.transcribe(audio_path, str(payload.get("language") or "auto"))
        return {
            "ok": True,
            "text": result.text,
            "language": result.language,
            "emotion": result.emotion,
            "confidence": result.confidence,
        }

    async def synthesize(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = VoiceRequest.from_tool_arguments(payload, max_chars=500)
        if request.mode == "singing":
            result = await self.singing_service.synthesize_clip(request)
        else:
            result = await self.conversation_speech.synthesize(
                request,
                str(payload.get("profile") or "atri"),
                SpeechSynthesisOptions(
                    prefer_original=_payload_bool(
                        payload,
                        "prefer_original",
                        self.config.original_clip_enabled,
                    ),
                    quality_gate=_payload_bool(
                        payload,
                        "quality_gate",
                        self.config.tts_quality_gate_enabled,
                    ),
                    quality_retries=_payload_int(
                        payload,
                        "quality_retries",
                        self.config.tts_quality_retries,
                        minimum=0,
                        maximum=3,
                    ),
                    quality_max_error_rate=_payload_float(
                        payload,
                        "quality_max_error_rate",
                        self.config.tts_quality_max_error_rate,
                        minimum=0.0,
                        maximum=1.0,
                    ),
                    allow_context_original_fallback=_payload_bool(
                        payload,
                        "allow_context_original_fallback",
                        False,
                    ),
                    allow_best_effort=_payload_bool(
                        payload,
                        "allow_best_effort",
                        False,
                    ),
                ),
            )
            self._last_quality = self.conversation_speech.last_quality
        return {
            "ok": True,
            "audio_path": str(result.audio_path),
            "duration_seconds": result.duration_seconds,
            "source": result.source,
            "quality": result.quality,
        }

    async def create_singing_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.singing_service.submit(payload)

    async def get_singing_job(self, job_id: str) -> dict[str, Any]:
        return self.singing_service.get(job_id)

    async def list_singing_jobs(self) -> dict[str, Any]:
        return {"ok": True, "jobs": self.singing_service.list()}

    async def cancel_singing_job(self, job_id: str) -> dict[str, Any]:
        return await self.singing_service.cancel(job_id)

    async def _synthesize_with_quality(
        self,
        request: VoiceRequest,
        profile: Any,
        *,
        quality_gate: bool,
        retries: int,
        maximum_error_rate: float | None = None,
    ) -> tuple[Any, Any]:
        try:
            outcome = await synthesize_with_quality(
                self.config,
                self.tts,
                self.asr,
                request,
                profile,
                quality_gate=quality_gate,
                retries=retries,
                maximum_error_rate=maximum_error_rate,
            )
        except ProviderError as exc:
            report = getattr(exc, "quality_report", None)
            if isinstance(report, dict):
                self._last_quality = report
            raise
        self._last_quality = outcome.public_report
        return outcome.result, outcome.report


def _payload_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _payload_int(
    payload: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _payload_float(
    payload: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(payload.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))
