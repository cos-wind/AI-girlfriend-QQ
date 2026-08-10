from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atri_qq_bot.voice import SynthesisResult, VoiceRequest

from .original_library import OriginalVoiceLibrary
from .providers import ProviderError


@dataclass(frozen=True)
class SingingStatus:
    enabled: bool
    clips: int
    engine: str
    root: str
    references: tuple[dict[str, str], ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "ready": self.clips > 0,
            "clips": self.clips,
            "engine": self.engine,
            "root": self.root,
            "references": list(self.references),
        }


class OriginalSingingProvider:
    """First-stage singing provider: only sends complete, verified singing clips."""

    def __init__(self, library: OriginalVoiceLibrary, *, enabled: bool = True) -> None:
        self.library = library
        self.enabled = bool(enabled)

    def status(self) -> dict[str, object]:
        references = self.library.singing_references()
        return SingingStatus(
            enabled=self.enabled,
            clips=len(references),
            engine="original_clip",
            root=str(self.library.root),
            references=tuple(references),
        ).public_dict()

    async def synthesize(self, request: VoiceRequest) -> SynthesisResult:
        if not self.enabled:
            raise ProviderError("歌唱回复未启用")
        clip = self.library.match(
            request.text,
            request.language,
            singing_only=True,
        )
        if clip is None:
            raise ProviderError(
                "没有匹配的完整歌声素材；请把以完整歌词命名的音频放入"
                "“ATRI训练音频素材\\歌唱”后重试"
            )
        output = self.library.materialize(clip)
        return SynthesisResult(
            audio_path=Path(output),
            source="original_clip",
            quality={
                "passed": True,
                "match_score": round(clip.score, 4),
                "transcript": clip.transcript,
            },
        )
