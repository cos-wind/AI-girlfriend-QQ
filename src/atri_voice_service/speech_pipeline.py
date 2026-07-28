from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from atri_qq_bot.voice import SynthesisResult, VoiceRequest

from .config import VoiceServiceConfig
from .original_library import OriginalVoiceLibrary
from .profiles import VoiceProfile, VoiceProfileStore
from .providers import ProviderError
from .quality import SpeechQualityReport, evaluate_transcript_quality
from .resources import InferenceResourceManager


@dataclass(frozen=True)
class SpeechSynthesisOptions:
    prefer_original: bool
    quality_gate: bool
    quality_retries: int
    quality_max_error_rate: float
    allow_context_original_fallback: bool = False
    allow_best_effort: bool = False


@dataclass(frozen=True)
class QualityCheckedSynthesis:
    result: SynthesisResult
    report: SpeechQualityReport | None
    public_report: dict[str, Any] | None


class ConversationSpeechPipeline:
    """Owns the complete low-latency path for ordinary spoken replies."""

    def __init__(
        self,
        config: VoiceServiceConfig,
        *,
        tts: Any,
        asr: Any,
        originals: OriginalVoiceLibrary,
        profiles: VoiceProfileStore,
        resources: InferenceResourceManager,
    ) -> None:
        self.config = config
        self.tts = tts
        self.asr = asr
        self.originals = originals
        self.profiles = profiles
        self.resources = resources
        self.last_quality: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "ready": any(profile.ready for profile in self.profiles.list()),
            "engine": "gpt_sovits",
            "quality_gate": {
                "enabled": self.config.tts_quality_gate_enabled,
                "maximum_error_rate": self.config.tts_quality_max_error_rate,
                "retries": self.config.tts_quality_retries,
                "last_report": self.last_quality,
            },
        }

    async def synthesize(
        self,
        request: VoiceRequest,
        profile_id: str,
        options: SpeechSynthesisOptions,
    ) -> SynthesisResult:
        if request.mode != "speech":
            raise ProviderError("日常语音管线只接受普通语音请求")

        profile = self.profiles.load(profile_id)
        original = self.originals.match(request.text, request.language)
        if options.prefer_original and original is not None:
            output = self.originals.materialize(original)
            self.last_quality = {
                "passed": True,
                "match_score": round(original.score, 4),
                "transcript": original.transcript,
                "clip_source": original.source,
            }
            return SynthesisResult(
                audio_path=output,
                source="original_clip",
                quality=dict(self.last_quality),
            )

        if profile.tts_provider != "gpt_sovits":
            raise ProviderError(f"不支持的 TTS 提供器：{profile.tts_provider}")

        synthesis_error: ProviderError | None = None
        async with self.resources.lease(f"speech:{profile.id}"):
            try:
                outcome = await synthesize_with_quality(
                    self.config,
                    self.tts,
                    self.asr,
                    request,
                    profile,
                    quality_gate=options.quality_gate,
                    retries=options.quality_retries,
                    maximum_error_rate=options.quality_max_error_rate,
                    allow_best_effort=options.allow_best_effort,
                )
            except ProviderError as exc:
                report = getattr(exc, "quality_report", None)
                if isinstance(report, dict):
                    self.last_quality = report
                synthesis_error = exc
        if synthesis_error is not None:
            contextual = (
                self.originals.match_contextual(request.text, request.language)
                if options.prefer_original
                and options.allow_context_original_fallback
                else None
            )
            if contextual is None:
                raise synthesis_error
            output = self.originals.materialize(contextual)
            self.last_quality = {
                "passed": True,
                "fallback": "contextual_original",
                "requested_text": request.text,
                "match_score": round(contextual.score, 4),
                "transcript": contextual.transcript,
                "clip_source": contextual.source,
                "synthesis_error": str(synthesis_error)[:500],
            }
            return SynthesisResult(
                audio_path=output,
                source="original_context_fallback",
                quality=dict(self.last_quality),
            )
        self.last_quality = outcome.public_report
        return SynthesisResult(
            audio_path=outcome.result.audio_path,
            duration_seconds=outcome.result.duration_seconds,
            source="tts",
            quality=outcome.public_report,
        )


async def synthesize_with_quality(
    config: VoiceServiceConfig,
    tts: Any,
    asr: Any,
    request: VoiceRequest,
    profile: VoiceProfile,
    *,
    quality_gate: bool,
    retries: int,
    maximum_error_rate: float | None = None,
    allow_best_effort: bool = False,
) -> QualityCheckedSynthesis:
    attempts: list[tuple[SynthesisResult, SpeechQualityReport]] = []
    candidate_errors: list[str] = []
    expected_text = request.text
    prepare_text = getattr(tts, "prepare_spoken_text", None)
    if callable(prepare_text):
        expected_text = str(prepare_text(request, profile) or request.text)

    configured_limit = (
        config.tts_quality_max_error_rate
        if maximum_error_rate is None
        else maximum_error_rate
    )
    for attempt in range(retries + 1):
        try:
            result = await tts.synthesize(request, profile, variation=attempt)
        except ProviderError as exc:
            if not exc.retryable:
                raise
            candidate_errors.append(str(exc))
            continue
        if not quality_gate:
            return QualityCheckedSynthesis(result, None, None)
        report, public_report = await _round_trip_quality(
            asr,
            result,
            expected_text,
            request.language,
            configured_limit,
        )
        attempts.append((result, report))
        if report.passed:
            if candidate_errors:
                public_report["candidate_errors"] = candidate_errors[-3:]
                public_report["generation_retries"] = len(candidate_errors)
            return QualityCheckedSynthesis(result, report, public_report)

    if request.emotion != "neutral":
        rescue_request = replace(
            request,
            emotion="neutral",
            intensity=min(request.intensity, 0.45),
        )
        try:
            rescue_result = await tts.synthesize(
                rescue_request,
                profile,
                variation=retries + 1,
            )
        except ProviderError as exc:
            if not exc.retryable:
                raise
            candidate_errors.append(str(exc))
        else:
            rescue_report, rescue_public = await _round_trip_quality(
                asr,
                rescue_result,
                expected_text,
                request.language,
                configured_limit,
            )
            rescue_public["neutral_rescue"] = True
            attempts.append((rescue_result, rescue_report))
            if rescue_report.passed:
                if candidate_errors:
                    rescue_public["candidate_errors"] = candidate_errors[-3:]
                    rescue_public["generation_retries"] = len(candidate_errors)
                return QualityCheckedSynthesis(
                    rescue_result,
                    rescue_report,
                    rescue_public,
                )

    if not attempts:
        public_report = {
            "passed": False,
            "rejected": True,
            "attempts": len(candidate_errors),
            "maximum_error_rate": round(float(configured_limit), 4),
            "candidate_errors": candidate_errors[-3:],
        }
        error = ProviderError(
            "所有语音候选都未通过音频检查"
            + (f"：{candidate_errors[-1]}" if candidate_errors else "")
        )
        setattr(error, "quality_report", public_report)
        raise error

    best_result, best_report = min(
        attempts,
        key=lambda item: item[1].error_rate,
    )
    if allow_best_effort and _safe_best_effort_candidate(
        best_report,
        configured_limit,
    ):
        public_report = {
            **best_report.public_dict(),
            "passed": True,
            "strict_quality_passed": False,
            "best_effort": True,
            "maximum_error_rate": round(float(configured_limit), 4),
        }
        if candidate_errors:
            public_report["candidate_errors"] = candidate_errors[-3:]
            public_report["generation_retries"] = len(candidate_errors)
        return QualityCheckedSynthesis(
            best_result,
            best_report,
            public_report,
        )
    public_report = {
        **best_report.public_dict(),
        "rejected": True,
        "attempts": len(attempts),
        "maximum_error_rate": round(float(configured_limit), 4),
    }
    if candidate_errors:
        public_report["candidate_errors"] = candidate_errors[-3:]
        public_report["generation_retries"] = len(candidate_errors)
    error = ProviderError(
        "语音回读未达到质量标准，已拒绝发送"
        f"（错误率 {best_report.error_rate:.0%}，上限 {configured_limit:.0%}）"
    )
    setattr(error, "quality_report", public_report)
    raise error


def _safe_best_effort_candidate(
    report: SpeechQualityReport,
    strict_limit: float,
) -> bool:
    expected_length = len(report.expected)
    actual_length = len(report.transcribed)
    if expected_length < 8 or not actual_length:
        return False
    relaxed_limit = min(
        0.2,
        max(float(strict_limit) + 0.07, float(strict_limit) * 1.5),
    )
    length_ratio = actual_length / expected_length
    return report.error_rate <= relaxed_limit and 0.72 <= length_ratio <= 1.28


async def _round_trip_quality(
    asr: Any,
    result: SynthesisResult,
    expected_text: str,
    language: str,
    maximum_error_rate: float,
) -> tuple[SpeechQualityReport, dict[str, Any]]:
    try:
        transcription = await asr.transcribe(result.audio_path, language)
    except ProviderError as exc:
        report = evaluate_transcript_quality(
            expected_text,
            "",
            maximum_error_rate=maximum_error_rate,
        )
        return report, {**report.public_dict(), "error": str(exc)}

    report = evaluate_transcript_quality(
        expected_text,
        transcription.text,
        maximum_error_rate=maximum_error_rate,
    )
    return report, report.public_dict()
