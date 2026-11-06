"""One explicit deadline and independently replaceable OCR/vision providers."""
from __future__ import annotations

from atri_shared.reply_trace import span, traced

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from .extractor import FFmpegFrameExtractor
from .models import (FrameExtraction, FrameText, VideoAnalysis, VideoFrame,
                     VideoIssue, VideoOptions, VideoText)


class FrameExtractor(Protocol):
    async def extract(self, data: bytes, suffix: str, options: VideoOptions, *, deadline: float) -> FrameExtraction: ...


OcrProvider = Callable[[bytes], Awaitable[FrameText]]
VisionProvider = Callable[[tuple[VideoFrame, ...], tuple[VideoText, ...]], Awaitable[FrameText]]


class VideoAnalyzer:
    def __init__(self, *, options: VideoOptions | None = None,
                 extractor: FrameExtractor | None = None,
                 ocr: OcrProvider | None = None, vision: VisionProvider | None = None):
        self.options = options or VideoOptions()
        self.extractor = extractor or FFmpegFrameExtractor()
        self.ocr = ocr
        self.vision = vision

    async def analyze(self, data: bytes, suffix: str, *, deadline: float) -> VideoAnalysis:
        issues = []
        texts = []
        vision_text = ""
        if not data or len(data) > self.options.max_bytes:
            return VideoAnalysis(FrameExtraction(), issues=(VideoIssue("extract", "invalid_input", "视频为空或超过读取上限"),))
        if deadline <= time.monotonic():
            return VideoAnalysis(FrameExtraction(), issues=(VideoIssue("extract", "timeout", "视频分析达到时间预算"),))
        try:
            # The default extractor enforces its budget and returns partial frames.
            # Custom extractors must honor the same async cancellation contract.
            with span('video_extract'):
                extraction = await asyncio.wait_for(self.extractor.extract(
                    data, suffix, self.options, deadline=deadline),
                    min(self.options.extraction_seconds, deadline - time.monotonic()) + .05)
        except TimeoutError:
            extraction = FrameExtraction(issues=(VideoIssue("extract", "timeout", "视频抽帧超过阶段时限"),))
        except Exception as exc:
            extraction = FrameExtraction(issues=(VideoIssue("extract", "failed", f"视频抽帧失败：{exc}"),))
        issues.extend(extraction.issues)
        for index, frame in enumerate(extraction.frames, 1):
            if self.ocr is None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                issues.append(VideoIssue("ocr", "timeout", "视频分析达到时间预算，后续帧未处理"))
                break
            try:
                with span('video_ocr'):
                    value = await asyncio.wait_for(self.ocr(frame.data), min(self.options.ocr_seconds, remaining))
                if value.text.strip():
                    texts.append(VideoText(index, frame.timestamp_seconds, value.text.strip()))
                if value.error:
                    issues.append(VideoIssue("ocr", "provider_error", f"帧 {index} OCR：{value.error}"))
            except TimeoutError:
                issues.append(VideoIssue("ocr", "timeout", f"帧 {index} OCR 超时"))
            except Exception as exc:
                issues.append(VideoIssue("ocr", "failed", f"帧 {index} OCR：{exc}"))
        if extraction.frames:
            if self.vision is None:
                issues.append(VideoIssue("vision", "disabled", "已抽取关键帧，但未配置视觉模型，不能判断具体画面"))
            elif deadline <= time.monotonic():
                issues.append(VideoIssue("vision", "timeout", "视频视觉理解超过阶段时限，保留 OCR/标题降级结果"))
            else:
                try:
                    with span('video_vision'):
                        value = await asyncio.wait_for(self.vision(extraction.frames, tuple(texts)),
                            min(self.options.vision_seconds, deadline - time.monotonic()))
                    vision_text = value.text.strip()
                    if value.error or not vision_text:
                        issues.append(VideoIssue("vision", "provider_error", value.error or "视觉模型未返回可用内容"))
                except TimeoutError:
                    issues.append(VideoIssue("vision", "timeout", "视频视觉理解超过阶段时限，保留 OCR/标题降级结果"))
                except Exception as exc:
                    issues.append(VideoIssue("vision", "failed", f"视频视觉理解失败：{exc}"))
        for issue in issues:
            with span('video_issue', code=issue.code, note=issue.stage) as observed:
                observed.fail(issue.code)
        return VideoAnalysis(extraction, tuple(texts), vision_text, tuple(issues))
