"""Platform-free contracts. Timestamps are sample positions, not watched coverage."""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class VideoOptions:
    max_frames: int = 4
    max_bytes: int = 80_000_000
    extraction_seconds: float = 24.0
    ocr_seconds: float = 5.0
    vision_seconds: float = 55.0

    def __post_init__(self):
        if not 1 <= self.max_frames <= 8 or self.max_bytes <= 0:
            raise ValueError("视频帧数须为 1–8，字节上限须大于零")
        for value in (self.extraction_seconds, self.ocr_seconds, self.vision_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("视频阶段时限须为有限正数")


@dataclass(frozen=True)
class VideoIssue:
    stage: str
    code: str
    message: str


@dataclass(frozen=True)
class VideoFrame:
    data: bytes = field(repr=False)
    timestamp_seconds: float | None = None


@dataclass(frozen=True)
class FrameExtraction:
    frames: tuple[VideoFrame, ...] = ()
    duration_seconds: float | None = None
    issues: tuple[VideoIssue, ...] = ()


@dataclass(frozen=True)
class FrameText:
    text: str = ""
    error: str = ""


@dataclass(frozen=True)
class VideoText:
    frame_index: int
    timestamp_seconds: float | None
    text: str


@dataclass(frozen=True)
class VideoAnalysis:
    extraction: FrameExtraction
    texts: tuple[VideoText, ...] = ()
    vision_text: str = ""
    issues: tuple[VideoIssue, ...] = ()

    @property
    def visual_status(self) -> str:
        return "verified" if self.vision_text else "ocr_only" if self.texts else "metadata_only"
