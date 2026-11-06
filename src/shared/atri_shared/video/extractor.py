"""Bounded local FFmpeg extraction with cancellation owning the child process."""
from __future__ import annotations

from atri_shared.reply_trace import span

import asyncio
import io
import re
import subprocess
import tempfile
import time
import weakref
from pathlib import Path

from .models import FrameExtraction, VideoFrame, VideoIssue, VideoOptions

_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}
# Bound jobs in one event loop without retaining closed asyncio.run loops
# through Semaphore._loop after a contended acquisition.
_SLOTS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


class _ProcessTimeout(TimeoutError):
    def __init__(self, stdout: bytes):
        super().__init__("FFmpeg exceeded its time budget")
        self.stdout = stdout


async def _run(command: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    if timeout <= 0:
        raise TimeoutError
    process = await asyncio.create_subprocess_exec(
        *command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    communication = asyncio.create_task(process.communicate())
    try:
        stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout)
        return process.returncode, stdout, stderr
    except BaseException as exc:
        # wait_for(to_thread(subprocess.run)) cannot do this: its thread survives.
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        stdout, _ = await communication
        if isinstance(exc, TimeoutError):
            raise _ProcessTimeout(stdout) from exc
        raise


def _pipe_frames(stdout: bytes) -> list[bytes]:
    # FFmpeg's MJPEG encoder emits standalone JPEGs without embedded thumbnails.
    # Ignore an incomplete final image if the child timed out while writing it.
    return [part + b"\xff\xd9" for part in stdout.split(b"\xff\xd9")[:-1]
            if part.startswith(b"\xff\xd8")]


def _dedupe(frames: list[VideoFrame]) -> tuple[VideoFrame, ...]:
    from PIL import Image, ImageChops, ImageStat

    selected = []
    previous = None
    for frame in frames:
        try:
            with Image.open(io.BytesIO(frame.data)) as image:
                sample = image.convert("RGB").resize((32, 32))
        except Exception:
            # An unreadable JPEG is not usable evidence.
            continue
        if previous is not None:
            difference = ImageStat.Stat(ImageChops.difference(previous, sample)).mean
            if sum(difference) / len(difference) < 3.5:
                continue
        selected.append(frame)
        previous = sample
    return tuple(selected)


class FFmpegFrameExtractor:
    async def extract(
        self, data: bytes, suffix: str, options: VideoOptions, *, deadline: float,
    ) -> FrameExtraction:
        if not data or len(data) > options.max_bytes:
            return FrameExtraction(issues=(VideoIssue("extract", "invalid_input", "视频为空或超过读取上限"),))
        deadline = min(deadline, time.monotonic() + options.extraction_seconds)
        loop = asyncio.get_running_loop()
        reference = _SLOTS.get(loop)
        slots = reference() if reference is not None else None
        if slots is None:
            slots = asyncio.Semaphore(2)
            _SLOTS[loop] = weakref.ref(slots)
        try:
            await asyncio.wait_for(slots.acquire(), max(0, deadline - time.monotonic()))
        except TimeoutError:
            return FrameExtraction(issues=(VideoIssue("extract", "timeout", "视频抽帧等待资源超过阶段时限"),))
        try:
            return await self._extract(data, suffix, options, deadline)
        except Exception as exc:
            return FrameExtraction(issues=(VideoIssue("extract", "failed", f"视频抽帧失败：{exc}"),))
        finally:
            slots.release()

    async def _extract(self, data, suffix, options, deadline) -> FrameExtraction:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            return FrameExtraction(issues=(VideoIssue("extract", "unavailable", f"视频抽帧组件不可用：{exc}"),))
        issues = []
        frames = []
        duration = None
        # Only the input is stored on disk. Frames return through stdout so the
        # child does not need permission to create images in the host's temp dir.
        # Cancellation reaps the child before removing its input (also on Windows).
        with tempfile.TemporaryDirectory(prefix="atri-video-frames-") as folder:
            root = Path(folder)
            source = root / ("input" + (suffix.lower() if suffix.lower() in _EXTENSIONS else ".mp4"))
            source.write_bytes(data)
            # Local input only: a disguised playlist must not fetch nested URLs.
            base = [ffmpeg, "-nostdin", "-hide_banner", "-protocol_whitelist", "file,pipe"]
            try:
                with span('video_probe'):
                    _, _, stderr = await _run([*base, "-i", str(source)], min(8, deadline - time.monotonic()))
                match = re.search(rb"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
                if match:
                    h, m, s = map(float, match.groups())
                    duration = h * 3600 + m * 60 + s or None
            except TimeoutError:
                issues.append(VideoIssue("probe", "timeout", "视频时长探测超时，尝试顺序抽帧"))
            if duration:
                timestamps = ([duration / 2] if options.max_frames == 1 else [
                    max(0, min(duration - .05, duration * i / (options.max_frames - 1)))
                    for i in range(options.max_frames)
                ])
                for timestamp in timestamps:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        issues.append(VideoIssue("extract", "timeout", "视频抽帧超过阶段时限，保留已完成帧"))
                        break
                    command = [*base, "-v", "error", "-y", "-ss", f"{timestamp:.3f}",
                               "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
                               "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4",
                               "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"]
                    try:
                        code, stdout, stderr = await _run(command, min(6, remaining))
                        frames.extend(VideoFrame(data, timestamp) for data in _pipe_frames(stdout)[:1])
                        if code != 0:
                            detail = stderr.decode("utf-8", "replace").strip()[:1200]
                            issues.append(VideoIssue("extract", "decode_failed",
                                f"视频 {timestamp:.2f} 秒处抽帧失败：{detail or f'FFmpeg exit {code}'}"))
                    except TimeoutError:
                        issues.append(VideoIssue("extract", "timeout", f"视频 {timestamp:.2f} 秒处抽帧超时"))
            if not frames and deadline > time.monotonic():
                command = [*base, "-v", "error", "-y", "-i", str(source), "-map", "0:v:0",
                           "-an", "-sn", "-dn", "-vf", "fps=1,scale=640:-2",
                           "-frames:v", str(options.max_frames), "-q:v", "4",
                           "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"]
                stdout = b""
                try:
                    code, stdout, stderr = await _run(command, min(10, deadline - time.monotonic()))
                    if code != 0:
                        issues.append(VideoIssue("extract", "decode_failed", "视频抽帧失败：" + stderr.decode("utf-8", "replace").strip()[:1200]))
                except TimeoutError as exc:
                    stdout = getattr(exc, "stdout", b"")
                    issues.append(VideoIssue("extract", "timeout", "视频顺序抽帧超过阶段时限"))
                # FFmpeg can have emitted useful frames before an error/timeout.
                frames = [VideoFrame(data) for data in _pipe_frames(stdout)[:options.max_frames]]
                if frames:
                    issues.append(VideoIssue("extract", "sequential_fallback", "视频使用顺序抽帧，仅覆盖开头片段，时间位置未确认"))
            selected = _dedupe(frames)
            if not selected:
                issues.append(VideoIssue("extract", "no_frames", "视频文件已读取，但没有抽取到可分析画面"))
            elif duration and len(frames) < options.max_frames:
                issues.append(VideoIssue("extract", "partial_frames", "部分采样位置未能解码，已保留成功帧"))
            return FrameExtraction(selected, duration, tuple(issues))
