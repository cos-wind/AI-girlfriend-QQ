from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VOICE_EMOTIONS = {
    "neutral",
    "gentle",
    "happy",
    "shy",
    "sad",
    "serious",
    "sleepy",
    "surprised",
}
VOICE_LANGUAGES = {"auto", "zh", "ja", "en"}
VOICE_REASONS = {"explicit_request", "voice_reply", "autonomous", "proactive"}
VOICE_MODES = {"speech", "singing"}


@dataclass(frozen=True)
class RecordSegment:
    file: str
    url: str = ""


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    emotion: str = "neutral"
    intensity: float = 0.55
    language: str = "auto"
    reason: str = "autonomous"
    mode: str = "speech"

    @classmethod
    def from_tool_arguments(cls, arguments: dict[str, Any], max_chars: int) -> "VoiceRequest":
        text = _spoken_text(arguments.get("text"))
        if not text:
            raise ValueError("语音文本不能为空")
        if len(text) > max(1, int(max_chars)):
            raise ValueError(f"语音文本不能超过 {max_chars} 个字符")

        emotion = str(arguments.get("emotion") or "neutral").strip().lower()
        if emotion not in VOICE_EMOTIONS:
            emotion = "neutral"
        language = str(arguments.get("language") or "auto").strip().lower()
        if language not in VOICE_LANGUAGES:
            language = "auto"
        intensity = _bounded_float(arguments.get("intensity"), default=0.55)
        reason = str(arguments.get("reason") or "autonomous").strip().lower()
        if reason not in VOICE_REASONS:
            reason = "autonomous"
        mode = str(arguments.get("mode") or "speech").strip().lower()
        if mode not in VOICE_MODES:
            mode = "speech"
        return cls(
            text=text,
            emotion=emotion,
            intensity=intensity,
            language=language,
            reason=reason,
            mode=mode,
        )


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str = "auto"
    emotion: str = "neutral"
    confidence: float | None = None

    def prompt_text(self) -> str:
        details = [f"用户发送了一条语音，识别内容：{self.text}"]
        if self.emotion not in {"", "neutral", "unknown"}:
            details.append(f"语音情绪可能是 {self.emotion}")
        return "。".join(details) + "。"


@dataclass(frozen=True)
class VoicePromptContext:
    transcription: TranscriptionResult
    material_context: Any | None = None
    prefer_voice_reply: bool = False

    def prompt_context(self) -> str:
        parts: list[str] = []
        if self.material_context is not None:
            parts.append(str(self.material_context.prompt_context()))
        parts.append(self.transcription.prompt_text())
        if self.prefer_voice_reply:
            parts.append(
                "用户刚刚发送了语音，并且允许语音回应。除非内容包含代码、网址或必须逐字查看，"
                "优先调用 speak_as_atri 用一小段自然口语回应，reason 填 voice_reply。"
            )
        return "\n".join(parts)


@dataclass(frozen=True)
class SynthesisResult:
    audio_path: Path
    duration_seconds: float | None = None
    source: str = "tts"
    quality: dict[str, Any] | None = None


def _spoken_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    return text


def _bounded_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return min(1.0, max(0.0, number))
