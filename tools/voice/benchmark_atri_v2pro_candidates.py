from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as functional
import torchaudio


PROJECT_DIR = Path(__file__).resolve().parents[2]
MODEL_ROOT = Path(os.environ.get("ATRI_MODEL_ROOT", r"D:\AtriModels\voice"))
TRAINING_ROOT = MODEL_ROOT / "training" / "atri-official-v2pro-curated"
OUTPUT_ROOT = TRAINING_ROOT / "benchmark"
SOURCE_DIR = (
    Path.home()
    / "Music"
    / "ATRI训练音频素材"
    / "atri参考音频素材"
    / "atri参考音频素材"
)
GPT_WEIGHT = MODEL_ROOT / "base" / "gpt-sovits" / "pretrained_models" / "s1v3.ckpt"
SV_WEIGHT = (
    MODEL_ROOT
    / "base"
    / "gpt-sovits"
    / "pretrained_models"
    / "sv"
    / "pretrained_eres2netv2w24s4ep4.ckpt"
)
API_ROOT = "http://127.0.0.1:9880"
VOICE_SERVICE_ROOT = "http://127.0.0.1:8790"
REFERENCE_AUDIO = SOURCE_DIR / "ATR_b101_015.wav"
REFERENCE_TEXT = "わたしはマスターの所有物ですので。勝手に売買するのは違法です"


@dataclass(frozen=True)
class Case:
    id: str
    language: str
    text: str


CASES = (
    Case("ja-gentle", "ja", "マスター、今日もあなたのそばにいさせてください。"),
    Case("ja-neutral", "ja", "新しい一日が始まりました。何から始めましょうか。"),
    Case("zh-gentle", "zh", "主人，今天也请让我陪在你身边。"),
    Case("zh-neutral", "zh", "新的一天开始了，我们先做什么呢？"),
    Case("en-gentle", "en", "Master, please let me stay by your side today."),
    Case("en-neutral", "en", "A new day has begun. What should we do first?"),
)


def candidates() -> dict[str, Path]:
    new_root = MODEL_ROOT / "candidates" / "atri-official-v2pro-curated"
    items = {
        "voidshine-e8": (
            MODEL_ROOT
            / "candidates"
            / "voidshine-atri-v2pro"
            / "ATR_e8_s3952.pth"
        )
    }
    for path in sorted(new_root.glob("*.pth")):
        match = re.search(r"_e(\d+)_", path.name)
        key = f"curated-e{match.group(1)}" if match else path.stem
        items[key] = path
    return items


def request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 180,
) -> dict[str, Any]:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def set_weight(endpoint: str, path: Path) -> None:
    query = urllib.parse.urlencode({"weights_path": str(path)})
    request_json(f"{API_ROOT}/{endpoint}?{query}", timeout=180)


def synthesize(weight: Path, case: Case, destination: Path) -> None:
    set_weight("set_sovits_weights", weight)
    set_weight("set_gpt_weights", GPT_WEIGHT)
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
    with wave.open(str(destination), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    if duration <= 0.2:
        raise RuntimeError(f"Invalid synthesis output: {destination}")


def transcribe(path: Path, language: str) -> str:
    result = request_json(
        f"{VOICE_SERVICE_ROOT}/v1/transcribe",
        {"audio_path": str(path), "language": language},
        timeout=300,
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "ASR failed"))
    return str(result.get("text") or "").strip()


def normalized_text(text: str, language: str) -> str:
    value = text.casefold()
    if language == "en":
        return " ".join(re.findall(r"[a-z0-9']+", value))
    return "".join(character for character in value if character.isalnum())


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def error_rate(expected: str, actual: str, language: str) -> float:
    expected_normalized = normalized_text(expected, language)
    actual_normalized = normalized_text(actual, language)
    if language == "en":
        reference = expected_normalized.split()
        hypothesis = actual_normalized.split()
    else:
        reference = list(expected_normalized)
        hypothesis = list(actual_normalized)
    return edit_distance(reference, hypothesis) / max(1, len(reference))


class SpeakerEncoder:
    def __init__(self) -> None:
        source_root = PROJECT_DIR / "data" / "runtime" / "gpt-sovits" / "source"
        import sys

        sys.path.insert(0, str(source_root / "GPT_SoVITS" / "eres2net"))
        from ERes2NetV2 import ERes2NetV2
        import kaldi as Kaldi

        self.kaldi = Kaldi
        model = ERes2NetV2(baseWidth=24, scale=4, expansion=4)
        model.load_state_dict(torch.load(SV_WEIGHT, map_location="cpu"))
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model = model.eval().to(self.device)

    def encode(self, path: Path) -> torch.Tensor:
        audio, sample_rate = torchaudio.load(str(path))
        if audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)
        if sample_rate != 16000:
            audio = torchaudio.functional.resample(audio, sample_rate, 16000)
        feature = self.kaldi.fbank(
            audio,
            num_mel_bins=80,
            sample_frequency=16000,
            dither=0,
        ).unsqueeze(0)
        with torch.inference_mode():
            embedding = self.model.forward3(feature.to(self.device))
        return functional.normalize(embedding.float().cpu().flatten(), dim=0)


def held_out_references() -> list[Path]:
    report = json.loads(
        (TRAINING_ROOT / "corpus-audit.json").read_text(encoding="utf-8")
    )
    rows = [
        row
        for row in report["rows"]
        if row["accepted"]
        and row["split"] == "eval"
        and 2.0 <= float(row["duration_seconds"]) <= 8.0
    ]
    rows.sort(key=lambda row: row["filename"])
    if len(rows) < 20:
        raise RuntimeError("Not enough held-out references")
    stride = max(1, len(rows) // 20)
    return [SOURCE_DIR / rows[index]["filename"] for index in range(0, len(rows), stride)][
        :20
    ]


def capture_active_weights() -> tuple[str, str] | None:
    health = request_json(f"{VOICE_SERVICE_ROOT}/health")
    weights = health.get("tts", {}).get("active_weights")
    if isinstance(weights, list) and len(weights) == 2 and all(weights):
        return str(weights[0]), str(weights[1])
    return None


def main() -> None:
    for required in (GPT_WEIGHT, SV_WEIGHT, REFERENCE_AUDIO):
        if not required.is_file():
            raise FileNotFoundError(required)
    active_before = capture_active_weights()
    encoder = SpeakerEncoder()
    reference_embeddings = torch.stack(
        [encoder.encode(path) for path in held_out_references()]
    )
    reference_centroid = functional.normalize(reference_embeddings.mean(dim=0), dim=0)
    results: list[dict[str, Any]] = []
    try:
        for candidate_id, weight in candidates().items():
            if not weight.is_file():
                raise FileNotFoundError(weight)
            print(f"[candidate] {candidate_id}", flush=True)
            for case in CASES:
                output = OUTPUT_ROOT / candidate_id / f"{case.id}.wav"
                synthesize(weight, case, output)
                transcript = transcribe(output, case.language)
                embedding = encoder.encode(output)
                similarity = float(
                    functional.cosine_similarity(
                        embedding.unsqueeze(0),
                        reference_centroid.unsqueeze(0),
                    ).item()
                )
                result = {
                    "candidate": candidate_id,
                    "weight": str(weight),
                    "case": case.id,
                    "language": case.language,
                    "expected": case.text,
                    "transcript": transcript,
                    "error_rate": round(
                        error_rate(case.text, transcript, case.language), 4
                    ),
                    "speaker_similarity": round(similarity, 4),
                    "audio_path": str(output),
                }
                results.append(result)
                print(
                    f"  {case.id}: similarity={similarity:.4f}, "
                    f"error={result['error_rate']:.4f}, asr={transcript}",
                    flush=True,
                )
    finally:
        if active_before:
            set_weight("set_sovits_weights", Path(active_before[1]))
            set_weight("set_gpt_weights", Path(active_before[0]))

    summaries: list[dict[str, Any]] = []
    for candidate_id in candidates():
        rows = [row for row in results if row["candidate"] == candidate_id]
        summaries.append(
            {
                "candidate": candidate_id,
                "mean_speaker_similarity": round(
                    sum(row["speaker_similarity"] for row in rows) / len(rows), 4
                ),
                "mean_error_rate": round(
                    sum(row["error_rate"] for row in rows) / len(rows), 4
                ),
                "language_error_rates": {
                    language: round(
                        sum(
                            row["error_rate"]
                            for row in rows
                            if row["language"] == language
                        )
                        / sum(row["language"] == language for row in rows),
                        4,
                    )
                    for language in ("ja", "zh", "en")
                },
            }
        )
    summaries.sort(
        key=lambda row: (-row["mean_speaker_similarity"], row["mean_error_rate"])
    )
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reference_audio": str(REFERENCE_AUDIO),
        "reference_text": REFERENCE_TEXT,
        "held_out_reference_count": len(reference_embeddings),
        "active_weights_restored": list(active_before) if active_before else None,
        "summaries": summaries,
        "results": results,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_ROOT / "benchmark.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("[ready]", report_path, flush=True)


if __name__ == "__main__":
    main()
