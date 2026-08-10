from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from .schema import SynthesisResult, TranscriptionResult, VoiceRequest


class SpeechServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        quality: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.quality = quality
        self.status_code = status_code


class SpeechServiceClient:
    def __init__(self, base_url: str, timeout_seconds: float = 180.0) -> None:
        self.base_url = str(base_url or "http://127.0.0.1:8790").rstrip("/")
        self.timeout_seconds = max(2.0, float(timeout_seconds))

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds))

    async def health(self) -> dict[str, Any]:
        return await self._get_json("/health")

    async def transcribe(self, audio_path: Path, language: str = "auto") -> TranscriptionResult:
        path = Path(audio_path).expanduser().resolve()
        if not path.is_file():
            raise SpeechServiceError(f"语音文件不存在：{path}")
        payload = await self._post_json(
            "/v1/transcribe",
            {"audio_path": str(path), "language": language or "auto"},
        )
        _require_ok(payload)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise SpeechServiceError("语音识别没有返回文本")
        confidence = _optional_float(payload.get("confidence"))
        return TranscriptionResult(
            text=text,
            language=str(payload.get("language") or language or "auto"),
            emotion=str(payload.get("emotion") or "neutral").lower(),
            confidence=confidence,
        )

    async def synthesize(
        self,
        request: VoiceRequest,
        profile: str,
        *,
        prefer_original: bool | None = None,
        quality_gate: bool | None = None,
        quality_max_error_rate: float | None = None,
        quality_retries: int | None = None,
        allow_context_original_fallback: bool | None = None,
        allow_best_effort: bool | None = None,
    ) -> SynthesisResult:
        request_payload: dict[str, object] = {
            "text": request.text,
            "emotion": request.emotion,
            "intensity": request.intensity,
            "language": request.language,
            "profile": profile or "atri",
            "mode": request.mode,
        }
        if prefer_original is not None:
            request_payload["prefer_original"] = prefer_original
        if quality_gate is not None:
            request_payload["quality_gate"] = quality_gate
        if quality_max_error_rate is not None:
            request_payload["quality_max_error_rate"] = quality_max_error_rate
        if quality_retries is not None:
            request_payload["quality_retries"] = quality_retries
        if allow_context_original_fallback is not None:
            request_payload["allow_context_original_fallback"] = (
                allow_context_original_fallback
            )
        if allow_best_effort is not None:
            request_payload["allow_best_effort"] = allow_best_effort
        payload = await self._post_json(
            "/v1/synthesize",
            request_payload,
        )
        _require_ok(payload)
        raw_path = str(payload.get("audio_path") or "").strip()
        if not raw_path:
            raise SpeechServiceError("语音合成没有返回音频文件")
        audio_path = Path(raw_path).expanduser().resolve()
        if not audio_path.is_file():
            raise SpeechServiceError(f"合成音频不存在：{audio_path}")
        return SynthesisResult(
            audio_path=audio_path,
            duration_seconds=_optional_float(payload.get("duration_seconds")),
            source=str(payload.get("source") or "tts"),
            quality=payload.get("quality") if isinstance(payload.get("quality"), dict) else None,
        )

    async def create_singing_job(
        self,
        *,
        text: str,
        source_audio_path: Path,
        profile: str,
        reference_audio_path: Path | None = None,
        language: str = "auto",
        preview_seconds: int = 15,
        pitch_shift: float = 0.0,
        prefer_original: bool = False,
    ) -> dict[str, Any]:
        request_payload: dict[str, object] = {
            "text": text,
            "source_audio_path": str(Path(source_audio_path).expanduser().resolve()),
            "profile": profile or "atri",
            "language": language or "auto",
            "preview_seconds": preview_seconds,
            "pitch_shift": pitch_shift,
            "prefer_original": prefer_original,
        }
        if reference_audio_path is not None:
            request_payload["reference_audio_path"] = str(
                Path(reference_audio_path).expanduser().resolve()
            )
        payload = await self._post_json(
            "/v1/singing/jobs",
            request_payload,
        )
        _require_ok(payload)
        return payload

    async def singing_jobs(self) -> dict[str, Any]:
        payload = await self._get_json("/v1/singing/jobs")
        _require_ok(payload)
        return payload

    async def singing_job(self, job_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/v1/singing/jobs/{job_id}")
        _require_ok(payload)
        return payload

    async def cancel_singing_job(self, job_id: str) -> dict[str, Any]:
        payload = await self._post_json(
            f"/v1/singing/jobs/{job_id}/cancel",
            {},
        )
        _require_ok(payload)
        return payload

    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.get(f"{self.base_url}{path}")
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise _speech_service_error(exc.response) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SpeechServiceError(f"语音服务不可用：{exc}") from exc
        if not isinstance(payload, dict):
            raise SpeechServiceError("语音服务返回了无效数据")
        return payload

    async def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        delays = (0.2, 0.6)
        for attempt in range(len(delays) + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout()) as client:
                    response = await client.post(f"{self.base_url}{path}", json=payload)
                    response.raise_for_status()
                    result = response.json()
            except httpx.HTTPStatusError as exc:
                if (
                    attempt < len(delays)
                    and exc.response.status_code in {429, 502, 503, 504}
                ):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise _speech_service_error(exc.response) from exc
            except httpx.HTTPError as exc:
                if attempt < len(delays) and isinstance(
                    exc,
                    (
                        httpx.ConnectError,
                        httpx.ConnectTimeout,
                        httpx.NetworkError,
                        httpx.RemoteProtocolError,
                    ),
                ):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise SpeechServiceError(f"语音服务不可用：{exc}") from exc
            except ValueError as exc:
                raise SpeechServiceError(f"语音服务不可用：{exc}") from exc
            if not isinstance(result, dict):
                raise SpeechServiceError("语音服务返回了无效数据")
            return result
        raise SpeechServiceError("语音服务重试后仍不可用")


def _require_ok(payload: dict[str, Any]) -> None:
    if payload.get("ok") is False:
        raise SpeechServiceError(str(payload.get("error") or "语音服务执行失败"))


def _speech_service_error(response: httpx.Response) -> SpeechServiceError:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = str(payload.get("error") or "").strip()
        if detail:
            quality = payload.get("quality")
            return SpeechServiceError(
                detail,
                quality=quality if isinstance(quality, dict) else None,
                status_code=response.status_code,
            )
    return SpeechServiceError(
        f"语音服务请求失败：HTTP {response.status_code}",
        status_code=response.status_code,
    )


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
