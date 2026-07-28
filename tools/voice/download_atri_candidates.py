from __future__ import annotations

import hashlib
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ROOT = Path(os.environ.get("ATRI_CANDIDATES_ROOT", r"D:\本地大模型\models\AI_ATRI\voice\candidates"))


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: int
    sha256: str = ""


@dataclass(frozen=True)
class Candidate:
    id: str
    display_name: str
    repository: str
    revision: str
    license: str
    engine: str
    declared_version: str
    declared_languages: tuple[str, ...]
    gpt_weights: str
    sovits_weights: str
    reference_audio: str
    prompt_text: str
    files: tuple[RemoteFile, ...]


CANDIDATES = (
    Candidate(
        id="2dipw-atri-gpt-sovits",
        display_name="ATRI GPT-SoVITS (2DIPW)",
        repository="2DIPW/ATRI_GPT-SoVITS",
        revision="85b2af13fe867ec74ca497b0c367d3811a0f849c",
        license="CC-BY-NC-SA-4.0 plus repository restrictions",
        engine="gpt_sovits",
        declared_version="unknown",
        declared_languages=("ja", "zh", "en"),
        gpt_weights="atri-e10.ckpt",
        sovits_weights="atri_e25_s5250.pth",
        reference_audio="ここはですね、こうやって解くんです。いいですか.wav",
        prompt_text="ここはですね、こうやって解くんです。いいですか",
        files=(
            RemoteFile(
                "atri-e10.ckpt",
                155_087_613,
                "def59c3ab387e2c184b051c944760c7a0ca5b4b18fcbf249ebcd7db52b37cf77",
            ),
            RemoteFile(
                "atri_e25_s5250.pth",
                84_932_551,
                "317642ed2f25fb6160def963af4360cea42bf93f6637c1b972cac62aee610fdc",
            ),
            RemoteFile("README.md", 824),
            RemoteFile("…どうしてしまったのでしょう、わたしは.wav", 321_810),
            RemoteFile(
                "いえ、見えてましたよ。みなさんがいるの。わたし、目がいいので.wav",
                501_428,
            ),
            RemoteFile("ここはですね、こうやって解くんです。いいですか.wav", 460_528),
            RemoteFile(
                "そうでした。時間もありませんし、そちらを優先します.wav", 479_264
            ),
            RemoteFile("それはもじもじ.wav", 386_044),
            RemoteFile(
                "どうしてもです。夏生さんはここで待っててください.wav", 412_418
            ),
            RemoteFile(
                "わたしが夏生さんのために行動するのに、理由が必要でしょうか.wav",
                734_010,
            ),
            RemoteFile(
                "わたしはやはりポンコツです。本来、それはわたしの役目なのに.wav",
                561_258,
            ),
            RemoteFile(
                "悲しまないでください。わたしも、悲しくなってしまいます.wav",
                448_162,
            ),
            RemoteFile(
                "間違いありません。知性の欠片も感じない、ジャカジャカとうるさいだけの音楽です.wav",
                615_176,
            ),
        ),
    ),
    Candidate(
        id="voidshine-atri-v2pro",
        display_name="ATRI GPT-SoVITS v2Pro (VoidShine)",
        repository="VoidShine/atri-sovits",
        revision="40ade29f0335e75b7a0fe7a3d84264afa6a9f65b",
        license="AGPL-3.0 plus personal/research-only notice",
        engine="gpt_sovits",
        declared_version="v2Pro",
        declared_languages=("ja", "zh", "en"),
        gpt_weights="@official/s1v3.ckpt",
        sovits_weights="ATR_e8_s3952.pth",
        reference_audio="ref_audio.wav",
        prompt_text="わたしはマスターの所有物ですので。勝手に売買するのは違法です",
        files=(
            RemoteFile(
                "ATR_e8_s3952.pth",
                134_936_883,
                "cdf42ec9f35654a92039b7832becfc9f0f4b111b84f4c5d5266bbac219d0d46a",
            ),
            RemoteFile(
                "ref_audio.wav",
                316_654,
                "1922a8ca728643b2e62166bc3ffcd94253bf9faac2c5aa3af0fd9218d37f103c",
            ),
            RemoteFile("README.md", 1_721),
            RemoteFile("LICENSE", 34_523),
            RemoteFile("api_atri.py", 9_181),
        ),
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_file(path: Path, spec: RemoteFile) -> bool:
    if not path.is_file() or path.stat().st_size != spec.size:
        return False
    return not spec.sha256 or sha256(path) == spec.sha256


def download_file(candidate: Candidate, spec: RemoteFile, target: Path) -> None:
    if valid_file(target, spec):
        print(f"[skip] {candidate.id}/{spec.name}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    quoted_name = urllib.parse.quote(spec.name, safe="/")
    url = (
        f"https://huggingface.co/{candidate.repository}/resolve/"
        f"{candidate.revision}/{quoted_name}?download=true"
    )
    print(f"[download] {candidate.id}/{spec.name} ({spec.size / 1_000_000:.1f} MB)")
    request = urllib.request.Request(url, headers={"User-Agent": "AI-ATRI-model-audit/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    if not valid_file(temporary, spec):
        raise RuntimeError(f"download verification failed: {candidate.id}/{spec.name}")
    temporary.replace(target)


def write_manifest(candidate: Candidate, target_dir: Path) -> None:
    payload = {
        "schema_version": 1,
        "id": candidate.id,
        "display_name": candidate.display_name,
        "source": f"https://huggingface.co/{candidate.repository}",
        "revision": candidate.revision,
        "license": candidate.license,
        "engine": candidate.engine,
        "declared_version": candidate.declared_version,
        "declared_languages": list(candidate.declared_languages),
        "gpt_weights": candidate.gpt_weights,
        "sovits_weights": candidate.sovits_weights,
        "reference_audio": candidate.reference_audio,
        "prompt_text": candidate.prompt_text,
        "prompt_language": "ja",
        "files": [
            {"name": item.name, "size": item.size, "sha256": item.sha256}
            for item in candidate.files
        ],
        "verified": all(valid_file(target_dir / item.name, item) for item in candidate.files),
    }
    path = target_dir / "candidate.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    for candidate in CANDIDATES:
        target_dir = root / candidate.id
        for spec in candidate.files:
            download_file(candidate, spec, target_dir / spec.name)
        write_manifest(candidate, target_dir)
        print(f"[verified] {candidate.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
