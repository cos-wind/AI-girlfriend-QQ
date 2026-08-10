from __future__ import annotations

import math
import struct
import subprocess
import sys
import wave
from pathlib import Path


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

