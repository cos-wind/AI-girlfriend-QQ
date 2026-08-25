"""一次性 SenseVoice 工作进程。

该模块只处理一条音频后退出。退出是 Windows 上可靠释放 PyTorch/ONNX
提交内存的边界，不能改成长驻服务。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .config import VoiceServiceConfig
from .providers import ProviderError, SenseVoiceProvider


async def _transcribe(request_path: Path) -> dict[str, Any]:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    config = VoiceServiceConfig.from_env()
    provider = SenseVoiceProvider(
        config.asr_model,
        config.asr_device,
        config.modelscope_cache,
        vad_model=config.asr_vad_model,
        vad_max_segment_ms=config.asr_vad_max_segment_ms,
        audio_cache_dir=config.cache_dir / "asr-normalized",
        lexicon_path=config.asr_lexicon_path,
        preprocess_enabled=config.asr_preprocess_enabled,
        max_duration_seconds=config.asr_max_duration_seconds,
    )
    result = await provider.transcribe(
        Path(str(payload.get("audio_path") or "")),
        str(payload.get("language") or "auto"),
    )
    return {
        "ok": True,
        "text": result.text,
        "language": result.language,
        "emotion": result.emotion,
        "confidence": result.confidence,
    }


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    request_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    try:
        payload = asyncio.run(_transcribe(request_path))
    except (ProviderError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "error": str(exc)}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
