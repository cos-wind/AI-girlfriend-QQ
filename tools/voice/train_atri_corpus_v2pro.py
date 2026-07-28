from __future__ import annotations

import argparse
import audioop
import hashlib
import json
import math
import os
import re
import subprocess
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_DIR / "data" / "runtime" / "gpt-sovits"
SOURCE_DIR = RUNTIME_DIR / "source"
PYTHON = RUNTIME_DIR / ".venv" / "Scripts" / "python.exe"
MODEL_ROOT = Path(os.environ.get("ATRI_MODEL_ROOT", r"D:\AtriModels\voice"))
BASE_ROOT = MODEL_ROOT / "base" / "gpt-sovits" / "pretrained_models"
BASE_GPT = BASE_ROOT / "s1v3.ckpt"
BASE_SOVITS_G = BASE_ROOT / "v2Pro" / "s2Gv2Pro.pth"
BASE_SOVITS_D = BASE_ROOT / "v2Pro" / "s2Dv2Pro.pth"
EXPERIMENT_NAME = "atri-official-v2pro-curated"
TRAINING_ROOT = MODEL_ROOT / "training" / EXPERIMENT_NAME
EXPERIMENT_DIR = TRAINING_ROOT / "experiment"
OUTPUT_DIR = MODEL_ROOT / "candidates" / EXPERIMENT_NAME

MIN_DURATION_SECONDS = 0.8
MAX_DURATION_SECONDS = 12.0
MIN_TEXT_CHARACTERS = 3
MIN_RMS_DBFS = -45.0
MAX_RMS_DBFS = -6.0
MAX_CLIPPED_RATIO = 0.005
EVAL_PERCENT = 5


@dataclass(frozen=True)
class CorpusRow:
    filename: str
    text: str
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width: int
    rms_dbfs: float
    clipped_ratio: float
    sha256: str
    accepted: bool
    split: str
    rejected_reasons: tuple[str, ...]


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("[run]", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=SOURCE_DIR, env=env, check=True)


def runtime_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    python_paths = (
        PROJECT_DIR / "tools" / "voice" / "compat",
        SOURCE_DIR,
        SOURCE_DIR / "GPT_SoVITS",
    )
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join(str(path) for path in python_paths),
            "PATH": f"{SOURCE_DIR};{env.get('PATH', '')}",
        }
    )
    if extra:
        env.update(extra)
    return env


def parse_speaker_list(dataset_dir: Path) -> list[tuple[Path, str]]:
    speaker_list = dataset_dir / ".speaker.list"
    require_file(speaker_list)
    parsed: list[tuple[Path, str]] = []
    for line_number, line in enumerate(
        speaker_list.read_text(encoding="utf-8").splitlines(), start=1
    ):
        parts = line.split("|", 3)
        if len(parts) != 4:
            raise ValueError(f"Invalid speaker list line {line_number}: {line!r}")
        filename = Path(parts[0]).name
        text = parts[3].strip()
        audio_path = dataset_dir / filename
        require_file(audio_path)
        parsed.append((audio_path, text))
    return parsed


def inspect_audio(audio_path: Path, text: str) -> CorpusRow:
    with wave.open(str(audio_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        frames = wav.readframes(frame_count)

    duration = frame_count / sample_rate
    peak = (1 << (sample_width * 8 - 1)) - 1
    rms = audioop.rms(frames, sample_width)
    rms_dbfs = 20 * math.log10(max(rms, 1) / peak)
    clipped_ratio = 0.0
    if sample_width == 2:
        sample_count = max(1, len(frames) // 2)
        clipped_samples = sum(
            1
            for index in range(0, len(frames) - 1, 2)
            if abs(int.from_bytes(frames[index : index + 2], "little", signed=True))
            >= peak
        )
        clipped_ratio = clipped_samples / sample_count

    reasons: list[str] = []
    if not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        reasons.append("duration")
    text_characters = len(re.sub(r"[\W_]+", "", text))
    if text_characters < MIN_TEXT_CHARACTERS:
        reasons.append("text_too_short")
    if channels != 1 or sample_width != 2:
        reasons.append("audio_format")
    if not MIN_RMS_DBFS <= rms_dbfs <= MAX_RMS_DBFS:
        reasons.append("rms")
    if clipped_ratio > MAX_CLIPPED_RATIO:
        reasons.append("clipping")

    content_hash = sha256(audio_path)
    split_value = int(hashlib.sha256(audio_path.name.encode("utf-8")).hexdigest()[:8], 16)
    split = "eval" if split_value % 100 < EVAL_PERCENT else "train"
    return CorpusRow(
        filename=audio_path.name,
        text=text,
        duration_seconds=round(duration, 4),
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        rms_dbfs=round(rms_dbfs, 3),
        clipped_ratio=round(clipped_ratio, 7),
        sha256=content_hash,
        accepted=not reasons,
        split=split if not reasons else "rejected",
        rejected_reasons=tuple(reasons),
    )


def audit(dataset_dir: Path) -> list[CorpusRow]:
    TRAINING_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[CorpusRow] = []
    seen_hashes: set[str] = set()
    for index, (audio_path, text) in enumerate(parse_speaker_list(dataset_dir), start=1):
        row = inspect_audio(audio_path, text)
        if row.accepted and row.sha256 in seen_hashes:
            row = CorpusRow(
                **{
                    **asdict(row),
                    "accepted": False,
                    "split": "rejected",
                    "rejected_reasons": ("duplicate_audio",),
                }
            )
        if row.accepted:
            seen_hashes.add(row.sha256)
        rows.append(row)
        if index % 100 == 0:
            print(f"[audit] {index} clips", flush=True)

    train_rows = [row for row in rows if row.accepted and row.split == "train"]
    eval_rows = [row for row in rows if row.accepted and row.split == "eval"]
    _write_list(TRAINING_ROOT / "train.list", train_rows)
    _write_list(TRAINING_ROOT / "eval.list", eval_rows)

    rejection_counts: dict[str, int] = {}
    for row in rows:
        for reason in row.rejected_reasons:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": str(dataset_dir),
        "speaker_list": str(dataset_dir / ".speaker.list"),
        "engine_revision": _engine_revision(),
        "filters": {
            "duration_seconds": [MIN_DURATION_SECONDS, MAX_DURATION_SECONDS],
            "minimum_text_characters": MIN_TEXT_CHARACTERS,
            "rms_dbfs": [MIN_RMS_DBFS, MAX_RMS_DBFS],
            "maximum_clipped_ratio": MAX_CLIPPED_RATIO,
            "eval_percent": EVAL_PERCENT,
        },
        "summary": {
            "total": len(rows),
            "train": len(train_rows),
            "eval": len(eval_rows),
            "rejected": len(rows) - len(train_rows) - len(eval_rows),
            "train_hours": round(
                sum(row.duration_seconds for row in train_rows) / 3600, 4
            ),
            "eval_hours": round(
                sum(row.duration_seconds for row in eval_rows) / 3600, 4
            ),
            "rejection_counts": rejection_counts,
        },
        "base_models": {
            "gpt": _file_record(BASE_GPT),
            "sovits_generator": _file_record(BASE_SOVITS_G),
            "sovits_discriminator": _file_record(BASE_SOVITS_D),
        },
        "rows": [asdict(row) for row in rows],
    }
    report_path = TRAINING_ROOT / "corpus-audit.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[ready] train={len(train_rows)}, eval={len(eval_rows)}, "
        f"rejected={payload['summary']['rejected']}",
        flush=True,
    )
    return rows


def _write_list(path: Path, rows: list[CorpusRow]) -> None:
    path.write_text(
        "".join(f"{row.filename}|ATRI|JA|{row.text}\n" for row in rows),
        encoding="utf-8",
    )


def _engine_revision() -> str:
    path = SOURCE_DIR / ".atri-source-revision"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256(path) if path.is_file() else "",
    }


def prepare_features(dataset_dir: Path) -> None:
    require_file(PYTHON)
    require_file(BASE_SOVITS_G)
    train_list = TRAINING_ROOT / "train.list"
    require_file(train_list)
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    common = {
        "inp_text": str(train_list),
        "inp_wav_dir": str(dataset_dir),
        "exp_name": EXPERIMENT_NAME,
        "opt_dir": str(EXPERIMENT_DIR),
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": "0",
        "is_half": "True",
        "version": "v2Pro",
    }
    text_env = runtime_environment(
        {
            **common,
            "bert_pretrained_dir": str(
                BASE_ROOT / "chinese-roberta-wwm-ext-large"
            ),
        }
    )
    text_part = EXPERIMENT_DIR / "2-name2text-0.txt"
    text_output = EXPERIMENT_DIR / "2-name2text.txt"
    text_part.unlink(missing_ok=True)
    text_output.unlink(missing_ok=True)
    run(
        [str(PYTHON), "-s", "GPT_SoVITS/prepare_datasets/1-get-text.py"],
        env=text_env,
    )
    require_file(text_part)
    text_part.replace(text_output)

    hubert_env = runtime_environment(
        {
            **common,
            "cnhubert_base_dir": str(BASE_ROOT / "chinese-hubert-base"),
        }
    )
    run(
        [str(PYTHON), "-s", "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"],
        env=hubert_env,
    )
    speaker_env = runtime_environment(
        {
            **common,
            "sv_path": str(
                BASE_ROOT / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt"
            ),
        }
    )
    run(
        [str(PYTHON), "-s", "GPT_SoVITS/prepare_datasets/2-get-sv.py"],
        env=speaker_env,
    )
    expected = len(train_list.read_text(encoding="utf-8").splitlines())
    wav_count = len(list((EXPERIMENT_DIR / "5-wav32k").glob("*.wav")))
    feature_count = len(list((EXPERIMENT_DIR / "4-cnhubert").glob("*.pt")))
    speaker_count = len(list((EXPERIMENT_DIR / "7-sv_cn").glob("*.pt")))
    if (
        wav_count != expected
        or feature_count != expected
        or speaker_count != expected
    ):
        raise RuntimeError(
            f"Incomplete features: wav={wav_count}, hubert={feature_count}, "
            f"speaker={speaker_count}, expected={expected}"
        )
    print(
        f"[ready] acoustic features: {feature_count}, "
        f"speaker features: {speaker_count}",
        flush=True,
    )


def prepare_semantics() -> None:
    require_file(PYTHON)
    require_file(BASE_SOVITS_G)
    require_file(EXPERIMENT_DIR / "2-name2text.txt")
    part_path = EXPERIMENT_DIR / "6-name2semantic-0.tsv"
    output_path = EXPERIMENT_DIR / "6-name2semantic.tsv"
    part_path.unlink(missing_ok=True)
    output_path.unlink(missing_ok=True)
    env = runtime_environment(
        {
            "inp_text": str(TRAINING_ROOT / "train.list"),
            "exp_name": EXPERIMENT_NAME,
            "opt_dir": str(EXPERIMENT_DIR),
            "pretrained_s2G": str(BASE_SOVITS_G),
            "s2config_path": str(
                SOURCE_DIR / "GPT_SoVITS" / "configs" / "s2v2Pro.json"
            ),
            "i_part": "0",
            "all_parts": "1",
            "_CUDA_VISIBLE_DEVICES": "0",
            "is_half": "True",
            "version": "v2Pro",
        }
    )
    run(
        [str(PYTHON), "-s", "GPT_SoVITS/prepare_datasets/3-get-semantic.py"],
        env=env,
    )
    require_file(part_path)
    lines = part_path.read_text(encoding="utf-8").strip().splitlines()
    output_path.write_text(
        "item_name\tsemantic_audio\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    part_path.unlink()
    print(f"[ready] semantic features: {len(lines)}", flush=True)


def train_sovits(epochs: int, batch_size: int) -> list[Path]:
    if not 1 <= epochs <= 12:
        raise ValueError("epochs must be between 1 and 12")
    if not 1 <= batch_size <= 4:
        raise ValueError("batch size must be between 1 and 4")
    for required in (
        PYTHON,
        BASE_SOVITS_G,
        BASE_SOVITS_D,
        EXPERIMENT_DIR / "2-name2text.txt",
    ):
        require_file(required)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPERIMENT_DIR / "logs_s2_v2Pro").mkdir(parents=True, exist_ok=True)

    config_path = SOURCE_DIR / "GPT_SoVITS" / "configs" / "s2v2Pro.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["train"].update(
        {
            "batch_size": batch_size,
            "epochs": epochs,
            "text_low_lr_rate": 0.1,
            "pretrained_s2G": str(BASE_SOVITS_G),
            "pretrained_s2D": str(BASE_SOVITS_D),
            "if_save_latest": 0,
            "if_save_every_weights": True,
            "save_every_epoch": 1,
            "gpu_numbers": "0",
            "grad_ckpt": True,
            "lora_rank": "32",
        }
    )
    config["model"]["version"] = "v2Pro"
    config["data"]["exp_dir"] = str(EXPERIMENT_DIR)
    config["s2_ckpt_dir"] = str(EXPERIMENT_DIR)
    config["save_weight_dir"] = str(OUTPUT_DIR)
    config["name"] = EXPERIMENT_NAME
    config["version"] = "v2Pro"
    generated_config = TRAINING_ROOT / "s2-v2pro-finetune.json"
    generated_config.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    before = set(OUTPUT_DIR.glob("*.pth"))
    run(
        [
            str(PYTHON),
            "-s",
            "GPT_SoVITS/s2_train.py",
            "--config",
            str(generated_config),
        ],
        env=runtime_environment({"version": "v2Pro"}),
    )
    outputs = sorted(set(OUTPUT_DIR.glob("*.pth")) - before)
    if not outputs:
        outputs = sorted(OUTPUT_DIR.glob("*.pth"))
    if not outputs:
        raise RuntimeError(f"Training produced no weights in {OUTPUT_DIR}")
    print("[ready] SoVITS weights:", *(str(path) for path in outputs), sep="\n  ")
    return outputs


def train_gpt(epochs: int, batch_size: int) -> list[Path]:
    if not 1 <= epochs <= 20:
        raise ValueError("epochs must be between 1 and 20")
    for required in (
        PYTHON,
        BASE_GPT,
        EXPERIMENT_DIR / "2-name2text.txt",
        EXPERIMENT_DIR / "6-name2semantic.tsv",
    ):
        require_file(required)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config_path = SOURCE_DIR / "GPT_SoVITS" / "configs" / "s1longer-v2.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["train"].update(
        {
            "batch_size": batch_size,
            "epochs": epochs,
            "save_every_n_epoch": 1,
            "if_save_every_weights": True,
            "if_save_latest": 0,
            "half_weights_save_dir": str(OUTPUT_DIR),
            "exp_name": EXPERIMENT_NAME,
        }
    )
    config["pretrained_s1"] = str(BASE_GPT)
    config["train_semantic_path"] = str(EXPERIMENT_DIR / "6-name2semantic.tsv")
    config["train_phoneme_path"] = str(EXPERIMENT_DIR / "2-name2text.txt")
    config["output_dir"] = str(EXPERIMENT_DIR / "logs_s1_v2Pro")
    generated_config = TRAINING_ROOT / "s1-v2pro-finetune.yaml"
    generated_config.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    before = set(OUTPUT_DIR.glob("*.ckpt"))
    run(
        [
            str(PYTHON),
            "-s",
            "GPT_SoVITS/s1_train.py",
            "--config_file",
            str(generated_config),
        ],
        env=runtime_environment(
            {
                "_CUDA_VISIBLE_DEVICES": "0",
                "hz": "25hz",
                "version": "v2Pro",
            }
        ),
    )
    outputs = sorted(set(OUTPUT_DIR.glob("*.ckpt")) - before)
    if not outputs:
        outputs = sorted(OUTPUT_DIR.glob("*.ckpt"))
    if not outputs:
        raise RuntimeError(f"GPT training produced no weights in {OUTPUT_DIR}")
    print("[ready] GPT weights:", *(str(path) for path in outputs), sep="\n  ")
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit and fine-tune GPT-SoVITS v2Pro on the ATRI corpus."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=(
            Path.home()
            / "Music"
            / "ATRI训练音频素材"
            / "atri参考音频素材"
            / "atri参考音频素材"
        ),
    )
    parser.add_argument(
        "--stage",
        choices=(
            "audit",
            "features",
            "semantics",
            "train-sovits",
            "train-gpt",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--sovits-epochs", type=int, default=4)
    parser.add_argument("--gpt-epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_dir = args.dataset_dir.expanduser().resolve()
    if args.stage in {"audit", "all"}:
        audit(dataset_dir)
    if args.stage in {"features", "all"}:
        prepare_features(dataset_dir)
    if args.stage in {"semantics", "all"}:
        prepare_semantics()
    if args.stage in {"train-sovits", "all"}:
        train_sovits(args.sovits_epochs, args.batch_size)
    if args.stage in {"train-gpt", "all"}:
        train_gpt(args.gpt_epochs, args.batch_size)


if __name__ == "__main__":
    main()
