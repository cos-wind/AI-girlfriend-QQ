from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Iterable


KEY_NAMES = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def choose_section_count(duration: float, requested: int = 0) -> int:
    if requested in {3, 4, 5}:
        return requested
    if duration < 120:
        return 3
    if duration < 240:
        return 4
    return 5


def choose_delivery_boundaries(
    duration: float,
    bar_times: Iterable[float],
    *,
    target_seconds: float = 30.0,
) -> list[float]:
    """为 QQ 语音挑选约 30 秒的完整乐句边界。

    每个候选边界都落在 4/4 小节位置；在 20--45 秒的可接受窗口内，
    选择最接近目标时长的点，防止把唱词或鼓点硬切断。
    """
    total = max(0.0, float(duration))
    if total <= 0.1:
        return [0.0]
    target = min(45.0, max(20.0, float(target_seconds or 30.0)))
    bars = sorted({round(max(0.0, min(total, float(value))), 3) for value in bar_times})
    if not bars:
        bars = [round(value, 3) for value in range(0, int(math.ceil(total)) + 1, 4)]
    if not bars or bars[0] > 0:
        bars.insert(0, 0.0)
    if bars[-1] < total:
        bars.append(total)
    boundaries = [0.0]
    while total - boundaries[-1] > target * 1.45:
        start = boundaries[-1]
        candidates = [point for point in bars if start + 20.0 <= point <= min(total - 12.0, start + 45.0)]
        if not candidates:
            candidates = [point for point in bars if point > start + 1.0]
        if not candidates:
            break
        boundary = min(candidates, key=lambda point: abs((point - start) - target))
        if boundary <= start:
            break
        boundaries.append(round(boundary, 3))
    if boundaries[-1] < total:
        boundaries.append(round(total, 3))
    return boundaries


def plan_delivery_segments(source: Path, *, target_seconds: float = 30.0) -> dict[str, object]:
    """分析完整歌曲并返回用于导出 QQ 语音片段的边界。"""
    import imageio_ffmpeg
    try:
        import librosa
        import numpy as np
    except ModuleNotFoundError:
        return _fallback_delivery_segments(
            source,
            target_seconds=target_seconds,
            imageio_ffmpeg=imageio_ffmpeg,
        )

    sample_rate = 22_050
    hop_length = 512
    with tempfile.TemporaryDirectory(prefix="atri-delivery-segments-") as temporary:
        analysis_wav = Path(temporary) / "source.wav"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source.resolve()), "-ac", "1", "-ar", str(sample_rate),
                "-c:a", "pcm_s16le", str(analysis_wav),
            ],
            check=True,
            timeout=180,
        )
        audio, sample_rate = librosa.load(str(analysis_wav), sr=sample_rate, mono=True)
    duration = float(librosa.get_duration(y=audio, sr=sample_rate))
    if duration <= 0.1:
        raise ValueError("歌曲时长过短，无法切分")
    onset = librosa.onset.onset_strength(y=audio, sr=sample_rate, hop_length=hop_length)
    _tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset, sr=sample_rate, hop_length=hop_length, trim=False
    )
    beat_times = librosa.frames_to_time(np.asarray(beat_frames, dtype=int), sr=sample_rate, hop_length=hop_length)
    bars = [0.0, *beat_times[::4].tolist(), duration] if beat_times.size else []
    boundaries = choose_delivery_boundaries(duration, bars, target_seconds=target_seconds)
    segments = [
        {
            "index": index,
            "label": "完整乐句片段",
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "duration_seconds": round(end - start, 3),
        }
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
        if end - start >= 1.0
    ]
    return {
        "version": 1,
        "method": "beat+bar delivery segmentation",
        "duration_seconds": round(duration, 3),
        "target_seconds": target_seconds,
        "segments": segments,
    }


def _fallback_delivery_segments(
    source: Path,
    *,
    target_seconds: float,
    imageio_ffmpeg,
) -> dict[str, object]:
    """缺少 librosa 时用轻量时长和近似小节边界完成分段。"""
    duration = _probe_audio_duration(source, imageio_ffmpeg)
    if duration <= 0.1:
        raise ValueError("歌曲时长过短，无法分段")
    bar_times = [float(value) for value in range(0, int(math.ceil(duration)) + 1, 4)]
    boundaries = choose_delivery_boundaries(
        duration,
        bar_times,
        target_seconds=target_seconds,
    )
    segments = [
        {
            "index": index,
            "label": "兼容模式 / 近似小节边界",
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "duration_seconds": round(end - start, 3),
        }
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
        if end - start >= 1.0
    ]
    return {
        "version": 1,
        "method": "bar-approximation fallback (librosa unavailable)",
        "duration_seconds": round(duration, 3),
        "target_seconds": target_seconds,
        "segments": segments,
    }


def _probe_audio_duration(source: Path, imageio_ffmpeg) -> float:
    """优先用标准库读取 WAV，其他格式通过 ffmpeg 探测时长。"""
    if source.suffix.lower() == ".wav":
        try:
            with wave.open(str(source), "rb") as handle:
                frame_rate = handle.getframerate()
                frame_count = handle.getnframes()
            if frame_rate > 0:
                return frame_count / frame_rate
        except (OSError, wave.Error):
            pass
    process = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(source.resolve())],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        process.stdout + process.stderr,
    )
    if not match:
        raise ValueError("无法读取歌曲时长，请检查音频文件是否完整")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def snap_boundaries(
    raw_boundaries: Iterable[float],
    bar_times: Iterable[float],
    *,
    duration: float,
    section_count: int,
) -> list[float]:
    raw = list(raw_boundaries)
    bars = sorted({max(0.0, min(duration, float(value))) for value in bar_times})
    if not bars:
        bars = [duration * index / section_count for index in range(section_count + 1)]
    minimum = max(2.0, duration / max(section_count * 2.5, 1))
    maximum = duration / max(section_count, 1) * 1.6
    snapped = [0.0]
    for index in range(1, section_count):
        target = raw[index] if index < len(raw) - 1 else duration * index / section_count
        remaining = section_count - index
        lower = snapped[-1] + minimum
        upper = min(duration - remaining * minimum, snapped[-1] + maximum)
        candidates = [value for value in bars if lower <= value <= upper]
        boundary = min(candidates, key=lambda value: abs(value - target)) if candidates else target
        snapped.append(round(max(lower, min(upper, boundary)), 3))
    snapped.append(round(duration, 3))
    return snapped


def _estimate_key(chroma_mean) -> str:
    import numpy as np

    chroma = np.asarray(chroma_mean, dtype=float)
    if not np.any(chroma):
        return "未知"
    scores: list[tuple[float, str]] = []
    for root, name in enumerate(KEY_NAMES):
        for profile, suffix in ((MAJOR_PROFILE, "大调"), (MINOR_PROFILE, "小调")):
            rotated = np.roll(np.asarray(profile, dtype=float), root)
            score = float(np.corrcoef(chroma, rotated)[0, 1])
            if math.isfinite(score):
                scores.append((score, f"{name} {suffix}"))
    return max(scores, default=(0.0, "未知"))[1]


def analyze_song(source: Path, requested_sections: int = 0) -> dict[str, object]:
    import imageio_ffmpeg
    import librosa
    import numpy as np

    sample_rate = 22_050
    hop_length = 512
    with tempfile.TemporaryDirectory(prefix="atri-structure-") as temporary:
        analysis_wav = Path(temporary) / "source.wav"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source.resolve()),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(analysis_wav),
            ],
            check=True,
        )
        audio, sample_rate = librosa.load(str(analysis_wav), sr=sample_rate, mono=True)
    duration = float(librosa.get_duration(y=audio, sr=sample_rate))
    if duration <= 0.1:
        raise ValueError("歌曲时长过短，无法分析乐理结构")
    section_count = choose_section_count(duration, requested_sections)

    onset = librosa.onset.onset_strength(y=audio, sr=sample_rate, hop_length=hop_length)
    tempo_value, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=sample_rate,
        hop_length=hop_length,
        trim=False,
    )
    tempo_array = np.asarray(tempo_value).reshape(-1)
    tempo = float(tempo_array[0]) if tempo_array.size else 0.0
    beat_frames = np.asarray(beat_frames, dtype=int)
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate, hop_length=hop_length)

    harmonic = librosa.effects.harmonic(audio)
    chroma = librosa.feature.chroma_stft(y=harmonic, sr=sample_rate, hop_length=hop_length)
    mfcc = librosa.feature.mfcc(y=audio, sr=sample_rate, n_mfcc=8, hop_length=hop_length)
    rms = librosa.feature.rms(y=audio, hop_length=hop_length)
    frame_count = min(chroma.shape[1], mfcc.shape[1], rms.shape[1])
    features = np.vstack((chroma[:, :frame_count], mfcc[:, :frame_count], rms[:, :frame_count]))
    features = librosa.util.normalize(features, axis=1)

    raw_boundaries = [duration * index / section_count for index in range(section_count + 1)]
    if beat_frames.size >= section_count * 2:
        fixed_beats = librosa.util.fix_frames(beat_frames, x_min=0, x_max=frame_count)
        try:
            synchronized = librosa.util.sync(features, fixed_beats, aggregate=np.median)
            clustered = librosa.segment.agglomerative(synchronized, section_count)
            clustered_frames = [fixed_beats[min(int(index), len(fixed_beats) - 1)] for index in clustered]
            clustered_times = librosa.frames_to_time(
                clustered_frames,
                sr=sample_rate,
                hop_length=hop_length,
            ).tolist()
            if len(clustered_times) == section_count:
                raw_boundaries = [0.0, *clustered_times[1:], duration]
        except (ValueError, IndexError):
            pass

    if beat_times.size:
        bar_times = [0.0, *beat_times[::4].tolist(), duration]
    else:
        bar_times = raw_boundaries
    boundaries = snap_boundaries(
        raw_boundaries,
        bar_times,
        duration=duration,
        section_count=section_count,
    )

    energy_by_section: list[float] = []
    for start, end in zip(boundaries, boundaries[1:]):
        left = max(0, int(start * sample_rate))
        right = min(len(audio), max(left + 1, int(end * sample_rate)))
        energy_by_section.append(float(np.sqrt(np.mean(np.square(audio[left:right])))))
    climax = max(range(section_count), key=energy_by_section.__getitem__) if section_count > 2 else -1

    sections: list[dict[str, object]] = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if index == 0:
            label = "前奏 / 第一乐段"
        elif index == section_count - 1:
            label = "尾奏 / 结束乐段"
        elif index == climax:
            label = "高潮 / 副歌候选"
        else:
            label = f"主段 {index} / 过渡候选"
        sections.append(
            {
                "index": index + 1,
                "label": label,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "duration_seconds": round(end - start, 3),
                "reason": "边界已吸附到节拍/小节，并参考和声、音色与能量变化",
            }
        )

    return {
        "version": 1,
        "method": "beat+bar+chroma+mfcc+agglomerative",
        "duration_seconds": round(duration, 3),
        "tempo_bpm": round(tempo, 2),
        "estimated_key": _estimate_key(np.mean(chroma, axis=1)),
        "meter_hint": "4/4 小节候选",
        "section_count": section_count,
        "sections": sections,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sections", type=int, default=0)
    args = parser.parse_args()

    result = analyze_song(args.source, args.sections)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[ATRI] 乐理分析完成：{result['section_count']} 段 · "
        f"{result['tempo_bpm']} BPM · {result['estimated_key']}",
        flush=True,
    )
    for section in result["sections"]:
        print(
            f"[ATRI] 第 {section['index']} 段 {section['label']}："
            f"{section['start_seconds']:.2f}s - {section['end_seconds']:.2f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
