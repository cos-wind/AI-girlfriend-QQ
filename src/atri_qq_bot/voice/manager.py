from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .client import SpeechServiceClient, SpeechServiceError
from .policy import load_voice_behavior
from .schema import SynthesisResult, TranscriptionResult, VoiceRequest
from .segments import find_record_segments


ActionCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


class VoiceManager:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.client = self._new_client(config)
        self._last_synthesis_at: dict[str, float] = {}

    def update_config(self, config: Any) -> None:
        self.config = config
        self.client = self._new_client(config)

    async def transcribe_event(
        self,
        event: dict[str, Any],
        call_action: ActionCaller,
    ) -> TranscriptionResult | None:
        if not bool(getattr(self.config, "voice_asr_enabled", False)):
            return None
        if event.get("message_type") == "group" and not bool(
            getattr(self.config, "voice_group_enabled", False)
        ):
            return None
        records = find_record_segments(event.get("message"))
        if not records:
            return None

        response = await call_action(
            "get_record",
            {"file": records[0].file, "out_format": "wav"},
        )
        audio_path = _record_path(response)
        if audio_path is None:
            direct_path = Path(records[0].file).expanduser()
            audio_path = direct_path.resolve() if direct_path.is_file() else None
        if audio_path is None or not audio_path.is_file():
            raise SpeechServiceError("NapCat 没有返回可读取的语音文件")
        max_bytes = max(1_000_000, int(getattr(self.config, "voice_input_max_bytes", 20_000_000)))
        if audio_path.stat().st_size > max_bytes:
            raise SpeechServiceError(f"语音文件超过 {max_bytes // 1_000_000} MB 限制")
        return await self.client.transcribe(audio_path)

    async def synthesize(
        self,
        conversation_id: str,
        request: VoiceRequest,
        enforce_cooldown: bool = True,
    ) -> SynthesisResult:
        now = time.monotonic()
        cooldown = max(0.0, float(getattr(self.config, "voice_cooldown_seconds", 30) or 0))
        if request.reason == "explicit_request":
            cooldown = min(cooldown, 2.0)
        last_at = self._last_synthesis_at.get(conversation_id)
        if enforce_cooldown and last_at is not None and now - last_at < cooldown:
            remaining = max(1, int(cooldown - (now - last_at)))
            raise SpeechServiceError(f"语音回复冷却中，还需约 {remaining} 秒")
        policy = load_voice_behavior()
        profile = str(getattr(self.config, "voice_profile", "atri") or "atri")
        synthesis_options = {
            "prefer_original": bool(policy.get("original_clip_enabled", True)),
            "quality_gate": bool(policy.get("quality_gate_enabled", True)),
            "quality_max_error_rate": float(
                policy.get("quality_max_error_rate", 0.22)
            ),
            "quality_retries": max(
                3 if request.reason == "explicit_request" else 0,
                int(policy.get("quality_retries", 1) or 0),
            ),
        }
        try:
            result = await self.client.synthesize(
                request,
                profile,
                allow_context_original_fallback=True,
                allow_best_effort=True,
                **synthesis_options,
            )
        except SpeechServiceError as primary_error:
            rescue_profile = str(
                getattr(
                    self.config,
                    "voice_zh_rescue_profile",
                    "atri-official-v2pro-curated-gpt-e6",
                )
                or ""
            ).strip()
            terminal_error = primary_error
            if _should_try_chinese_rescue(
                request,
                primary_error,
                profile,
                rescue_profile,
            ):
                try:
                    result = await self.client.synthesize(
                        request,
                        rescue_profile,
                        allow_context_original_fallback=True,
                        allow_best_effort=True,
                        **synthesis_options,
                    )
                except SpeechServiceError as rescue_error:
                    terminal_error = SpeechServiceError(
                        f"{primary_error}；中文救援档案也未通过：{rescue_error}",
                        quality=_better_quality(
                            primary_error.quality,
                            rescue_error.quality,
                        ),
                        status_code=(
                            rescue_error.status_code or primary_error.status_code
                        ),
                    )
                else:
                    result = replace(
                        result,
                        quality={
                            **(result.quality or {}),
                            "rescue_profile": rescue_profile,
                        },
                    )
                    terminal_error = None
            if terminal_error is not None:
                raise terminal_error from primary_error
        if enforce_cooldown:
            self._last_synthesis_at[conversation_id] = now
        return result

    @staticmethod
    def _new_client(config: Any) -> SpeechServiceClient:
        return SpeechServiceClient(
            str(getattr(config, "voice_service_url", "http://127.0.0.1:8790")),
            float(getattr(config, "voice_service_timeout_seconds", 180.0)),
        )


def _record_path(response: dict[str, Any] | None) -> Path | None:
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    candidates = data if isinstance(data, dict) else response
    for key in ("file", "path"):
        value = str(candidates.get(key) or "").strip()
        if value:
            return Path(value).expanduser().resolve()
    return None


def _should_try_chinese_rescue(
    request: VoiceRequest,
    error: SpeechServiceError,
    profile: str,
    rescue_profile: str,
) -> bool:
    if not rescue_profile or rescue_profile == profile or request.mode != "speech":
        return False
    if request.language not in {"", "auto", "zh"}:
        return False
    if request.language in {"", "auto"} and not any(
        "\u3400" <= char <= "\u9fff" for char in request.text
    ):
        return False
    if isinstance(error.quality, dict) and bool(error.quality.get("rejected")):
        return True
    return error.status_code == 400


def _better_quality(
    primary: dict[str, Any] | None,
    rescue: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidates = [item for item in (primary, rescue) if isinstance(item, dict)]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: float(item.get("error_rate", 1.0) or 1.0),
    )
