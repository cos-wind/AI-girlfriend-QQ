from __future__ import annotations

import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIXER = PROJECT_ROOT / "tools" / "voice" / "mix_singing_audio.py"


def _write_tone(path: Path, *, channels: int, frequency: float) -> None:
    sample_rate = 44_100
    frames = bytearray()
    for index in range(sample_rate // 5):
        sample = int(4_000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", sample) * channels)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def _write_silence(path: Path, *, channels: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(b"\0\0" * channels * (44_100 // 5))


def _peak(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        width = source.getsampwidth()
        raw = source.readframes(source.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        data = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        data = ((data ^ 0x800000) - 0x800000).astype(np.float32) / 8_388_608.0
    else:
        raise AssertionError(f"unexpected sample width: {width}")
    return float(np.max(np.abs(data)))


def test_mixer_preserves_stereo_instrumental(tmp_path: Path) -> None:
    vocal = tmp_path / "vocal.wav"
    instrumental = tmp_path / "instrumental.wav"
    mixed = tmp_path / "mixed.wav"
    _write_tone(vocal, channels=1, frequency=220)
    _write_tone(instrumental, channels=2, frequency=440)

    subprocess.run(
        [
            sys.executable,
            str(MIXER),
            "--vocal",
            str(vocal),
            "--instrumental",
            str(instrumental),
            "--output",
            str(mixed),
            "--reverb",
            "0",
        ],
        check=True,
    )

    with wave.open(str(mixed), "rb") as result:
        assert result.getnchannels() == 2
        assert result.getsampwidth() == 3

    assert _peak(mixed) <= 10 ** (-1.0 / 20.0) + 1e-3


def test_mixer_does_not_reintroduce_unconverted_harmony_by_default(tmp_path: Path) -> None:
    vocal = tmp_path / "vocal.wav"
    instrumental = tmp_path / "instrumental.wav"
    harmony = tmp_path / "harmony.wav"
    mixed = tmp_path / "mixed.wav"
    _write_silence(vocal, channels=1)
    _write_silence(instrumental, channels=2)
    _write_tone(harmony, channels=2, frequency=330)

    subprocess.run(
        [
            sys.executable,
            str(MIXER),
            "--vocal",
            str(vocal),
            "--instrumental",
            str(instrumental),
            "--harmony",
            str(harmony),
            "--output",
            str(mixed),
            "--reverb",
            "0",
        ],
        check=True,
    )

    assert _peak(mixed) < 1e-4
