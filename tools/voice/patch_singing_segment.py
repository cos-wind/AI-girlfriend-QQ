from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from singing_audio_engineering import _fit_length, apply_expression, patch_selected_range, quality_report


def _read_mono(path: Path, expected_rate: int | None = None) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path.resolve(), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if expected_rate is not None and sample_rate != expected_rate:
        from scipy.signal import resample_poly

        import math

        divisor = math.gcd(int(sample_rate), int(expected_rate))
        audio = resample_poly(audio, expected_rate // divisor, sample_rate // divisor)
        sample_rate = expected_rate
    return np.asarray(audio, dtype=np.float32), int(sample_rate)


def main() -> None:
    parser = argparse.ArgumentParser(description="ATRI 选区重生成与无损范围替换")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--replacement", type=Path, required=True)
    parser.add_argument("--source-vocal", type=Path, required=True)
    parser.add_argument("--source-context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quality-output", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--context-start", type=float, required=True)
    parser.add_argument("--parameters-json", default="{}")
    args = parser.parse_args()

    base, sample_rate = _read_mono(args.base)
    replacement, _ = _read_mono(args.replacement, sample_rate)
    source_context, _ = _read_mono(args.source_context, sample_rate)
    source, _ = _read_mono(args.source_vocal, sample_rate)
    parameters = json.loads(args.parameters_json)
    print("[ATRI_PROGRESS] 40% 应用选区音色与表现力参数", flush=True)
    # Seed-VC can return a context a few milliseconds longer or shorter. Align
    # the complete context before slicing the selected absolute time range.
    replacement = _fit_length(replacement, len(source_context))
    replacement = apply_expression(replacement, source_context, sample_rate, parameters)
    output = patch_selected_range(
        base,
        replacement,
        sample_rate,
        start_seconds=args.start,
        end_seconds=args.end,
        context_start=args.context_start,
    )
    print("[ATRI_PROGRESS] 75% 检测选区两端接缝", flush=True)
    quality = quality_report(source, output, sample_rate, seam_times=[args.start, args.end])
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output.resolve(), output, sample_rate, subtype="PCM_24")
    args.quality_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.quality_output.resolve().write_text(
        json.dumps(quality, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[ATRI_PROGRESS] 100% 仅选中范围已更新，其余采样保持不变", flush=True)


if __name__ == "__main__":
    main()
