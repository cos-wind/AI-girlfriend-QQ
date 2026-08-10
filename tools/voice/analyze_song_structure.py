from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
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
