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
    parser.add_argument("--emotion-strength", type=float, default=0.55)
    parser.add_argument("--articulation", type=float, default=0.60)
    parser.add_argument("--debug-log", type=Path)
    parser.add_argument(
        "--style",
        choices=("natural", "gentle", "bright", "soft"),
        default="natural",
    )
    args = parser.parse_args()

    root = args.seed_vc_root.resolve()
    inference = root / "inference.py"
    if not inference.is_file():
        raise FileNotFoundError(f"Seed-VC inference.py 不存在：{inference}")
    with tempfile.TemporaryDirectory(prefix="atri-seed-vc-") as temporary:
        output_dir = Path(temporary)
        style_cfg = {
            "natural": 0.70,
            "gentle": 0.62,
            "bright": 0.82,
            "soft": 0.56,
        }[args.style]
        style_cfg += (max(0.0, min(1.0, args.emotion_strength)) - 0.55) * 0.30
        style_cfg += (max(0.0, min(1.0, args.articulation)) - 0.60) * 0.12
        style_cfg = max(0.45, min(0.95, style_cfg))
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
            str(style_cfg),
            "--f0-condition",
            "True",
            "--auto-f0-adjust",
            "False",
            "--semi-tone-shift",
            str(round(max(-12.0, min(12.0, args.pitch_shift)))),
            "--fp16",
            "True",
        ]
        print("[ATRI_PROGRESS] 12% Seed-VC 加载 44.1k 歌声模型与 RMVPE", flush=True)
        if args.debug_log:
            args.debug_log.resolve().parent.mkdir(parents=True, exist_ok=True)
            with args.debug_log.resolve().open("a", encoding="utf-8") as debug:
                subprocess.run(
                    command,
                    cwd=root,
                    check=True,
                    stdout=debug,
                    stderr=subprocess.STDOUT,
                )
        else:
            subprocess.run(
                command,
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        print("[ATRI_PROGRESS] 92% RMVPE 条件歌声推理完成", flush=True)
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
