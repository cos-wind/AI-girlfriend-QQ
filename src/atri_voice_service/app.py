from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from atri_qq_bot.voice import VoiceRequest
from atri_qq_bot.runtime.inference_lock import InferencePriority

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
from .runtime_services import (
    ensure_gpt_sovits_runtime,
    gpt_sovits_runtime_ready,
    prepare_asr_runtime,
    stop_gpt_sovits_runtime,
)


def conversation_synthesis_timeout_seconds(
    text: str,
    *,
    runtime_ready: bool,
    maximum_seconds: float,
) -> float:
    """Return one bounded deadline for queue, startup and one TTS inference.

    Warm short replies fail fast; longer text gets proportionally more time. A
    cold GPT-SoVITS runtime receives a measured startup allowance without
    restoring the former unbounded 120/150-second conversation waits.
    """

    spoken_units = max(1, sum(1 for char in str(text or "") if not char.isspace()))
    warm_budget = 20.0 + min(25.0, spoken_units * 0.5)
    budget = warm_budget + (0.0 if runtime_ready else 35.0)
    hard_cap = max(5.0, min(75.0, float(maximum_seconds)))
    return min(hard_cap, max(10.0, budget))


class SpeechApplication:
    def __init__(self, config: VoiceServiceConfig) -> None:
        self.config = config
        self.profiles = VoiceProfileStore(config.profiles_dir)
        self.profiles.ensure_default()
        install_candidate_profiles(self.profiles)
        self.asr = create_asr_provider(config)
        self.tts = GptSovitsProvider(
            config.cache_dir,
            timeout_seconds=config.tts_inference_timeout_seconds,
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
            ensure_tts_runtime=self._ensure_tts_runtime,
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
        self._tts_idle_shutdown_task: Any | None = None
        self._last_asr_timings: dict[str, float] = {}

    async def _ensure_tts_runtime(self) -> bool:
        """Allow cold-start loading without extending ordinary inference forever."""

        return await ensure_gpt_sovits_runtime(
            timeout_seconds=self.config.tts_startup_timeout_seconds
        )

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
            "last_asr_timings": dict(getattr(self, "_last_asr_timings", {})),
            "profiles": profiles,
            # The service is request-ready before SenseVoice is resident.
            # ASR's own ``loaded`` flag still reports its exact model state.
            "ready": (bool(asr_status.get("dependency_available"))
                      and not bool(asr_status.get("load_error")))
            or any(profile["ready"] for profile in profiles),
        }

    async def warmup_asr(self) -> None:
        try:
            async with self.resources.lease("asr:warmup"):
                await self.asr.warmup()
        except ProviderError:
            # The error remains visible through /health; a later request can retry.
            return

    async def control_asr(self, action: str) -> dict[str, Any]:
        if action not in {"start", "stop"}:
            raise ProviderError("不支持的识别模型操作")
        # Share the inference queue with microphone requests and TTS. No runtime
        # shutdown is needed: resident mode deliberately uses CPU only.
        async with self.resources.lease("asr:control", timeout_seconds=30):
            if action == "start":
                await self.asr.load_resident()
            else:
                await self.asr.unload()
        return {"ok": True, "asr": self.asr.status()}

    async def prewarm_tts(self) -> None:
        """Load GPT-SoVITS before the first authorized conversation needs it."""
        try:
            async with self.resources.lease(
                "tts:prewarm",
                priority=InferencePriority.BACKGROUND,
            ):
                ready = await ensure_gpt_sovits_runtime(timeout_seconds=120.0)
            if ready:
                self._schedule_tts_idle_shutdown()
        except (ProviderError, TimeoutError):
            return

    async def transcribe(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        audio_path = Path(str(payload.get("audio_path") or "")).expanduser().resolve()
        if not audio_path.is_file():
            raise ProviderError("待识别语音文件不存在")
        try:
            async with self.resources.lease("asr"):
                acquired = time.perf_counter()
                asr_device = str(self.config.asr_device or "cpu").strip().lower()
                requires_gpu = asr_device.startswith(("cuda", "gpu"))
                if not await prepare_asr_runtime(requires_gpu=requires_gpu):
                    raise ProviderError("无法为语音识别释放本地推理资源")
                prepared = time.perf_counter()
                result = await self.asr.transcribe(
                    audio_path,
                    str(payload.get("language") or "auto"),
                )
        finally:
            # CPU reuse is bounded by the worker idle timer; GPU workers exit
            # after each request to return VRAM to TTS.
            release = getattr(self.asr, "release_after_request", self.asr.unload)
            await release()
        self._last_asr_timings = {
            "queue_seconds": round(acquired - started, 4),
            "resource_prepare_seconds": round(prepared - acquired, 4),
            **getattr(self.asr, "last_timings", {}),
            "total_seconds": round(time.perf_counter() - started, 4),
        }
        return {
            "ok": True,
            "text": result.text,
            "language": result.language,
            "emotion": result.emotion,
            "confidence": result.confidence,
        }

    async def synthesize(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._cancel_tts_idle_shutdown()
        request = VoiceRequest.from_tool_arguments(payload, max_chars=500)
        try:
            if request.mode == "singing":
                result = await self.singing_service.synthesize_clip(request)
            else:
                runtime_ready = await gpt_sovits_runtime_ready()
                timeout_seconds = conversation_synthesis_timeout_seconds(
                    request.text,
                    runtime_ready=runtime_ready,
                    maximum_seconds=self.config.tts_total_timeout_seconds,
                )
                try:
                    result = await asyncio.wait_for(
                        self.conversation_speech.synthesize(
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
                        ),
                        timeout=timeout_seconds,
                    )
                except TimeoutError as exc:
                    raise ProviderError(
                        f"语音合成超过 {timeout_seconds:.0f} 秒，已取消本次任务",
                        retryable=False,
                    ) from exc
                self._last_quality = self.conversation_speech.last_quality
        finally:
            self._schedule_tts_idle_shutdown()
        return {
            "ok": True,
            "audio_path": str(result.audio_path),
            "duration_seconds": result.duration_seconds,
            "source": result.source,
            "quality": result.quality,
        }

    def _cancel_tts_idle_shutdown(self) -> None:
        # 兼容测试、插件或旧集成通过 ``__new__`` 构造应用的方式。
        task = getattr(self, "_tts_idle_shutdown_task", None)
        self._tts_idle_shutdown_task = None
        if task is not None and not task.done():
            task.cancel()

    def _schedule_tts_idle_shutdown(self) -> None:
        self._cancel_tts_idle_shutdown()
        if self.config.tts_idle_shutdown_seconds <= 0:
            return
        self._tts_idle_shutdown_task = asyncio.create_task(
            self._stop_tts_after_idle(),
            name="atri-tts-idle-shutdown",
        )

    async def _stop_tts_after_idle(self) -> None:
        try:
            await asyncio.sleep(self.config.tts_idle_shutdown_seconds)
            # 停止 GPT-SoVITS 是跨进程操作（PowerShell/子进程），不能无限期
            # 占用共享推理租约。此前 stop-gpt-sovits.ps1 偶发卡住时，这个
            # 后台任务会一直持有租约，导致文本、视觉和记忆任务全部超时。
            # 到时只放弃本次卸载，释放租约；下一次语音请求仍可复用或重启引擎。
            # 空闲卸载是后台维护，不能抢在聊天/视觉任务前面，也不能无限
            # 等待前台任务；拿不到租约就跳过本轮，下一次语音结束后会重排。
            async with self.resources.lease(
                "tts:idle-shutdown",
                timeout_seconds=1.0,
                priority=InferencePriority.BACKGROUND,
            ):
                await asyncio.wait_for(
                    stop_gpt_sovits_runtime(),
                    timeout=8.0,
                )
        except asyncio.CancelledError:
            return
        except (asyncio.TimeoutError, TimeoutError):
            return

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
