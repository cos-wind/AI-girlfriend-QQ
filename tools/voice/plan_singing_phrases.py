from __future__ import annotations

import argparse
import json
from pathlib import Path

import soundfile as sf

from singing_audio_engineering import build_phrase_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="ATRI 乐句与换气点规划")
    parser.add_argument("--vocal", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-seconds", type=float, default=3.0)
    args = parser.parse_args()

    print("[ATRI_PROGRESS] 8% 读取分离人声", flush=True)
    audio, sample_rate = sf.read(args.vocal.resolve(), dtype="float32", always_2d=False)
    analysis = json.loads(args.analysis.resolve().read_text(encoding="utf-8-sig"))
    print("[ATRI_PROGRESS] 45% 检测换气点与低能量边界", flush=True)
    plan = build_phrase_plan(
        audio,
        int(sample_rate),
        analysis,
        context_seconds=args.context_seconds,
    )
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[ATRI_PROGRESS] 100% 已规划 {len(plan['phrases'])} 个乐句、"
        f"{len(plan['render_groups'])} 个资源安全推理组",
        flush=True,
    )


if __name__ == "__main__":
    main()
