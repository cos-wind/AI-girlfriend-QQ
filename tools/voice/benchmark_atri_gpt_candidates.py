from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_atri_v2pro_candidates import (
    API_ROOT,
    CASES,
    GPT_WEIGHT,
    MODEL_ROOT,
    OUTPUT_ROOT,
    REFERENCE_AUDIO,
    REFERENCE_TEXT,
    VOICE_SERVICE_ROOT,
    error_rate,
    request_json,
    set_weight,
    transcribe,
)


SOVITS_WEIGHT = (
    MODEL_ROOT
    / "candidates"
    / "atri-official-v2pro-curated"
    / "atri-official-v2pro-curated_e1_s884.pth"
)
GPT_OUTPUT_ROOT = OUTPUT_ROOT / "gpt-candidates"


def gpt_candidates() -> dict[str, Path]:
    root = MODEL_ROOT / "candidates" / "atri-official-v2pro-curated"
    available = {
        path.stem.rsplit("-e", 1)[-1]: path
        for path in root.glob("atri-official-v2pro-curated-e*.ckpt")
    }
    selected = {"base": GPT_WEIGHT}
    for epoch in ("2", "4", "6", "8"):
        if epoch in available:
            selected[f"gpt-e{epoch}"] = available[epoch]
    return selected


def synthesize(gpt_weight: Path, case: Any, destination: Path) -> None:
    set_weight("set_sovits_weights", SOVITS_WEIGHT)
    set_weight("set_gpt_weights", gpt_weight)
    payload = {
        "text": case.text,
        "text_lang": case.language,
        "ref_audio_path": str(REFERENCE_AUDIO),
        "prompt_text": REFERENCE_TEXT,
        "prompt_lang": "ja",
        "media_type": "wav",
        "streaming_mode": False,
        "text_split_method": "cut5",
        "top_k": 15,
        "top_p": 0.9,
        "temperature": 0.8,
        "speed_factor": 0.967,
        "fragment_interval": 0.311,
        "repetition_penalty": 1.35,
        "seed": 19 if case.language == "zh" else 42,
    }
    request = urllib.request.Request(
        f"{API_ROOT}/tts",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        audio = response.read()
        content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type:
        raise RuntimeError(audio.decode("utf-8", errors="replace"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(audio)


def main() -> None:
    for required in (GPT_WEIGHT, SOVITS_WEIGHT, REFERENCE_AUDIO):
        if not required.is_file():
            raise FileNotFoundError(required)
    health = request_json(f"{VOICE_SERVICE_ROOT}/health")
    active = health.get("tts", {}).get("active_weights")
    active_before = tuple(active) if isinstance(active, list) and len(active) == 2 else None
    results: list[dict[str, Any]] = []
    try:
        for candidate_id, weight in gpt_candidates().items():
            print(f"[candidate] {candidate_id}", flush=True)
            for case in CASES:
                output = GPT_OUTPUT_ROOT / candidate_id / f"{case.id}.wav"
                synthesize(weight, case, output)
                transcript = transcribe(output, case.language)
                rate = error_rate(case.text, transcript, case.language)
                results.append(
                    {
                        "candidate": candidate_id,
                        "weight": str(weight),
                        "case": case.id,
                        "language": case.language,
                        "expected": case.text,
                        "transcript": transcript,
                        "error_rate": round(rate, 4),
                        "audio_path": str(output),
                    }
                )
                print(f"  {case.id}: error={rate:.4f}, asr={transcript}", flush=True)
    finally:
        if active_before and all(active_before):
            set_weight("set_sovits_weights", Path(str(active_before[1])))
            set_weight("set_gpt_weights", Path(str(active_before[0])))

    summaries = []
    for candidate_id in gpt_candidates():
        rows = [row for row in results if row["candidate"] == candidate_id]
        summaries.append(
            {
                "candidate": candidate_id,
                "mean_error_rate": round(
                    sum(row["error_rate"] for row in rows) / len(rows),
                    4,
                ),
                "language_error_rates": {
                    language: round(
                        sum(row["error_rate"] for row in rows if row["language"] == language)
                        / max(1, sum(row["language"] == language for row in rows)),
                        4,
                    )
                    for language in ("ja", "zh", "en")
                },
            }
        )
    summaries.sort(key=lambda row: row["mean_error_rate"])
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sovits_weight": str(SOVITS_WEIGHT),
        "summaries": summaries,
        "results": results,
    }
    GPT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    report = GPT_OUTPUT_ROOT / "benchmark.json"
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[ready] {report}", flush=True)


if __name__ == "__main__":
    main()
