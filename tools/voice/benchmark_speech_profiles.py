from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


async def benchmark(
    base_url: str,
    manifest_path: Path,
    profiles: list[str],
    output_dir: Path,
) -> Path:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("语音基准清单必须包含非空 cases 数组")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    timeout = httpx.Timeout(240, connect=5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for profile in profiles:
            for case in cases:
                request = {
                    "profile": profile,
                    "text": str(case["text"]),
                    "language": str(case.get("language") or "auto"),
                    "emotion": str(case.get("emotion") or "neutral"),
                    "intensity": float(case.get("intensity", 0.55)),
                    "prefer_original": False,
                    "quality_gate": True,
                    "quality_retries": 1,
                }
                started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{base_url.rstrip('/')}/v1/synthesize",
                        json=request,
                    )
                    response.raise_for_status()
                    result = response.json()
                    elapsed = time.perf_counter() - started
                    audio_path = Path(str(result["audio_path"])).resolve()
                    row = {
                        "profile": profile,
                        "case_id": str(case["id"]),
                        "language": request["language"],
                        "emotion": request["emotion"],
                        "text": request["text"],
                        "ok": True,
                        "elapsed_seconds": round(elapsed, 3),
                        "audio_path": str(audio_path),
                        "quality": result.get("quality"),
                    }
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    row = {
                        "profile": profile,
                        "case_id": str(case.get("id") or ""),
                        "language": request["language"],
                        "emotion": request["emotion"],
                        "text": request["text"],
                        "ok": False,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "error": str(exc),
                    }
                rows.append(row)
                print(
                    f"[{profile}] {row['case_id']} "
                    f"{'ok' if row['ok'] else 'failed'} "
                    f"{row['elapsed_seconds']:.2f}s",
                    flush=True,
                )
    report = _build_report(base_url, manifest_path, profiles, rows)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = output_dir / f"speech-profile-benchmark-{timestamp}.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def _build_report(
    base_url: str,
    manifest_path: Path,
    profiles: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for profile in profiles:
        selected = [row for row in rows if row["profile"] == profile]
        succeeded = [row for row in selected if row["ok"]]
        error_rates = [
            float(row["quality"]["error_rate"])
            for row in succeeded
            if isinstance(row.get("quality"), dict)
            and isinstance(row["quality"].get("error_rate"), (int, float))
        ]
        summaries.append(
            {
                "profile": profile,
                "cases": len(selected),
                "succeeded": len(succeeded),
                "success_rate": round(len(succeeded) / max(1, len(selected)), 4),
                "average_seconds": round(
                    statistics.fmean(row["elapsed_seconds"] for row in succeeded),
                    3,
                )
                if succeeded
                else None,
                "average_asr_error_rate": round(statistics.fmean(error_rates), 4)
                if error_rates
                else None,
            }
        )
    return {
        "service_url": base_url,
        "manifest": str(manifest_path),
        "profiles": profiles,
        "summaries": summaries,
        "results": rows,
        "human_review": {
            "scale": "1-5",
            "fields": [
                "speaker_similarity",
                "naturalness",
                "emotion_fit",
                "pronunciation",
            ],
            "note": "自动指标只筛查漏字和耗时，最终模型选择必须补充盲听评分。",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--service-url",
        default="http://127.0.0.1:8790",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/voice/speech-benchmark.json"),
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=[
            "atri-official-v2pro-curated",
            "atri-2dipw",
            "atri-voidshine",
        ],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/runtime"),
    )
    args = parser.parse_args()
    output = asyncio.run(
        benchmark(
            args.service_url,
            args.manifest.resolve(),
            args.profiles,
            args.output_dir.resolve(),
        )
    )
    print(f"报告已保存：{output}", flush=True)


if __name__ == "__main__":
    main()
