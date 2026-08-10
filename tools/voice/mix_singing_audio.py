from __future__ import annotations

import argparse
import math
import wave
from pathlib import Path

import numpy as np


def _read_audio(path: Path, sample_rate: int = 44_100) -> np.ndarray:
    from pedalboard.io import AudioFile

    with AudioFile(str(path.resolve())).resampled_to(sample_rate) as stream:
        return np.asarray(stream.read(stream.frames), dtype=np.float32)


def _fit_channels(audio: np.ndarray, channels: int, frames: int) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data[np.newaxis, :]
    if data.shape[0] != channels:
        data = np.repeat(data.mean(axis=0, keepdims=True), channels, axis=0)
    if data.shape[1] < frames:
        data = np.pad(data, ((0, 0), (0, frames - data.shape[1])))
    return data[:, :frames]


def _adaptive_vocal_dsp(
    vocal: np.ndarray,
    sample_rate: int,
    presence_db: float,
    deesser_strength: float,
) -> np.ndarray:
    """Small STFT dynamic-EQ and de-esser before the Pedalboard chain."""

    data = vocal.reshape(-1)
    if len(data) < 1024:
        return data
    frame_size = 2048
    hop = 512
    window = np.hanning(frame_size).astype(np.float32)
    padded = np.pad(data, (frame_size, frame_size))
    output = np.zeros_like(padded, dtype=np.float64)
    weights = np.zeros_like(padded, dtype=np.float64)
    frequencies = np.fft.rfftfreq(frame_size, 1 / sample_rate)
    presence = (frequencies >= 2500) & (frequencies <= 5200)
    sibilance = (frequencies >= 5200) & (frequencies <= 10500)
    for start in range(0, len(padded) - frame_size + 1, hop):
        frame = padded[start : start + frame_size] * window
        spectrum = np.fft.rfft(frame)
        power = np.square(np.abs(spectrum)) + 1e-12
        total = float(power.sum())
        presence_ratio = float(power[presence].sum() / total)
        sibilance_ratio = float(power[sibilance].sum() / total)
        dynamic_cut = max(0.0, presence_ratio - 0.14) * 18.0
        presence_gain = 10.0 ** ((presence_db - dynamic_cut) / 20.0)
        deess_cut = max(0.0, sibilance_ratio - 0.10) * 26.0 * deesser_strength
        spectrum[presence] *= presence_gain
        spectrum[sibilance] *= 10.0 ** (-deess_cut / 20.0)
        rendered = np.fft.irfft(spectrum, n=frame_size).real
        output[start : start + frame_size] += rendered * window
        weights[start : start + frame_size] += np.square(window)
    weights[weights < 1e-8] = 1.0
    return (output / weights)[frame_size : frame_size + len(data)].astype(np.float32)


def _ducking_envelope(vocal: np.ndarray, sample_rate: int, ducking_db: float) -> np.ndarray:
    absolute = np.abs(vocal).astype(np.float64)
    width = max(1, round(sample_rate * 0.08))
    left = width // 2
    right = width - 1 - left
    padded = np.pad(absolute, (left, right), mode="edge")
    cumulative = np.concatenate(([0.0], np.cumsum(padded, dtype=np.float64)))
    level = ((cumulative[width:] - cumulative[:-width]) / width).astype(np.float32)
    reference = float(np.quantile(level, 0.9)) if len(level) else 0.0
    if reference <= 1e-6:
        return np.ones_like(level)
    activity = np.clip(level / reference, 0.0, 1.0)
    return np.power(10.0, (-float(ducking_db) * activity) / 20.0).astype(np.float32)


def _write_pcm16(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    data = np.asarray(audio, dtype=np.float32)
    data = np.clip(data, -1.0, 1.0)
    interleaved = (data.T.reshape(-1) * 32767.0).astype("<i2")
    path.resolve().parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path.resolve()), "wb") as stream:
        stream.setnchannels(data.shape[0])
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(interleaved.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="ATRI Pedalboard 工程化后期混音")
    parser.add_argument("--vocal", type=Path, required=True)
    parser.add_argument("--instrumental", type=Path, required=True)
    parser.add_argument("--harmony", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instrumental-gain-db", type=float, default=-1.7)
    parser.add_argument("--instrumental-gain", type=float)
    parser.add_argument("--vocal-gain-db", type=float, default=0.0)
    parser.add_argument("--eq-presence-db", type=float, default=-1.0)
    parser.add_argument("--eq-air-db", type=float, default=1.2)
    parser.add_argument("--compressor-threshold-db", type=float, default=-18.0)
    parser.add_argument("--compressor-ratio", type=float, default=2.5)
    parser.add_argument("--deesser-strength", type=float, default=0.35)
    parser.add_argument("--saturation-db", type=float, default=1.0)
    parser.add_argument("--reverb", type=float, default=0.08)
    parser.add_argument("--delay-ms", type=float, default=90.0)
    parser.add_argument("--delay-mix", type=float, default=0.04)
    parser.add_argument("--ducking-db", type=float, default=3.0)
    parser.add_argument("--limiter-db", type=float, default=-1.0)
    args = parser.parse_args()

    from pedalboard import (
        Compressor,
        Delay,
        Distortion,
        Gain,
        HighpassFilter,
        HighShelfFilter,
        Limiter,
        Pedalboard,
        Reverb,
    )

    sample_rate = 44_100
    print("[ATRI_PROGRESS] 8% 读取单声道人声与立体声伴奏", flush=True)
    vocal = _read_audio(args.vocal, sample_rate).mean(axis=0)
    instrumental = _read_audio(args.instrumental, sample_rate)
    frames = max(len(vocal), instrumental.shape[1])
    vocal = _fit_channels(vocal, 1, frames)[0]
    instrumental = _fit_channels(instrumental, 2, frames)

    print("[ATRI_PROGRESS] 28% 动态 EQ 与齿音抑制", flush=True)
    vocal = _adaptive_vocal_dsp(
        vocal,
        sample_rate,
        max(-9.0, min(6.0, args.eq_presence_db)),
        max(0.0, min(1.0, args.deesser_strength)),
    )
    reverb = max(0.0, min(0.45, args.reverb))
    delay_mix = max(0.0, min(0.35, args.delay_mix))
    vocal_board = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=70.0),
            HighShelfFilter(
                cutoff_frequency_hz=9000.0,
                gain_db=max(-6.0, min(9.0, args.eq_air_db)),
                q=0.7,
            ),
            Compressor(
                threshold_db=max(-40.0, min(-6.0, args.compressor_threshold_db)),
                ratio=max(1.0, min(10.0, args.compressor_ratio)),
                attack_ms=12.0,
                release_ms=110.0,
            ),
            Distortion(drive_db=max(0.0, min(9.0, args.saturation_db))),
            Reverb(
                room_size=0.22,
                damping=0.65,
                wet_level=reverb,
                dry_level=1.0,
                width=0.85,
            ),
            Delay(
                delay_seconds=max(0.0, min(0.5, args.delay_ms / 1000.0)),
                feedback=0.12,
                mix=delay_mix,
            ),
            Gain(gain_db=max(-12.0, min(12.0, args.vocal_gain_db))),
        ]
    )
    print("[ATRI_PROGRESS] 52% Pedalboard 压缩、饱和、混响与延迟", flush=True)
    processed_vocal = np.asarray(vocal_board(vocal[np.newaxis, :], sample_rate), dtype=np.float32)
    if processed_vocal.ndim == 1:
        processed_vocal = processed_vocal[np.newaxis, :]
    vocal_stereo = np.repeat(processed_vocal[:1], 2, axis=0)

    accompaniment_db = max(-18.0, min(6.0, args.instrumental_gain_db))
    if args.instrumental_gain is not None:
        linear = max(0.1, min(1.5, args.instrumental_gain))
        accompaniment_db = 20.0 * math.log10(linear)
    duck = _ducking_envelope(vocal, sample_rate, max(0.0, min(12.0, args.ducking_db)))
    accompaniment = instrumental * duck[np.newaxis, :] * (10.0 ** (accompaniment_db / 20.0))
    mixed = vocal_stereo[:, :frames] + accompaniment[:, :frames]

    if args.harmony and args.harmony.is_file():
        harmony = _fit_channels(_read_audio(args.harmony, sample_rate), 2, frames)
        mixed += harmony * (10.0 ** (-8.0 / 20.0))

    print("[ATRI_PROGRESS] 82% 伴奏 Ducking 与最终限幅", flush=True)
    limiter = Pedalboard(
        [Limiter(threshold_db=max(-6.0, min(-0.1, args.limiter_db)), release_ms=100.0)]
    )
    mixed = np.asarray(limiter(mixed, sample_rate), dtype=np.float32)
    _write_pcm16(args.output, mixed, sample_rate)
    print("[ATRI_PROGRESS] 100% 立体声混音完成", flush=True)


if __name__ == "__main__":
    main()
