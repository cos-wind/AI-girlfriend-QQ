from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


def select_reference_excerpt(
    reference_audio: np.ndarray,
    sample_rate: int,
    *,
    seconds: float = 6.0,
) -> tuple[np.ndarray, float]:
    """Select a compact, active reference prompt instead of taking 25 seconds."""

    data = np.asarray(reference_audio, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    data = np.nan_to_num(data.reshape(-1), copy=False)
    target = max(1, round(max(3.0, min(10.0, float(seconds))) * sample_rate))
    if len(data) <= target:
        return np.pad(data, (0, max(0, target - len(data)))).astype(np.float32), 0.0

    frame = max(1, round(sample_rate * 0.05))
    count = len(data) // frame
    framed = data[: count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(np.square(framed), axis=1, dtype=np.float64) + 1e-12)
    active_threshold = max(0.002, float(np.quantile(rms, 0.90)) * 0.08)
    window_frames = max(1, target // frame)
    step_frames = max(1, round(0.25 * sample_rate / frame))
    best_score = float("-inf")
    best_frame = 0
    for start in range(0, max(1, count - window_frames + 1), step_frames):
        values = rms[start : start + window_frames]
        if len(values) < window_frames:
            continue
        active = values[values > active_threshold]
        active_ratio = float(len(active) / len(values))
        median_active = float(np.median(active)) if len(active) else 0.0
        peak = float(np.max(np.abs(framed[start : start + window_frames])))
        clipping_penalty = max(0.0, peak - 0.95) * 8.0
        score = active_ratio * 3.0 + np.log10(median_active + 1e-6) - clipping_penalty
        if score > best_score:
            best_score = score
            best_frame = start
    first = best_frame * frame
    excerpt = data[first : first + target]
    if len(excerpt) < target:
        excerpt = np.pad(excerpt, (0, target - len(excerpt)))
    return excerpt.astype(np.float32), first / sample_rate


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
    parser.add_argument("--reference-seconds", type=float, default=6.0)
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
        import soundfile as sf

        reference_audio, reference_rate = sf.read(
            args.reference.resolve(), dtype="float32", always_2d=False
        )
        excerpt, excerpt_start = select_reference_excerpt(
            reference_audio,
            int(reference_rate),
            seconds=args.reference_seconds,
        )
        prompt_path = output_dir / "prompt" / "atri-reference-prompt.wav"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(prompt_path, excerpt, int(reference_rate), subtype="PCM_24")
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
            str(prompt_path.resolve()),
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
        print(
            f"[ATRI_PROGRESS] 8% 精选 {len(excerpt) / reference_rate:.1f} 秒亚托莉参考（{excerpt_start:.2f}s）",
            flush=True,
        )
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
            (
                path
                for path in output_dir.glob("*.wav")
                if path.resolve() != prompt_path.resolve()
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("Seed-VC 没有生成 WAV")
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], args.output.resolve())


if __name__ == "__main__":
    main()
