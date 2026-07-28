from __future__ import annotations

import json
import urllib.request
import wave
from pathlib import Path


SERVICE_URL = "http://127.0.0.1:8790/v1/synthesize"
CASES = {
    "zh": "主人，今天也请让我陪在你身边。",
    "en": "Master, please let me stay by your side today.",
    "ja": "マスター、今日もあなたのそばにいさせてください。",
}
PROFILES = ("atri-2dipw", "atri-voidshine")


def synthesize(profile: str, language: str, text: str) -> Path:
    body = json.dumps(
        {
            "profile": profile,
            "text": text,
            "language": language,
            "emotion": "gentle",
            "intensity": 0.55,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        SERVICE_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "synthesis failed"))
    audio_path = Path(str(payload["audio_path"])).resolve()
    with wave.open(str(audio_path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if duration <= 0.2 or audio.getnchannels() < 1:
            raise RuntimeError(f"Invalid WAV output: {audio_path}")
    print(f"[pass] {profile} {language}: {duration:.2f}s -> {audio_path}", flush=True)
    return audio_path


def main() -> None:
    for profile in PROFILES:
        for language, text in CASES.items():
            synthesize(profile, language, text)
    print("[ready] all ATRI TTS smoke tests passed", flush=True)


if __name__ == "__main__":
    main()
