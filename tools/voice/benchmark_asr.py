from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any


MODEL_ROOT = Path(os.environ.get("ATRI_ASR_ROOT", r"D:\AtriModels\voice\asr"))
DEFAULT_HOTWORDS = ["亚托莉", "夏生", "萝卜子", "ATRI", "GPT-SoVITS", "NapCat"]
LANGUAGE_NAMES = {"zh": "中文", "en": "英文", "ja": "日文"}


def normalized_characters(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return [char for char in normalized if char.isalnum()]


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, 1):
        current = [left_index]
        for right_index, right_item in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(expected: str, actual: str) -> float:
    reference = normalized_characters(expected)
    hypothesis = normalized_characters(actual)
    return edit_distance(reference, hypothesis) / max(1, len(reference))


def result_text(result: Any) -> str:
    if isinstance(result, list) and result:
        return result_text(result[0])
    if isinstance(result, dict):
        return str(result.get("text") or "").strip()
    return str(result or "").strip()


def load_cases(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("Benchmark manifest must contain a cases list")
    return [
        {
            "id": str(item["id"]),
            "language": str(item["language"]),
            "text": str(item["text"]),
            "audio": str(Path(str(item["audio"])).expanduser().resolve()),
        }
        for item in cases
        if isinstance(item, dict)
    ]


def sensevoice_runner(model_path: Path, device: str):
    from funasr import AutoModel

    model = AutoModel(
        model=str(model_path),
        trust_remote_code=True,
        device=device,
        disable_update=True,
    )

    def transcribe(case: dict[str, str]) -> tuple[str, dict[str, Any]]:
        result = model.generate(
            input=case["audio"],
            cache={},
            language=case["language"],
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
        )
        raw = result_text(result)
        text = re.sub(r"<\|[^|>]+\|>", "", raw).strip()
        return text, {}

    return transcribe


def funasr_nano_runner(model_path: Path, device: str):
    from funasr import AutoModel

    model = AutoModel(
        model=str(model_path),
        trust_remote_code=True,
        device=device,
        disable_update=True,
    )

    def transcribe(case: dict[str, str]) -> tuple[str, dict[str, Any]]:
        result = model.generate(
            input=[case["audio"]],
            cache={},
            batch_size=1,
            hotwords=DEFAULT_HOTWORDS,
            language=LANGUAGE_NAMES[case["language"]],
            itn=True,
        )
        return result_text(result), {}

    return transcribe


def faster_whisper_runner(model_path: Path, device: str):
    from faster_whisper import WhisperModel

    compute_type = "int8_float16" if device == "cuda" else "int8"
    model = WhisperModel(str(model_path), device=device, compute_type=compute_type)

    def transcribe(case: dict[str, str]) -> tuple[str, dict[str, Any]]:
        segments, info = model.transcribe(
            case["audio"],
            language=case["language"],
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=True,
            hotwords=", ".join(DEFAULT_HOTWORDS),
        )
        resolved = list(segments)
        text = "".join(segment.text for segment in resolved).strip()
        avg_logprob = (
            sum(float(segment.avg_logprob) for segment in resolved) / len(resolved)
            if resolved
            else -10.0
        )
        return text, {
            "detected_language": info.language,
            "language_probability": info.language_probability,
            "avg_logprob": avg_logprob,
        }

    return transcribe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["sensevoice", "funasr-nano", "whisper-turbo"], required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.engine == "sensevoice":
        model_path = MODEL_ROOT.parent / "modelscope" / "models" / "iic--SenseVoiceSmall" / "snapshots" / "master"
        runner_factory = sensevoice_runner
        device = "cuda:0" if args.device == "cuda" else "cpu"
    elif args.engine == "funasr-nano":
        model_path = MODEL_ROOT / "fun-asr-nano-2512"
        runner_factory = funasr_nano_runner
        device = "cuda:0" if args.device == "cuda" else "cpu"
    else:
        model_path = MODEL_ROOT / "faster-whisper-large-v3-turbo"
        runner_factory = faster_whisper_runner
        device = args.device
    if not model_path.is_dir():
        raise FileNotFoundError(model_path)

    load_started = time.perf_counter()
    runner = runner_factory(model_path, device)
    load_seconds = time.perf_counter() - load_started
    results = []
    for case in load_cases(args.manifest.resolve()):
        started = time.perf_counter()
        text, details = runner(case)
        elapsed = time.perf_counter() - started
        row = {
            **case,
            "recognized": text,
            "cer": character_error_rate(case["text"], text),
            "elapsed_seconds": elapsed,
            **details,
        }
        results.append(row)
        print(
            f"[{args.engine}] {case['id']} cer={row['cer']:.3f} "
            f"time={elapsed:.2f}s text={text}",
            flush=True,
        )
    report = {
        "engine": args.engine,
        "model": str(model_path),
        "load_seconds": load_seconds,
        "average_cer": sum(item["cer"] for item in results) / max(1, len(results)),
        "average_seconds": sum(item["elapsed_seconds"] for item in results) / max(1, len(results)),
        "results": results,
    }
    output = args.output or Path("data/runtime") / f"asr-benchmark-{args.engine}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("engine", "load_seconds", "average_cer", "average_seconds")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
