from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import imageio_ffmpeg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vocal", type=Path, required=True)
    parser.add_argument("--instrumental", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instrumental-gain", type=float, default=0.82)
    args = parser.parse_args()

    gain = max(0.1, min(1.5, args.instrumental_gain))
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(args.vocal.resolve()),
        "-i",
        str(args.instrumental.resolve()),
        "-filter_complex",
        (
            f"[0:a]volume=1.0[v];[1:a]volume={gain:.3f}[i];"
            "[v][i]amix=inputs=2:duration=shortest:dropout_transition=0,"
            "alimiter=limit=0.93[out]"
        ),
        "-map",
        "[out]",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(args.output.resolve()),
    ]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
