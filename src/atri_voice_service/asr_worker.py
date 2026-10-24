"""ASR child protocol: one model, serial requests, exit on parent EOF.

Only job paths pass through stdin. Results are atomically published and removed
by the owner; recording contents and transcripts never enter service logs.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .config import VoiceServiceConfig
from .providers import SenseVoiceProvider


def _provider() -> SenseVoiceProvider:
    config = VoiceServiceConfig.from_env()
    return SenseVoiceProvider(
        config.asr_model, config.asr_device, config.modelscope_cache,
        vad_model=config.asr_vad_model,
        vad_max_segment_ms=config.asr_vad_max_segment_ms,
        audio_cache_dir=config.cache_dir / "asr-normalized",
        lexicon_path=config.asr_lexicon_path,
        preprocess_enabled=config.asr_preprocess_enabled,
        max_duration_seconds=config.asr_max_duration_seconds,
    )


async def _transcribe(provider: SenseVoiceProvider, request_path: Path) -> dict[str, Any]:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if payload.get("action") == "load":
        await provider.warmup()
        return {"ok": True, "timings": {}}
    result = await provider.transcribe(
        Path(str(payload.get("audio_path") or "")),
        str(payload.get("language") or "auto"),
    )
    return {
        "ok": True, "text": result.text, "language": result.language,
        "emotion": result.emotion, "confidence": result.confidence,
        "timings": provider.last_timings,
    }


async def _job(provider: SenseVoiceProvider, request_path: Path, result_path: Path) -> bool:
    try:
        payload = await _transcribe(provider, request_path)
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(result_path)
    return bool(payload.get("ok"))


async def _serve() -> int:
    provider = _provider()
    while line := await asyncio.to_thread(sys.stdin.readline):
        request_path, result_path = json.loads(line)
        await _job(provider, Path(request_path), Path(result_path))
    return 0


def main() -> int:
    if sys.argv[1:] == ["--serve"]:
        return asyncio.run(_serve())
    if len(sys.argv) == 3:
        success = asyncio.run(_job(_provider(), Path(sys.argv[1]), Path(sys.argv[2])))
        return 0 if success else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
