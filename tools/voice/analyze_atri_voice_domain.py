from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import torch
import torch.nn.functional as functional
import torchaudio


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ROOT = Path(r"D:\AtriModels\voice")
DEFAULT_HANDCRAFTED_ROOT = Path.home() / "Music" / "ATRI训练音频素材" / "手搓音频素材"


class SpeakerEncoder:
    def __init__(self, model_root: Path) -> None:
        source_root = PROJECT_ROOT / "data" / "runtime" / "gpt-sovits" / "source"
        encoder_root = source_root / "GPT_SoVITS" / "eres2net"
        sys.path.insert(0, str(encoder_root))
        from ERes2NetV2 import ERes2NetV2
        import kaldi as Kaldi

        checkpoint = (
            model_root
            / "base"
            / "gpt-sovits"
            / "pretrained_models"
            / "sv"
            / "pretrained_eres2netv2w24s4ep4.ckpt"
        )
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        self.kaldi = Kaldi
        model = ERes2NetV2(baseWidth=24, scale=4, expansion=4)
        model.load_state_dict(torch.load(checkpoint, map_location="cpu"))
        self.model = model.eval()

    def encode(self, audio: torch.Tensor, sample_rate: int) -> torch.Tensor:
        if audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)
        if sample_rate != 16_000:
            audio = torchaudio.functional.resample(audio, sample_rate, 16_000)
        feature = self.kaldi.fbank(
            audio,
            num_mel_bins=80,
            sample_frequency=16_000,
            dither=0,
        ).unsqueeze(0)
        with torch.inference_mode():
            embedding = self.model.forward3(feature)
        return functional.normalize(embedding.float().flatten(), dim=0)


def _active_audio(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float]:
    if samples.size == 0:
        return samples, 1.0
    frame_length = max(256, int(sample_rate * 0.025))
    hop_length = max(128, int(sample_rate * 0.010))
    rms = librosa.feature.rms(
        y=samples,
        frame_length=frame_length,
        hop_length=hop_length,
        center=True,
    )[0]
    peak_rms = float(np.max(rms, initial=0.0))
    threshold = max(10 ** (-50.0 / 20.0), peak_rms * 10 ** (-35.0 / 20.0))
    active = np.flatnonzero(rms >= threshold)
    if active.size == 0:
        return samples, 1.0
    start = max(0, int(active[0] * hop_length - frame_length // 2))
    end = min(samples.size, int(active[-1] * hop_length + frame_length))
    trimmed = samples[start:end]
    silence_ratio = 1.0 - (trimmed.size / max(1, samples.size))
    return trimmed, max(0.0, min(1.0, silence_ratio))


def _acoustic_metrics(audio: torch.Tensor, sample_rate: int) -> dict[str, Any]:
    mono = audio.mean(dim=0).detach().cpu().numpy().astype(np.float32)
    active, silence_ratio = _active_audio(mono, sample_rate)
    if active.size == 0:
        active = mono
    rms = float(np.sqrt(np.mean(np.square(active), dtype=np.float64)))
    peak = float(np.max(np.abs(active), initial=0.0))
    clipping_ratio = float(np.mean(np.abs(active) >= 0.999)) if active.size else 0.0
    analysis_rate = 16_000
    analysis = librosa.resample(active, orig_sr=sample_rate, target_sr=analysis_rate)
    f0 = librosa.yin(
        analysis,
        fmin=65.0,
        fmax=700.0,
        sr=analysis_rate,
        frame_length=1024,
        hop_length=160,
    )
    voiced = f0[np.isfinite(f0) & (f0 >= 65.0) & (f0 <= 700.0)]
    centroid = librosa.feature.spectral_centroid(y=analysis, sr=analysis_rate)[0]
    return {
        "duration_seconds": round(mono.size / max(1, sample_rate), 3),
        "active_seconds": round(active.size / max(1, sample_rate), 3),
        "silence_ratio": round(silence_ratio, 4),
        "rms_dbfs": round(20.0 * math.log10(max(rms, 1e-9)), 2),
        "peak_dbfs": round(20.0 * math.log10(max(peak, 1e-9)), 2),
        "clipping_ratio": round(clipping_ratio, 6),
        "pitch_median_hz": round(float(np.median(voiced)), 2) if voiced.size else None,
        "pitch_p10_hz": round(float(np.percentile(voiced, 10)), 2) if voiced.size else None,
        "pitch_p90_hz": round(float(np.percentile(voiced, 90)), 2) if voiced.size else None,
        "spectral_centroid_hz": round(float(np.mean(centroid)), 2),
    }


def _audio_paths(root: Path) -> list[Path]:
    extensions = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in extensions),
        key=lambda path: path.name.casefold(),
    )


def analyze(
    handcrafted_root: Path,
    comparisons: list[Path],
    model_root: Path,
) -> dict[str, Any]:
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    encoder = SpeakerEncoder(model_root)
    source_paths = _audio_paths(handcrafted_root)
    if not source_paths:
        raise RuntimeError(f"No audio found under {handcrafted_root}")

    embeddings: dict[str, torch.Tensor] = {}
    rows: list[dict[str, Any]] = []
    for group, paths in (
        ("handcrafted", source_paths),
        ("comparison", [path for path in comparisons if path.is_file()]),
    ):
        for path in paths:
            audio, sample_rate = torchaudio.load(str(path))
            key = str(path.resolve())
            embeddings[key] = encoder.encode(audio, sample_rate)
            rows.append(
                {
                    "group": group,
                    "name": path.stem,
                    "path": key,
                    "sample_rate": sample_rate,
                    "channels": int(audio.shape[0]),
                    **_acoustic_metrics(audio, sample_rate),
                }
            )
            print(f"[{group}] {path.name}", flush=True)

    handcrafted_keys = [row["path"] for row in rows if row["group"] == "handcrafted"]
    source_embeddings = torch.stack([embeddings[key] for key in handcrafted_keys])
    centroid = functional.normalize(source_embeddings.mean(dim=0), dim=0)
    pairwise = source_embeddings @ source_embeddings.T
    pair_mask = ~torch.eye(pairwise.shape[0], dtype=torch.bool)
    pair_values = pairwise[pair_mask]
    for row in rows:
        embedding = embeddings[row["path"]]
        row["similarity_to_handcrafted_centroid"] = round(
            float(functional.cosine_similarity(embedding, centroid, dim=0).item()),
            4,
        )
        source_similarities = source_embeddings @ embedding
        nearest_index = int(torch.argmax(source_similarities).item())
        nearest_source = next(
            source for source in rows if source["path"] == handcrafted_keys[nearest_index]
        )
        row["nearest_handcrafted"] = nearest_source["name"]
        row["nearest_handcrafted_similarity"] = round(
            float(source_similarities[nearest_index].item()),
            4,
        )

    handcrafted_rows = [row for row in rows if row["group"] == "handcrafted"]
    def aggregate(field: str) -> dict[str, float]:
        values = [float(row[field]) for row in handcrafted_rows if row.get(field) is not None]
        return {
            "mean": round(float(np.mean(values)), 3),
            "median": round(float(np.median(values)), 3),
            "p10": round(float(np.percentile(values, 10)), 3),
            "p90": round(float(np.percentile(values, 90)), 3),
        }

    return {
        "handcrafted_root": str(handcrafted_root.resolve()),
        "handcrafted_count": len(handcrafted_rows),
        "handcrafted_pairwise_similarity": {
            "mean": round(float(pair_values.mean().item()), 4),
            "minimum": round(float(pair_values.min().item()), 4),
            "maximum": round(float(pair_values.max().item()), 4),
        },
        "handcrafted_acoustics": {
            field: aggregate(field)
            for field in (
                "duration_seconds",
                "active_seconds",
                "silence_ratio",
                "rms_dbfs",
                "pitch_median_hz",
                "spectral_centroid_hz",
            )
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handcrafted-root", type=Path, default=DEFAULT_HANDCRAFTED_ROOT)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--compare", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "runtime" / "atri-voice-domain.json",
    )
    args = parser.parse_args()
    report = analyze(args.handcrafted_root, list(args.compare), args.model_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Report: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
