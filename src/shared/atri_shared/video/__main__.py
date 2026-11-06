"""Offline extraction diagnostic: python -m atri_shared.video <file>."""
import argparse
import asyncio
import json
from pathlib import Path
import time

from . import FFmpegFrameExtractor, VideoOptions


def main() -> int:
    parser = argparse.ArgumentParser(description="独立视频抽帧诊断；不连接平台、不加载 OCR/视觉模型")
    parser.add_argument("file", type=Path)
    parser.add_argument("--frames", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--seconds", type=float, default=24)
    parser.add_argument("--output", type=Path, help="可选：在新目录内保存 JPEG；不覆盖已有目录")
    args = parser.parse_args()
    try:
        options = VideoOptions(max_frames=args.frames, extraction_seconds=args.seconds)
        if args.file.stat().st_size > options.max_bytes:
            raise ValueError("文件超过 80 MB 读取上限")
        result = asyncio.run(FFmpegFrameExtractor().extract(
            args.file.read_bytes(), args.file.suffix, options, deadline=time.monotonic() + args.seconds))
        report = {
            "duration_seconds": result.duration_seconds,
            "sample_positions_seconds": [f.timestamp_seconds for f in result.frames],
            "frame_count": len(result.frames),
            "issues": [{"stage": i.stage, "code": i.code, "message": i.message} for i in result.issues],
        }
        if args.output is not None:
            args.output.mkdir(parents=True, exist_ok=False)
            for index, frame in enumerate(result.frames, 1):
                (args.output / f"frame-{index:02d}.jpg").write_bytes(frame.data)
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if result.frames else 1
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
