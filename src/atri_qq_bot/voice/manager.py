from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .client import SpeechServiceClient, SpeechServiceError
from .policy import load_voice_behavior
from .schema import SynthesisResult, TranscriptionResult, VoiceRequest
from .segments import find_record_segments
from ..runtime.modality_access import is_event_modality_allowed


ActionCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


class VoiceManager:
    """QQ 侧语音适配器。

    这里只处理事件、请求参数和 OneBot action；ASR/TTS 推理在独立进程内完成，
    避免语音模型阻塞聊天主进程。
    """

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
        # 在调用 NapCat get_record 和 ASR 服务之前拦截，未授权用户不会产生
        # 音频读取、网络传输或语音模型推理开销。
        if not is_event_modality_allowed(event, "voice"):
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
        # QQ 会话以低延迟交付为目标：回读验收仍保留给 WebUI 的严格预览。
        # 正常音频一次即交付；只有模型产出坏 WAV 时才允许一次备用种子救援。
        result = await self.client.synthesize(
            request,
            profile,
            **_synthesis_options(policy),
        )
        if enforce_cooldown:
            self._last_synthesis_at[conversation_id] = now
        return result

    @staticmethod
    def _new_client(config: Any) -> SpeechServiceClient:
        return SpeechServiceClient(
            str(getattr(config, "voice_service_url", "http://127.0.0.1:8790")),
            float(getattr(config, "voice_service_timeout_seconds", 180.0)),
        )


def _synthesis_options(
    policy: dict[str, Any],
) -> dict[str, Any]:
    """QQ 会话的单次、低延迟合成参数。"""

    return {
        "prefer_original": bool(policy.get("original_clip_enabled", True)),
        "quality_gate": False,
        "quality_max_error_rate": float(policy.get("quality_max_error_rate", 0.22)),
        # No ASR round-trip in QQ.  One alternate seed is allowed only when
        # GPT-SoVITS rejects its first generated WAV as invalid.
        "quality_retries": 1,
        "allow_context_original_fallback": True,
        "allow_best_effort": True,
    }


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
