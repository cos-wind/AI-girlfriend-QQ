from __future__ import annotations

from pathlib import Path
import hashlib

from atri_voice_service.original_library import OriginalVoiceLibrary
from atri_voice_service.singing import OriginalSingingProvider


def test_voice_service_exposes_authoritative_singing_references(tmp_path: Path) -> None:
    root = tmp_path / "library"
    singing = root / "唱歌素材"
    speech = root / "普通语音"
    singing.mkdir(parents=True)
    speech.mkdir()
    first = singing / "清唱1.mp3"
    second = singing / "English Vocal.wav"
    first.write_bytes(b"ID3")
    second.write_bytes(b"RIFF")
    (speech / "普通台词.mp3").write_bytes(b"ID3")

    provider = OriginalSingingProvider(
        OriginalVoiceLibrary(root, tmp_path / "cache", refresh_seconds=60)
    )
    status = provider.status()

    assert status["root"] == str(root.resolve())
    assert status["clips"] == 2
    assert status["references"] == [
        {
            "id": hashlib.sha256(
                (Path("唱歌素材") / second.name).as_posix().encode("utf-8")
            ).hexdigest()[:12],
            "name": "English Vocal",
            "path": str(second.resolve()),
            "relative_path": str(Path("唱歌素材") / second.name),
        },
        {
            "id": hashlib.sha256(
                (Path("唱歌素材") / first.name).as_posix().encode("utf-8")
            ).hexdigest()[:12],
            "name": "清唱1",
            "path": str(first.resolve()),
            "relative_path": str(Path("唱歌素材") / first.name),
        },
    ]

    (singing / "later.mp3").write_bytes(b"ID3")
    assert provider.status()["references"] == status["references"]
