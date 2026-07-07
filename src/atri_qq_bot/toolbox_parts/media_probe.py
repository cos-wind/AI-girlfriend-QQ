from __future__ import annotations

import re
import struct
import subprocess
import tempfile
from pathlib import Path

from .formatting import _shorten


VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}


def _image_mime_type(data: bytes) -> str:
    info = _image_info(data)
    if not info:
        return "image/png"
    kind = info[0].lower()
    if kind == "jpeg":
        return "image/jpeg"
    return f"image/{kind}"

def _extract_video_frames(data: bytes, ext: str, max_frames: int) -> tuple[list[bytes], str]:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        return [], f"视频抽帧组件不可用：{exc}"

    suffix = ext if ext in VIDEO_EXTENSIONS else ".mp4"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / f"input{suffix}"
        input_path.write_bytes(data)
        duration = _probe_video_duration_seconds(ffmpeg, input_path)
        frames = _extract_even_video_frames(ffmpeg, input_path, tmp_dir, max_frames, duration)
        if not frames:
            pattern = str(tmp_dir / "frame_%02d.jpg")
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-vf",
                "fps=1,scale=640:-2",
                "-frames:v",
                str(max_frames),
                "-q:v",
                "4",
                pattern,
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
            except Exception as exc:
                return [], f"视频抽帧失败：{exc}"
            if completed.returncode != 0:
                error = completed.stderr.decode("utf-8", errors="ignore").strip()
                return [], f"视频抽帧失败：{_shorten(error, 220) or 'ffmpeg 未返回成功状态'}"
            frames = [path.read_bytes() for path in sorted(tmp_dir.glob("frame_*.jpg"))[:max_frames]]
        return frames, "" if frames else "视频文件已读取，但没有抽取到关键帧。"

def _probe_video_duration_seconds(ffmpeg: str, input_path: Path) -> float | None:
    command = [ffmpeg, "-i", str(input_path)]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            check=False,
        )
    except Exception:
        return None
    text = completed.stderr.decode("utf-8", errors="ignore")
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return duration if duration > 0 else None

def _extract_even_video_frames(
    ffmpeg: str,
    input_path: Path,
    tmp_dir: Path,
    max_frames: int,
    duration: float | None,
) -> list[bytes]:
    if not duration:
        return []
    timestamps = [
        max(0.0, min(duration - 0.05, duration * (index + 1) / (max_frames + 1)))
        for index in range(max_frames)
    ]
    frames: list[bytes] = []
    for index, timestamp in enumerate(timestamps, start=1):
        output_path = tmp_dir / f"even_frame_{index:02d}.jpg"
        command = [
            ffmpeg,
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(input_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            "-q:v",
            "4",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=12,
                check=False,
            )
        except Exception:
            continue
        if completed.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            frames.append(output_path.read_bytes())
    return frames[:max_frames]

def _image_info(data: bytes) -> tuple[str, int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return ("PNG", width, height)
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return ("GIF", width, height)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_info(data)
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ("WEBP", 0, 0)
    return None

def _jpeg_info(data: bytes) -> tuple[str, int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack(">H", data[index : index + 2])[0]
        if marker in set(range(0xC0, 0xCF)) - {0xC4, 0xC8, 0xCC} and index + 7 < len(data):
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            return ("JPEG", width, height)
        index += max(2, length)
    return None
