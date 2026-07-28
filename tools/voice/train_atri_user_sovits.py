from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_DIR / "data" / "runtime" / "gpt-sovits"
SOURCE_DIR = RUNTIME_DIR / "source"
PYTHON = RUNTIME_DIR / ".venv" / "Scripts" / "python.exe"
FFMPEG = SOURCE_DIR / "ffmpeg.exe"
MODEL_ROOT = Path(os.environ.get("ATRI_MODEL_ROOT", r"D:\AtriModels\voice"))
TRAINING_ROOT = MODEL_ROOT / "training" / "atri-user-jp-v1"
WAV_DIR = TRAINING_ROOT / "wavs"
EXPERIMENT_DIR = TRAINING_ROOT / "experiment"
OUTPUT_DIR = MODEL_ROOT / "candidates" / "atri-user-jp-v1"
BASE_SOVITS = MODEL_ROOT / "candidates" / "2dipw-atri-gpt-sovits" / "atri_e25_s5250.pth"


SAMPLES = (
    {
        "id": "atri_user_01",
        "source": "不可以看.mp3",
        "text": "あっ、ダメです、見ちゃ。",
        "include": True,
        "role": "serious",
    },
    {
        "id": "atri_user_02",
        "source": "嘿嘿，我派上用场了吧.mp3",
        "text": "えへへ、ちゃんと役に立つでしょ？",
        "include": True,
        "role": "happy",
    },
    {
        "id": "atri_user_03",
        "source": "是螃蟹哦.mp3",
        "text": "カニです。",
        "include": True,
        "role": "gentle",
    },
    {
        "id": "atri_user_04",
        "source": "疼.mp3",
        "text": "",
        "include": False,
        "role": "pain",
        "excluded_reason": "Contains non-verbal breathing and has no reliable transcript.",
    },
    {
        "id": "atri_user_05",
        "source": "因为我是高性能的呢.mp3",
        "text": "高性能ですから。",
        "include": True,
        "role": "proud",
    },
    {
        "id": "atri_user_06",
        "source": "有的.mp3",
        "text": "はいです。",
        "include": True,
        "role": "neutral",
    },
    {
        "id": "atri_user_07",
        "source": "再见.mp3",
        "text": "さようなら。",
        "include": True,
        "role": "farewell",
    },
    {
        "id": "atri_user_08",
        "source": "早上好.mp3",
        "text": "おはようございます。",
        "include": True,
        "role": "greeting",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)


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


def prepare_audio(source_dir: Path) -> list[dict[str, Any]]:
    require_file(FFMPEG)
    WAV_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for sample in SAMPLES:
        source = source_dir / str(sample["source"])
        require_file(source)
        output = WAV_DIR / f"{sample['id']}.wav"
        run(
            [
                str(FFMPEG),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-af",
                (
                    "silenceremove=start_periods=1:start_duration=0.03:"
                    "start_threshold=-45dB:start_silence=0.08,"
                    "areverse,"
                    "silenceremove=start_periods=1:start_duration=0.03:"
                    "start_threshold=-45dB:start_silence=0.18,"
                    "areverse"
                ),
                "-ac",
                "1",
                "-ar",
                "32000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
        )
        rows.append(
            {
                **sample,
                "source_path": str(source.resolve()),
                "source_sha256": sha256(source),
                "wav_path": str(output.resolve()),
                "wav_sha256": sha256(output),
            }
        )

    list_path = TRAINING_ROOT / "train.list"
    lines = [
        f"{Path(row['wav_path']).name}|ATRI|JA|{row['text']}"
        for row in rows
        if row["include"]
    ]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_manifest(rows, source_dir)
    print(f"[ready] {len(lines)} training clips: {list_path}", flush=True)
    return rows


def write_manifest(rows: list[dict[str, Any]], source_dir: Path) -> None:
    revision_path = SOURCE_DIR / ".atri-source-revision"
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir.resolve()),
        "engine_revision": revision_path.read_text(encoding="utf-8").strip()
        if revision_path.is_file()
        else "",
        "base_sovits": str(BASE_SOVITS),
        "base_sovits_sha256": sha256(BASE_SOVITS) if BASE_SOVITS.is_file() else "",
        "strategy": "SoVITS-only continual fine-tune; retain the existing 2DIPW GPT weight.",
        "samples": rows,
    }
    (TRAINING_ROOT / "training-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_features() -> None:
    require_file(PYTHON)
    require_file(BASE_SOVITS)
    train_list = TRAINING_ROOT / "train.list"
    require_file(train_list)
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    common = {
        "inp_text": str(train_list),
        "inp_wav_dir": str(WAV_DIR),
        "exp_name": "atri-user-jp-v1",
        "opt_dir": str(EXPERIMENT_DIR),
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": "0",
        "is_half": "True",
        "version": "v1",
    }
    text_env = runtime_environment(
        {
            **common,
            "bert_pretrained_dir": str(
                MODEL_ROOT
                / "base"
                / "gpt-sovits"
                / "pretrained_models"
                / "chinese-roberta-wwm-ext-large"
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
            "cnhubert_base_dir": str(
                MODEL_ROOT
                / "base"
                / "gpt-sovits"
                / "pretrained_models"
                / "chinese-hubert-base"
            ),
        }
    )
    run(
        [str(PYTHON), "-s", "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"],
        env=hubert_env,
    )
    wav_count = len(list((EXPERIMENT_DIR / "5-wav32k").glob("*.wav")))
    feature_count = len(list((EXPERIMENT_DIR / "4-cnhubert").glob("*.pt")))
    expected = sum(bool(sample["include"]) for sample in SAMPLES)
    if wav_count != expected or feature_count != expected:
        raise RuntimeError(
            f"Incomplete features: wav={wav_count}, hubert={feature_count}, expected={expected}"
        )
    print(f"[ready] acoustic features: {feature_count}", flush=True)


def train(epochs: int) -> list[Path]:
    if epochs < 1 or epochs > 4:
        raise ValueError("epochs must be between 1 and 4 for this tiny dataset")
    require_file(PYTHON)
    require_file(BASE_SOVITS)
    require_file(EXPERIMENT_DIR / "2-name2text.txt")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_dir = EXPERIMENT_DIR / "logs_s2_v1"
    log_dir.mkdir(parents=True, exist_ok=True)

    config_path = SOURCE_DIR / "GPT_SoVITS" / "configs" / "s2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["train"].update(
        {
            "batch_size": 2,
            "epochs": epochs,
            "text_low_lr_rate": 0.1,
            "pretrained_s2G": str(BASE_SOVITS),
            "pretrained_s2D": "",
            "if_save_latest": 0,
            "if_save_every_weights": True,
            "save_every_epoch": 1,
            "gpu_numbers": "0",
            "grad_ckpt": False,
            "lora_rank": "32",
        }
    )
    config["model"]["version"] = "v1"
    config["data"]["exp_dir"] = str(EXPERIMENT_DIR)
    config["s2_ckpt_dir"] = str(EXPERIMENT_DIR)
    config["save_weight_dir"] = str(OUTPUT_DIR)
    config["name"] = "atri-user-jp-v1"
    config["version"] = "v1"
    generated_config = TRAINING_ROOT / "s2-finetune.json"
    generated_config.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    before = set(OUTPUT_DIR.glob("*.pth"))
    run(
        [str(PYTHON), "-s", "GPT_SoVITS/s2_train.py", "--config", str(generated_config)],
        env=runtime_environment({"version": "v1"}),
    )
    outputs = sorted(set(OUTPUT_DIR.glob("*.pth")) - before)
    if not outputs:
        outputs = sorted(OUTPUT_DIR.glob("*.pth"))
    if not outputs:
        raise RuntimeError(f"Training produced no inference weights in {OUTPUT_DIR}")
    print("[ready] weights:", *(str(path) for path in outputs), sep="\n  ", flush=True)
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and conservatively fine-tune ATRI SoVITS from user-provided clips."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path.home() / "Music" / "ATRI训练音频素材",
    )
    parser.add_argument(
        "--stage",
        choices=("prepare", "features", "train", "all"),
        default="all",
    )
    parser.add_argument("--epochs", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_dir = args.source_dir.expanduser().resolve()
    if args.stage in {"prepare", "all"}:
        prepare_audio(source_dir)
    if args.stage in {"features", "all"}:
        prepare_features()
    if args.stage in {"train", "all"}:
        train(args.epochs)


if __name__ == "__main__":
    main()
