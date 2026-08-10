from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import imageio_ffmpeg

from atri_voice_service.resources import InferenceResourceManager
from atri_voice_service.singing_pipeline import (
    ExternalSingingProvider,
    SingingJobRequest,
    evaluate_audio_file,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a long-form singing conversion outside the WebUI preview limit."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--title", default="ATRI full singing conversion")
    parser.add_argument("--profile", default="atri")
    parser.add_argument("--pitch-shift", type=float, default=0.0)
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=0,
        help="Convert in independent chunks to reduce peak memory; 0 converts in one pass.",
    )
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    source = args.source.expanduser().resolve()
    reference = args.reference.expanduser().resolve()
    manifest = args.manifest.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source audio does not exist: {source}")
    if not reference.is_file():
        raise FileNotFoundError(f"reference audio does not exist: {reference}")
    if not manifest.is_file():
        raise FileNotFoundError(f"pipeline manifest does not exist: {manifest}")

    provider = ExternalSingingProvider(
        manifest,
        args.cache_dir.expanduser().resolve(),
        InferenceResourceManager(),
    )
    def progress(value: int, message: str) -> None:
        print(
            json.dumps(
                {"event": "progress", "progress": value, "message": message},
                ensure_ascii=False,
            ),
            flush=True,
        )

    duration_seconds = max(5, min(3600, int(args.duration_seconds)))
    chunk_seconds = max(0, int(args.chunk_seconds))
    if chunk_seconds:
        result_payload = await _synthesize_chunked(
            provider=provider,
            source=source,
            reference=reference,
            manifest=manifest,
            cache_dir=args.cache_dir.expanduser().resolve(),
            title=str(args.title),
            profile=str(args.profile),
            pitch_shift=max(-12.0, min(12.0, float(args.pitch_shift))),
            duration_seconds=duration_seconds,
            chunk_seconds=max(5, min(60, chunk_seconds)),
            retries=max(0, min(5, int(args.retries))),
            progress=progress,
        )
    else:
        request = SingingJobRequest(
            text=str(args.title),
            source_audio_path=source,
            reference_audio_path=reference,
            profile=str(args.profile),
            preview_seconds=duration_seconds,
            pitch_shift=max(-12.0, min(12.0, float(args.pitch_shift))),
            prefer_original=False,
        )
        result = await provider.synthesize(request, progress)
        result_payload = {
            "audio_path": str(result.audio_path),
            "duration_seconds": result.duration_seconds,
            "source": result.source,
            "quality": result.quality,
        }
    print(
        json.dumps(
            {
                "event": "result",
                **result_payload,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


async def _synthesize_chunked(
    *,
    provider: ExternalSingingProvider,
    source: Path,
    reference: Path,
    manifest: Path,
    cache_dir: Path,
    title: str,
    profile: str,
    pitch_shift: float,
    duration_seconds: int,
    chunk_seconds: int,
    retries: int,
    progress: object,
) -> dict[str, object]:
    total_chunks = (duration_seconds + chunk_seconds - 1) // chunk_seconds
    digest = hashlib.sha256()
    for path in (source, reference, manifest):
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    digest.update(
        f"chunked|{duration_seconds}|{chunk_seconds}|{pitch_shift}|{profile}".encode()
    )
    output = cache_dir / "singing" / f"full-{digest.hexdigest()[:32]}.wav"
    if output.is_file():
        quality = evaluate_audio_file(output)
        return {
            "audio_path": str(output),
            "duration_seconds": quality.get("duration_seconds"),
            "source": "singing_chunk_cache",
            "quality": quality,
        }

    converted_parts: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="atri-full-singing-") as temp_value:
        temporary = Path(temp_value)
        for index in range(total_chunks):
            start = index * chunk_seconds
            length = min(chunk_seconds, duration_seconds - start)
            segment = temporary / f"segment-{index + 1:03d}.wav"
            _extract_segment(source, segment, start, length)
            request = SingingJobRequest(
                text=f"{title} {index + 1}/{total_chunks}",
                source_audio_path=segment,
                reference_audio_path=reference,
                profile=profile,
                preview_seconds=length,
                pitch_shift=pitch_shift,
                prefer_original=False,
            )

            result = None
            for attempt in range(retries + 1):
                try:
                    print(
                        json.dumps(
                            {
                                "event": "chunk",
                                "chunk": index + 1,
                                "total_chunks": total_chunks,
                                "attempt": attempt + 1,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    result = await provider.synthesize(
                        request,
                        lambda value, message, chunk=index + 1: progress(
                            round(((chunk - 1) + value / 100) / total_chunks * 100),
                            f"分段 {chunk}/{total_chunks}：{message}",
                        ),
                    )
                    break
                except Exception:
                    if attempt >= retries:
                        raise
                    await asyncio.sleep(15)
            assert result is not None
            converted_parts.append(result.audio_path)
            await asyncio.sleep(3)

        output.parent.mkdir(parents=True, exist_ok=True)
        _concatenate_wav(converted_parts, output)

    quality = evaluate_audio_file(output)
    if not quality.get("passed"):
        output.unlink(missing_ok=True)
        raise RuntimeError(f"chunked output quality check failed: {quality}")
    return {
        "audio_path": str(output),
        "duration_seconds": quality.get("duration_seconds"),
        "source": "singing_chunked",
        "quality": quality,
    }


def _extract_segment(
    source: Path,
    output: Path,
    start_seconds: int,
    duration_seconds: int,
) -> None:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start_seconds),
        "-i",
        str(source),
        "-t",
        str(duration_seconds),
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    subprocess.run(command, check=True)


def _concatenate_wav(parts: list[Path], output: Path) -> None:
    if not parts:
        raise ValueError("no converted singing chunks to concatenate")
    parameters: tuple[int, int, int] | None = None
    with wave.open(str(output), "wb") as writer:
        for part in parts:
            with wave.open(str(part), "rb") as reader:
                current = (
                    reader.getnchannels(),
                    reader.getsampwidth(),
                    reader.getframerate(),
                )
                if parameters is None:
                    parameters = current
                    writer.setnchannels(current[0])
                    writer.setsampwidth(current[1])
                    writer.setframerate(current[2])
                elif current != parameters:
                    raise ValueError(
                        f"incompatible WAV chunk {part}: {current} != {parameters}"
                    )
                while frames := reader.readframes(44100):
                    writer.writeframes(frames)


def main() -> None:
    asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    main()
