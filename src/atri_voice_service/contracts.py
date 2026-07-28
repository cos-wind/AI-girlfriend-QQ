from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from atri_qq_bot.voice import SynthesisResult, VoiceRequest

from .profiles import VoiceProfile


class SpeechProvider(Protocol):
    def status(self) -> dict[str, Any]: ...

    async def synthesize(
        self,
        request: VoiceRequest,
        profile: VoiceProfile,
        *,
        variation: int = 0,
    ) -> SynthesisResult: ...


class SingingProvider(Protocol):
    def status(self) -> dict[str, Any]: ...

    async def synthesize(self, request: VoiceRequest) -> SynthesisResult: ...


class AudioQualityEvaluator(Protocol):
    def evaluate(self, audio_path: Path) -> dict[str, Any]: ...
