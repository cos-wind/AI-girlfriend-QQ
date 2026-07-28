from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import snapshot_download


MODEL_ROOT = Path(os.environ.get("ATRI_ASR_ROOT", r"D:\AtriModels\voice\asr"))
SPECS = {
    "funasr-nano": {
        "repo_id": "FunAudioLLM/Fun-ASR-Nano-2512",
        "revision": "272c57b82523ada6fd87095e955f8e29100979ab",
        "directory": "fun-asr-nano-2512",
        "primary": "model.pt",
        "required": [
            "model.pt",
            "config.yaml",
            "configuration.json",
            "multilingual.tiktoken",
            "Qwen3-0.6B/config.json",
            "Qwen3-0.6B/tokenizer.json",
        ],
        "license": "Apache-2.0 code; verify model-card terms before redistribution",
    },
    "whisper-turbo": {
        "repo_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        "directory": "faster-whisper-large-v3-turbo",
        "primary": "model.bin",
        "required": [
            "model.bin",
            "config.json",
            "preprocessor_config.json",
            "tokenizer.json",
            "vocabulary.json",
        ],
        "license": "MIT (derived from OpenAI Whisper large-v3-turbo)",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(candidate: str, root: Path) -> None:
    spec = SPECS[candidate]
    target = root / str(spec["directory"])
    target.mkdir(parents=True, exist_ok=True)
    print(f"[download] {candidate} -> {target}", flush=True)
    snapshot_download(
        repo_id=str(spec["repo_id"]),
        revision=str(spec["revision"]),
        local_dir=target,
    )
    missing = [name for name in spec["required"] if not (target / str(name)).is_file()]
    if missing:
        raise RuntimeError(f"{candidate} is incomplete: {', '.join(missing)}")
    primary = target / str(spec["primary"])
    manifest = {
        "id": candidate,
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "license": spec["license"],
        "primary_file": primary.name,
        "primary_size": primary.stat().st_size,
        "primary_sha256": sha256(primary),
        "verified": True,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (target / "candidate.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[ready] {candidate} {primary.stat().st_size} bytes "
        f"sha256={manifest['primary_sha256']}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        choices=["all", *SPECS],
        default="all",
    )
    parser.add_argument("--root", type=Path, default=MODEL_ROOT)
    args = parser.parse_args()
    selected = SPECS if args.candidate == "all" else {args.candidate: SPECS[args.candidate]}
    for candidate in selected:
        download(candidate, args.root.resolve())


if __name__ == "__main__":
    main()
