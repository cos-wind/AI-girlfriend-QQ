from __future__ import annotations

import math
from typing import Any

import numpy as np


def _mono(audio: np.ndarray) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=0 if data.shape[0] <= 8 else 1)
    return np.nan_to_num(data.reshape(-1), copy=False)


def _frame_rms(audio: np.ndarray, frame_size: int, hop_size: int) -> np.ndarray:
    data = _mono(audio)
    if not len(data):
        return np.zeros(1, dtype=np.float32)
    values: list[float] = []
    for start in range(0, len(data), max(1, hop_size)):
        frame = data[start : start + max(1, frame_size)]
        if not len(frame):
            break
        values.append(float(np.sqrt(np.mean(np.square(frame), dtype=np.float64) + 1e-12)))
    return np.asarray(values, dtype=np.float32)


def _nearest_boundary(
    target: float,
    candidates: list[tuple[float, float]],
    window: float,
) -> tuple[float, str]:
    nearby = [(time, rms) for time, rms in candidates if abs(time - target) <= window]
    if not nearby:
        return target, "music_structure"
    time, _ = min(nearby, key=lambda item: (item[1], abs(item[0] - target)))
    return time, "breath"


def build_phrase_plan(
    vocal_audio: np.ndarray,
    sample_rate: int,
    analysis: dict[str, Any],
    *,
    context_seconds: float = 3.0,
) -> dict[str, Any]:
    """Create fine phrases and 3–5 resource-safe render groups.

    Fine phrases are used for targeted corrections.  The first full render keeps
    3–5 model invocations by grouping them on the existing music-structure
    boundaries; those boundaries are snapped to detected breath/low-energy
    valleys before 2–4 seconds of context is added.
    """

    audio = _mono(vocal_audio)
    if sample_rate <= 0 or not len(audio):
        raise ValueError("人声音频为空")
    duration = float(analysis.get("duration_seconds") or len(audio) / sample_rate)
    duration = min(duration, len(audio) / sample_rate)
    context = max(2.0, min(4.0, float(context_seconds)))
    hop_seconds = 0.05
    hop = max(1, round(sample_rate * hop_seconds))
    rms = _frame_rms(audio, max(hop * 3, 1), hop)
    floor = max(0.0015, float(np.quantile(rms, 0.25)) * 1.35)

    candidates: list[tuple[float, float]] = []
    minimum_gap = max(1, round(0.8 / hop_seconds))
    last_index = -minimum_gap
    for index in range(1, max(1, len(rms) - 1)):
        if rms[index] > floor or rms[index] > rms[index - 1] or rms[index] > rms[index + 1]:
            continue
        if index - last_index < minimum_gap:
            if candidates and rms[index] < candidates[-1][1]:
                candidates[-1] = (round(index * hop_seconds, 3), float(rms[index]))
                last_index = index
            continue
        candidates.append((round(index * hop_seconds, 3), float(rms[index])))
        last_index = index

    raw_sections = analysis.get("sections")
    if not isinstance(raw_sections, list) or not 3 <= len(raw_sections) <= 5:
        count = 4
        raw_sections = [
            {
                "index": index + 1,
                "start_seconds": duration * index / count,
                "end_seconds": duration * (index + 1) / count,
            }
            for index in range(count)
        ]

    group_boundaries: list[tuple[float, str]] = [(0.0, "song_start")]
    for section in raw_sections[:-1]:
        target = float(section.get("end_seconds") or 0)
        boundary, reason = _nearest_boundary(target, candidates, 2.0)
        if boundary - group_boundaries[-1][0] < 2.0:
            boundary, reason = target, "music_structure"
        group_boundaries.append((round(boundary, 3), reason))
    group_boundaries.append((round(duration, 3), "song_end"))

    render_groups: list[dict[str, Any]] = []
    for index in range(len(group_boundaries) - 1):
        start = group_boundaries[index][0]
        end = group_boundaries[index + 1][0]
        render_groups.append(
            {
                "index": index + 1,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "context_start": round(max(0.0, start - context), 3),
                "context_end": round(min(duration, end + context), 3),
                "context_seconds": context,
                "boundary_reason": group_boundaries[index][1],
            }
        )

    fine_boundaries: list[tuple[float, str]] = [(0.0, "song_start")]
    cursor = 0.0
    while duration - cursor > 24.0:
        low = cursor + 8.0
        high = min(duration - 4.0, cursor + 24.0)
        choices = [(time, value) for time, value in candidates if low <= time <= high]
        if choices:
            boundary, _ = min(choices, key=lambda item: item[1])
            reason = "breath"
        else:
            boundary = high
            reason = "phrase_length_guard"
        fine_boundaries.append((round(boundary, 3), reason))
        cursor = boundary
    for boundary, reason in group_boundaries[1:-1]:
        if all(abs(boundary - item[0]) > 1.0 for item in fine_boundaries):
            fine_boundaries.append((boundary, reason))
    fine_boundaries.append((round(duration, 3), "song_end"))
    fine_boundaries = sorted(set(fine_boundaries), key=lambda item: item[0])

    phrases: list[dict[str, Any]] = []
    for index in range(len(fine_boundaries) - 1):
        start = fine_boundaries[index][0]
        end = fine_boundaries[index + 1][0]
        if end - start < 0.25:
            continue
        phrases.append(
            {
                "id": f"phrase-{index + 1:03d}",
                "index": index + 1,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "boundary_reason": fine_boundaries[index][1],
            }
        )

    return {
        "version": 1,
        "duration_seconds": round(duration, 3),
        "f0_engine": "rmvpe",
        "breath_detection": {
            "method": "vocal_rms_valley",
            "threshold": round(floor, 6),
            "candidate_count": len(candidates),
        },
        "phrases": phrases,
        "render_groups": render_groups,
    }


def _fit_length(audio: np.ndarray, target_length: int) -> np.ndarray:
    data = _mono(audio)
    target = max(1, int(target_length))
    if len(data) == target:
        return data.copy()
    if len(data) < 2:
        return np.zeros(target, dtype=np.float32)
    source_positions = np.linspace(0.0, 1.0, len(data), endpoint=True)
    target_positions = np.linspace(0.0, 1.0, target, endpoint=True)
    return np.interp(target_positions, source_positions, data).astype(np.float32)


def assemble_contextual_parts(
    parts: list[np.ndarray],
    sample_rate: int,
    plan: dict[str, Any],
) -> np.ndarray:
    groups = plan.get("render_groups")
    if not isinstance(groups, list) or len(groups) != len(parts):
        raise ValueError("上下文片段数量与推理计划不一致")
    total = max(1, round(float(plan["duration_seconds"]) * sample_rate))
    accumulated = np.zeros(total, dtype=np.float64)
    weights = np.zeros(total, dtype=np.float64)
    for part, group in zip(parts, groups):
        context_start = float(group["context_start"])
        context_end = float(group["context_end"])
        start = float(group["start_seconds"])
        end = float(group["end_seconds"])
        first = max(0, round(context_start * sample_rate))
        last = min(total, round(context_end * sample_rate))
        if last <= first:
            continue
        data = _fit_length(part, last - first)
        fade = np.ones(len(data), dtype=np.float64)
        fade_in = max(0, round((start - context_start) * sample_rate))
        fade_out = max(0, round((context_end - end) * sample_rate))
        if fade_in:
            phase = np.linspace(0.0, math.pi / 2, fade_in, endpoint=False)
            fade[:fade_in] = np.square(np.sin(phase))
        if fade_out:
            phase = np.linspace(math.pi / 2, 0.0, fade_out, endpoint=False)
            fade[-fade_out:] = np.square(np.sin(phase))
        accumulated[first:last] += data[: last - first] * fade
        weights[first:last] += fade
    missing = weights < 1e-8
    weights[missing] = 1.0
    output = accumulated / weights
    output[missing] = 0.0
    return np.clip(output, -1.0, 1.0).astype(np.float32)


def patch_selected_range(
    base_audio: np.ndarray,
    replacement_context: np.ndarray,
    sample_rate: int,
    *,
    start_seconds: float,
    end_seconds: float,
    context_start: float,
    crossfade_seconds: float = 0.03,
) -> np.ndarray:
    base = _mono(base_audio)
    start = max(0, round(float(start_seconds) * sample_rate))
    end = min(len(base), round(float(end_seconds) * sample_rate))
    if end <= start:
        raise ValueError("局部重跑选区无效")
    offset = max(0, round((float(start_seconds) - float(context_start)) * sample_rate))
    replacement = _mono(replacement_context)
    selected = replacement[offset : offset + (end - start)]
    selected = _fit_length(selected, end - start)
    output = base.copy()
    fade_samples = min(round(crossfade_seconds * sample_rate), (end - start) // 4)
    if fade_samples >= 2:
        phase = np.linspace(0.0, math.pi / 2, fade_samples, endpoint=True)
        wet = np.sin(phase)
        dry = np.cos(phase)
        selected[:fade_samples] = base[start : start + fade_samples] * dry + selected[:fade_samples] * wet
        selected[-fade_samples:] = (
            selected[-fade_samples:] * dry + base[end - fade_samples : end] * wet
        )
    output[start:end] = selected
    return np.clip(output, -1.0, 1.0).astype(np.float32)


def _moving_average(audio: np.ndarray, samples: int) -> np.ndarray:
    width = max(1, int(samples))
    if width == 1:
        return audio.copy()
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    left = width // 2
    right = width - 1 - left
    padded = np.pad(data, (left, right), mode="edge")
    cumulative = np.empty(len(padded) + 1, dtype=np.float64)
    cumulative[0] = 0.0
    np.cumsum(padded, dtype=np.float64, out=cumulative[1:])
    return ((cumulative[width:] - cumulative[:-width]) / width).astype(np.float32)


def _apply_vibrato_chunked(audio: np.ndarray, sample_rate: int, amount: float) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    output = np.empty_like(data)
    depth_samples = sample_rate * 0.0007 * amount
    margin = max(2, math.ceil(abs(depth_samples)) + 1)
    chunk_size = 1_000_000
    for start in range(0, len(data), chunk_size):
        end = min(len(data), start + chunk_size)
        positions = np.arange(start, end, dtype=np.float64)
        warped = positions + depth_samples * np.sin(2 * np.pi * 5.4 * positions / sample_rate)
        source_start = max(0, start - margin)
        source_end = min(len(data), end + margin)
        source_positions = np.arange(source_start, source_end, dtype=np.float64)
        output[start:end] = np.interp(
            warped,
            source_positions,
            data[source_start:source_end],
            left=float(data[0]),
            right=float(data[-1]),
        )
    return output


def _shift_spectral_envelope(audio: np.ndarray, semitones: float) -> np.ndarray:
    if abs(semitones) < 0.05 or len(audio) < 512:
        return audio
    frame_size = 1024
    hop = frame_size // 4
    window = np.hanning(frame_size).astype(np.float32)
    padded = np.pad(audio, (frame_size, frame_size))
    output = np.zeros_like(padded, dtype=np.float64)
    weight = np.zeros_like(padded, dtype=np.float64)
    ratio = 2.0 ** (float(semitones) / 12.0)
    bins = frame_size // 2 + 1
    positions = np.arange(bins, dtype=np.float64)
    kernel = np.ones(25, dtype=np.float64) / 25.0
    for start in range(0, len(padded) - frame_size + 1, hop):
        frame = padded[start : start + frame_size] * window
        spectrum = np.fft.rfft(frame)
        magnitude = np.maximum(np.abs(spectrum), 1e-7)
        envelope = np.convolve(np.log(magnitude), kernel, mode="same")
        shifted = np.interp(positions / ratio, positions, envelope, left=envelope[0], right=envelope[-1])
        gain = np.exp(np.clip(shifted - envelope, -1.0, 1.0) * 0.65)
        rendered = np.fft.irfft(spectrum * gain, n=frame_size).real
        output[start : start + frame_size] += rendered * window
        weight[start : start + frame_size] += np.square(window)
    weight[weight < 1e-8] = 1.0
    result = (output / weight)[frame_size : frame_size + len(audio)]
    return result.astype(np.float32)


def apply_expression(
    converted_audio: np.ndarray,
    source_audio: np.ndarray,
    sample_rate: int,
    parameters: dict[str, Any],
) -> np.ndarray:
    converted = _mono(converted_audio)
    source = _fit_length(source_audio, len(converted))
    result = converted.copy()

    breathiness = max(0.0, min(1.0, float(parameters.get("breathiness", 0.08))))
    if breathiness > 0:
        smooth = _moving_average(source, max(3, round(sample_rate / 3500)))
        air = source - smooth
        envelope = _moving_average(np.abs(source), max(3, round(sample_rate * 0.02)))
        active = np.clip((0.09 - envelope) / 0.08, 0.0, 1.0)
        result += air * active * (0.08 * breathiness)

    vibrato = max(0.0, min(1.0, float(parameters.get("vibrato", 0.15))))
    if vibrato > 0.001:
        result = _apply_vibrato_chunked(result, sample_rate, vibrato)

    articulation = max(0.0, min(1.0, float(parameters.get("articulation", 0.60))))
    transient = result - _moving_average(result, max(3, round(sample_rate * 0.0015)))
    result += transient * ((articulation - 0.5) * 0.35)

    formant = max(-4.0, min(4.0, float(parameters.get("formant_shift", 0.0))))
    result = _shift_spectral_envelope(result, formant)
    peak = float(np.max(np.abs(result))) if len(result) else 0.0
    if peak > 0.995:
        result *= 0.995 / peak
    return np.nan_to_num(result).astype(np.float32)


def _rough_pitch(audio: np.ndarray, sample_rate: int) -> float | None:
    data = _mono(audio)
    if len(data) < sample_rate // 5:
        return None
    # A full time-domain autocorrelation of three 44.1 kHz seconds is O(n^2)
    # and can pin the machine during a quality check. Downsample only this
    # independent diagnostic path and use an O(n log n) FFT autocorrelation.
    stride = max(1, int(sample_rate // 8_000))
    effective_rate = float(sample_rate) / stride
    frame = data[::stride][: min(len(data[::stride]), round(effective_rate * 2.0))]
    frame = frame - float(frame.mean())
    if float(np.sqrt(np.mean(frame * frame) + 1e-12)) < 0.005:
        return None
    fft_size = 1 << max(1, (2 * len(frame) - 1).bit_length())
    spectrum = np.fft.rfft(frame, n=fft_size)
    correlation = np.fft.irfft(spectrum * np.conjugate(spectrum), n=fft_size)[: len(frame)]
    # Compensate for fewer overlapping samples at larger lags.
    correlation /= np.maximum(1, np.arange(len(frame), 0, -1, dtype=np.float64))
    minimum = max(1, round(effective_rate / 1000.0))
    maximum = min(len(correlation), round(effective_rate / 65.0))
    if maximum <= minimum:
        return None
    lag = minimum + int(np.argmax(correlation[minimum:maximum]))
    return effective_rate / lag if lag else None


def quality_report(
    source_audio: np.ndarray,
    converted_audio: np.ndarray,
    sample_rate: int,
    *,
    seam_times: list[float] | None = None,
) -> dict[str, Any]:
    source = _mono(source_audio)
    converted = _fit_length(converted_audio, len(source))
    clipping_count = int(np.count_nonzero(np.abs(converted) >= 0.999))

    frame = max(1, round(sample_rate * 0.05))
    source_rms = _frame_rms(source, frame, frame)
    converted_rms = _frame_rms(converted, frame, frame)
    active = source_rms > 0.02
    silent = active & (converted_rms[: len(active)] < 0.002)
    silence_ratio = float(silent.sum() / max(1, active.sum()))

    seam_values: list[float] = []
    for seconds in seam_times or []:
        index = round(float(seconds) * sample_rate)
        if 1 <= index < len(converted):
            seam_values.append(float(abs(converted[index] - converted[index - 1])))
    maximum_seam = max(seam_values, default=0.0)

    source_pitch = _rough_pitch(source, sample_rate)
    converted_pitch = _rough_pitch(converted, sample_rate)
    cents = None
    if source_pitch and converted_pitch:
        cents = float(1200.0 * math.log2(converted_pitch / source_pitch))

    checks = [
        {
            "id": "clipping",
            "label": "削波",
            "passed": clipping_count == 0,
            "value": clipping_count,
            "reference": "0 个样本达到满幅",
        },
        {
            "id": "abnormal_silence",
            "label": "异常静音",
            "passed": silence_ratio <= 0.02,
            "value": round(silence_ratio, 5),
            "reference": "活跃原声中异常静音占比 ≤ 2%",
        },
        {
            "id": "seam_click",
            "label": "接缝爆音",
            "passed": maximum_seam <= 0.12,
            "value": round(maximum_seam, 6),
            "reference": "接缝相邻采样跳变 ≤ 0.12",
        },
        {
            "id": "pitch_deviation",
            "label": "音高偏差",
            "passed": cents is None or abs(cents) <= 80.0,
            "value": None if cents is None else round(cents, 2),
            "reference": "独立粗检中位偏差 ≤ 80 cents；模型 F0 使用 RMVPE",
        },
    ]
    return {
        "passed": all(bool(item["passed"]) for item in checks),
        "checks": checks,
        "sample_rate": sample_rate,
    }
