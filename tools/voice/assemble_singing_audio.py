from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from singing_audio_engineering import (
    apply_expression,
    assemble_contextual_parts,
    quality_report,
)


def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return audio
    from scipy.signal import resample_poly

    import math

    divisor = math.gcd(source_rate, target_rate)
    return resample_poly(audio, target_rate // divisor, source_rate // divisor).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description="ATRI 上下文推理片段 overlap-add 与质量检测")
    parser.add_argument("--source-vocal", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--parts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quality-output", type=Path, required=True)
    parser.add_argument("--parameters-json", default="{}")
    args = parser.parse_args()

    plan = json.loads(args.plan.resolve().read_text(encoding="utf-8-sig"))
    parameters = json.loads(args.parameters_json)
    source, sample_rate = sf.read(args.source_vocal.resolve(), dtype="float32", always_2d=False)
    groups = plan.get("render_groups") or []
    parts: list[np.ndarray] = []
    print(f"[ATRI_PROGRESS] 10% 对齐 {len(groups)} 个上下文片段", flush=True)
    for index, _group in enumerate(groups, start=1):
        path = args.parts_dir.resolve() / f"group-{index:02d}-converted.wav"
        audio, part_rate = sf.read(path, dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        parts.append(_resample(np.asarray(audio), int(part_rate), int(sample_rate)))
    converted = assemble_contextual_parts(parts, int(sample_rate), plan)
    converted = apply_expression(converted, source, int(sample_rate), parameters)
    seam_times = [float(group["start_seconds"]) for group in groups[1:]]
    print("[ATRI_PROGRESS] 78% 检测接缝、静音、削波与音高偏差", flush=True)
    quality = quality_report(source, converted, int(sample_rate), seam_times=seam_times)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output.resolve(), converted, int(sample_rate), subtype="PCM_24")
    args.quality_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.quality_output.resolve().write_text(
        json.dumps(quality, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state = "通过" if quality["passed"] else "发现可修复问题"
    print(f"[ATRI_PROGRESS] 100% overlap-add 完成，质量检查：{state}", flush=True)


if __name__ == "__main__":
    main()
