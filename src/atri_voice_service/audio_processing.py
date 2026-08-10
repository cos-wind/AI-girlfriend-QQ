from __future__ import annotations

import subprocess
import wave
from array import array
from dataclasses import dataclass
import math
from pathlib import Path
import re
from uuid import uuid4

from .process_utils import hidden_subprocess_options


class AudioPreprocessError(RuntimeError):
    pass


class AudioValidationError(AudioPreprocessError):
    pass


@dataclass(frozen=True)
class PreparedAudio:
    path: Path
    temporary: bool = False
    duration_seconds: float | None = None

    def cleanup(self) -> None:
        if self.temporary:
            self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProcessedAudio:
    path: Path
    duration_seconds: float
    gain_db: float
    trimmed_leading_seconds: float
    trimmed_trailing_seconds: float


def prepare_speech_audio(
    source: Path,
    cache_dir: Path,
    *,
    enabled: bool = True,
    max_duration_seconds: float = 300.0,
) -> PreparedAudio:
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise AudioPreprocessError(f"语音文件不存在：{source}")
    if not enabled:
        return PreparedAudio(source)

    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise AudioPreprocessError(f"无法加载内置 FFmpeg：{exc}") from exc

    cache_dir = Path(cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"asr-normalized-{uuid4().hex}.wav"
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=90,
            **hidden_subprocess_options(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        output.unlink(missing_ok=True)
        raise AudioPreprocessError(f"音频标准化失败：{exc}") from exc
    if completed.returncode != 0 or not output.is_file():
        output.unlink(missing_ok=True)
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise AudioPreprocessError(f"音频标准化失败：{detail or 'FFmpeg 未生成输出'}")

    try:
        with wave.open(str(output), "rb") as audio:
            duration = audio.getnframes() / max(1, audio.getframerate())
            valid_format = (
                audio.getnchannels() == 1
                and audio.getframerate() == 16000
                and audio.getsampwidth() == 2
            )
    except (OSError, wave.Error) as exc:
        output.unlink(missing_ok=True)
        raise AudioPreprocessError(f"标准化音频无效：{exc}") from exc
    if not valid_format:
        output.unlink(missing_ok=True)
        raise AudioPreprocessError("标准化音频不是 16kHz 单声道 PCM")
    if duration < 0.08:
        output.unlink(missing_ok=True)
        raise AudioValidationError("语音过短，无法可靠识别")
    if duration > max(1.0, max_duration_seconds):
        output.unlink(missing_ok=True)
        raise AudioValidationError(f"语音超过 {int(max_duration_seconds)} 秒限制")
    return PreparedAudio(output, temporary=True, duration_seconds=duration)


def postprocess_synthesized_audio(
    path: Path,
    *,
    target_rms_dbfs: float = -22.0,
    max_gain_db: float = 6.0,
    peak_ceiling_dbfs: float = -1.5,
) -> ProcessedAudio:
    path = Path(path).expanduser().resolve()
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            raw = source.readframes(frame_count)
    except (OSError, wave.Error) as exc:
        raise AudioPreprocessError(f"合成音频后处理失败：{exc}") from exc
    if channels < 1 or sample_width != 2 or compression != "NONE" or not raw:
        raise AudioPreprocessError("合成音频不是可处理的 PCM16 WAV")

    samples = array("h")
    samples.frombytes(raw)
    frame_samples = max(channels, int(sample_rate * 0.01) * channels)
    threshold = 10 ** (-45.0 / 20.0) * 32767
    active_frames: list[int] = []
    frame_rms: list[float] = []
    for start in range(0, len(samples), frame_samples):
        chunk = samples[start : start + frame_samples]
        if not chunk:
            continue
        rms = math.sqrt(sum(int(value) * int(value) for value in chunk) / len(chunk))
        frame_rms.append(rms)
        if rms >= threshold:
            active_frames.append(len(frame_rms) - 1)
    if not active_frames:
        raise AudioPreprocessError("合成音频没有检测到有效语音")

    first_active = _stable_active_frame(frame_rms, threshold, forward=True)
    last_active = _stable_active_frame(frame_rms, threshold, forward=False)
    lead_padding_frames = 20
    trail_padding_frames = 20
    start_frame = max(0, first_active - lead_padding_frames)
    end_frame = min(len(frame_rms), last_active + trail_padding_frames + 1)
    start_sample = start_frame * frame_samples
    end_sample = min(len(samples), end_frame * frame_samples)
    trimmed = samples[start_sample:end_sample]
    original_duration = frame_count / max(1, sample_rate)
    duration = len(trimmed) / max(1, sample_rate * channels)
    if duration < 0.2:
        raise AudioPreprocessError("合成音频有效语音过短")
    if original_duration >= 8.0 and duration / original_duration < 0.2:
        raise AudioPreprocessError("合成音频包含异常长静音，已拒绝发送")

    active_square_sum = 0
    active_sample_count = 0
    for index in range(first_active, last_active + 1):
        if frame_rms[index] < threshold:
            continue
        start = index * frame_samples
        chunk = samples[start : min(len(samples), start + frame_samples)]
        active_square_sum += sum(int(value) * int(value) for value in chunk)
        active_sample_count += len(chunk)
    active_rms = math.sqrt(active_square_sum / max(1, active_sample_count))
    current_rms_dbfs = 20 * math.log10(max(active_rms / 32767.0, 1e-9))
    desired_gain_db = min(max_gain_db, target_rms_dbfs - current_rms_dbfs)
    peak = max(abs(value) for value in trimmed)
    peak_gain_db = peak_ceiling_dbfs - 20 * math.log10(max(peak / 32767.0, 1e-9))
    gain_db = min(desired_gain_db, peak_gain_db)
    gain = 10 ** (gain_db / 20.0)
    processed = array(
        "h",
        (
            max(-32768, min(32767, round(value * gain)))
            for value in trimmed
        ),
    )

    temporary = path.with_suffix(".postprocess.tmp.wav")
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(sample_rate)
            output.writeframes(processed.tobytes())
        temporary.replace(path)
    except (OSError, wave.Error) as exc:
        temporary.unlink(missing_ok=True)
        raise AudioPreprocessError(f"合成音频写回失败：{exc}") from exc

    duration = len(processed) / max(1, sample_rate * channels)
    return ProcessedAudio(
        path=path,
        duration_seconds=duration,
        gain_db=gain_db,
        trimmed_leading_seconds=start_sample / max(1, sample_rate * channels),
        trimmed_trailing_seconds=max(0.0, original_duration - end_sample / max(1, sample_rate * channels)),
    )


def validate_synthesized_speech_timing(
    text: str,
    language: str,
    duration_seconds: float,
) -> None:
    value = str(text or "")
    duration = max(0.0, float(duration_seconds))
    normalized_language = str(language or "auto").lower()
    if normalized_language == "en":
        units = len(re.findall(r"[A-Za-z0-9]+", value))
        maximum_duration = max(3.0, units / 1.05 + 1.2)
    else:
        units = len(
            re.findall(r"[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9]", value)
        )
        maximum_duration = max(2.8, units / 1.7 + 0.8)
    if units and duration > maximum_duration:
        raise AudioPreprocessError(
            "合成音频出现异常拖长"
            f"（{units} 个发音单位生成 {duration:.1f} 秒，上限 {maximum_duration:.1f} 秒）"
        )


def _stable_active_frame(frame_rms: list[float], threshold: float, *, forward: bool) -> int:
    required = 3
    indices = range(len(frame_rms)) if forward else range(len(frame_rms) - 1, -1, -1)
    run: list[int] = []
    for index in indices:
        if frame_rms[index] >= threshold:
            run.append(index)
            if len(run) >= required:
                return min(run) if forward else max(run)
        else:
            run.clear()
    active = [index for index, rms in enumerate(frame_rms) if rms >= threshold]
    return active[0] if forward else active[-1]
