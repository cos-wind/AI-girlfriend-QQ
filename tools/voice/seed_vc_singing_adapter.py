from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-vc-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pitch-shift", type=float, default=0.0)
    parser.add_argument("--diffusion-steps", type=int, default=35)
    args = parser.parse_args()

    root = args.seed_vc_root.resolve()
    inference = root / "inference.py"
    if not inference.is_file():
        raise FileNotFoundError(f"Seed-VC inference.py 不存在：{inference}")
    with tempfile.TemporaryDirectory(prefix="atri-seed-vc-") as temporary:
        output_dir = Path(temporary)
        command = [
            sys.executable,
            str(inference),
            "--source",
            str(args.source.resolve()),
            "--target",
            str(args.reference.resolve()),
            "--output",
            str(output_dir),
            "--diffusion-steps",
            str(max(10, min(50, args.diffusion_steps))),
            "--length-adjust",
            "1.0",
            "--inference-cfg-rate",
            "0.7",
            "--f0-condition",
            "True",
            "--auto-f0-adjust",
            "False",
            "--semi-tone-shift",
            str(round(max(-12.0, min(12.0, args.pitch_shift)))),
            "--fp16",
            "True",
        ]
        subprocess.run(command, cwd=root, check=True)
        candidates = sorted(
            output_dir.glob("*.wav"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("Seed-VC 没有生成 WAV")
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], args.output.resolve())


if __name__ == "__main__":
    main()
