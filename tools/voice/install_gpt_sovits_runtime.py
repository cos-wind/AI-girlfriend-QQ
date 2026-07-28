from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "data" / "runtime" / "gpt-sovits"
SOURCE_ROOT = RUNTIME_ROOT / "source"
VENV_ROOT = RUNTIME_ROOT / ".venv"
PYTHON = VENV_ROOT / "Scripts" / "python.exe"
MODEL_ROOT = Path(os.environ.get("ATRI_GPT_SOVITS_MODEL_ROOT", r"D:\本地大模型\models\AI_ATRI\voice\base\gpt-sovits"))
HF_ROOT = "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main"

PRETRAINED_FILES = {
    "chinese-hubert-base/config.json": 1449,
    "chinese-hubert-base/preprocessor_config.json": 212,
    "chinese-hubert-base/pytorch_model.bin": 188_811_417,
    "chinese-roberta-wwm-ext-large/config.json": 963,
    "chinese-roberta-wwm-ext-large/pytorch_model.bin": 651_225_145,
    "chinese-roberta-wwm-ext-large/tokenizer.json": 268_962,
    "fast_langdetect/lid.176.bin": 131_266_198,
    "fast_langdetect/lid.176.ftz": 938_013,
    "s1v3.ckpt": 155_284_856,
    "sv/pretrained_eres2netv2w24s4ep4.ckpt": 107_528_697,
    "v2Pro/s2Dv2Pro.pth": 126_431_971,
    "v2Pro/s2Gv2Pro.pth": 162_303_657,
}

ARCHIVES = {
    "G2PWModel.zip": 588_856_634,
    "nltk_data.zip": 9_924_448,
    "open_jtalk_dic_utf_8-1.11.tar.gz": 23_646_843,
}

BINARIES = {
    "ffmpeg.exe": (
        "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/ffmpeg.exe",
        52_925_440,
    ),
    "ffprobe.exe": (
        "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/ffprobe.exe",
        122_135_040,
    ),
}


def download(url: str, destination: Path, expected_size: int) -> None:
    if destination.is_file() and destination.stat().st_size == expected_size:
        print(f"[skip] {destination.name}", flush=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "AI-ATRI-voice-setup/1.0"})
    print(f"[download] {destination.name} ({expected_size / 1024 / 1024:.1f} MiB)", flush=True)
    with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    actual_size = partial.stat().st_size
    if actual_size != expected_size:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Size mismatch for {destination}: expected {expected_size}, got {actual_size}")
    partial.replace(destination)


def install_dependencies() -> None:
    marker = RUNTIME_ROOT / ".dependencies-ready"
    if marker.is_file():
        print("[skip] Python dependencies", flush=True)
        return
    requirements = RUNTIME_ROOT / "requirements-windows.txt"
    source_requirements = (SOURCE_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    excluded = ("--no-binary=opencc", "pyopenjtalk", "jieba_fast", "opencc")
    requirements.write_text(
        "\n".join(
            line for line in source_requirements
            if not line.strip().startswith(excluded)
        ) + "\n",
        encoding="utf-8",
    )
    commands = [
        [str(PYTHON), "-m", "pip", "install", "-r", str(SOURCE_ROOT / "extra-req.txt"), "--no-deps"],
        [str(PYTHON), "-m", "pip", "install", "pyopenjtalk-prebuilt==0.3.0"],
        [str(PYTHON), "-m", "pip", "install", "opencc-python-reimplemented==0.1.7"],
        [str(PYTHON), "-m", "pip", "install", "-r", str(requirements)],
    ]
    for command in commands:
        print(f"[run] {' '.join(command[3:])}", flush=True)
        subprocess.run(command, cwd=SOURCE_ROOT, check=True)
    marker.write_text("ok\n", encoding="ascii")


def install_base_models() -> None:
    pretrained_root = MODEL_ROOT / "pretrained_models"
    for relative_path, expected_size in PRETRAINED_FILES.items():
        download(
            f"{HF_ROOT}/pretrained_models/{relative_path}",
            pretrained_root / Path(relative_path),
            expected_size,
        )

    archive_root = MODEL_ROOT / "archives"
    for name, expected_size in ARCHIVES.items():
        download(f"{HF_ROOT}/{name}", archive_root / name, expected_size)

    g2pw_destination = MODEL_ROOT / "G2PWModel"
    if not g2pw_destination.is_dir():
        print("[extract] G2PWModel", flush=True)
        with zipfile.ZipFile(archive_root / "G2PWModel.zip") as bundle:
            bundle.extractall(MODEL_ROOT)

    nltk_destination = VENV_ROOT / "nltk_data"
    if not nltk_destination.is_dir():
        print("[extract] nltk_data", flush=True)
        with zipfile.ZipFile(archive_root / "nltk_data.zip") as bundle:
            bundle.extractall(VENV_ROOT)

    result = subprocess.run(
        [str(PYTHON), "-c", "import os,pyopenjtalk; print(os.path.dirname(pyopenjtalk.__file__))"],
        check=True,
        capture_output=True,
        text=True,
    )
    open_jtalk_root = Path(result.stdout.strip())
    dictionary = open_jtalk_root / "open_jtalk_dic_utf_8-1.11"
    if not dictionary.is_dir():
        print("[extract] Open JTalk dictionary", flush=True)
        with tarfile.open(archive_root / "open_jtalk_dic_utf_8-1.11.tar.gz", "r:gz") as bundle:
            bundle.extractall(open_jtalk_root, filter="data")

    for name, (url, expected_size) in BINARIES.items():
        download(url, SOURCE_ROOT / name, expected_size)


def main() -> None:
    if not PYTHON.is_file() or not (SOURCE_ROOT / "api_v2.py").is_file():
        raise RuntimeError("Run download_gpt_sovits_source.py and create the GPT-SoVITS virtual environment first")
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    install_dependencies()
    install_base_models()
    print("[ready] GPT-SoVITS runtime dependencies and base models", flush=True)


if __name__ == "__main__":
    main()
