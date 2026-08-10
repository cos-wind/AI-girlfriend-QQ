from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
import struct
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from atri_qq_bot.voice import SynthesisResult

from .process_utils import hidden_subprocess_options
from .providers import ProviderError
from .resources import InferenceResourceManager


ProgressCallback = Callable[[int, str], None]
PIPELINE_PLACEHOLDERS = {
    "source",
    "reference",
    "vocal",
    "instrumental",
    "converted",
    "output",
    "pitch_shift",
    "preview_seconds",
    "model_root",
}


@dataclass(frozen=True)
class SingingJobRequest:
    text: str
    source_audio_path: Path | None
    reference_audio_path: Path | None = None
    language: str = "auto"
    profile: str = "atri"
    preview_seconds: int = 15
    pitch_shift: float = 0.0
    prefer_original: bool = True

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SingingJobRequest":
        text = " ".join(str(payload.get("text") or "").split())
        if not text:
            raise ValueError("唱歌任务缺少歌曲名或歌词")
        source_value = str(payload.get("source_audio_path") or "").strip()
        source_path = Path(source_value).expanduser().resolve() if source_value else None
        if source_path is not None and not source_path.is_file():
            raise ValueError(f"歌曲源文件不存在：{source_path}")
        reference_value = str(payload.get("reference_audio_path") or "").strip()
        reference_path = (
            Path(reference_value).expanduser().resolve() if reference_value else None
        )
        if reference_path is not None and not reference_path.is_file():
            raise ValueError(f"角色参考音频不存在：{reference_path}")
        try:
            preview_seconds = int(payload.get("preview_seconds", 15))
        except (TypeError, ValueError):
            preview_seconds = 15
        try:
            pitch_shift = float(payload.get("pitch_shift", 0.0))
        except (TypeError, ValueError):
            pitch_shift = 0.0
        if not math.isfinite(pitch_shift):
            pitch_shift = 0.0
        return cls(
            text=text[:500],
            source_audio_path=source_path,
            reference_audio_path=reference_path,
            language=str(payload.get("language") or "auto").strip().lower(),
            profile=str(payload.get("profile") or "atri").strip(),
            preview_seconds=max(5, min(60, preview_seconds)),
            pitch_shift=max(-12.0, min(12.0, pitch_shift)),
            prefer_original=_payload_bool(payload.get("prefer_original"), True),
        )


@dataclass(frozen=True)
class ExternalPipelineManifest:
    id: str
    model_root: Path
    separator: tuple[str, ...]
    converter: tuple[str, ...]
    mixer: tuple[str, ...]
    working_directory: Path | None
    timeout_seconds: int

    @classmethod
    def load(cls, path: Path) -> "ExternalPipelineManifest":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("歌声管线配置必须是 JSON 对象")
        converter = _command(raw.get("converter"))
        if not converter:
            raise ValueError("歌声管线缺少 converter 命令")
        working_value = str(raw.get("working_directory") or "").strip()
        model_value = str(raw.get("model_root") or "").strip()
        return cls(
            id=str(raw.get("id") or path.stem).strip(),
            model_root=Path(model_value).expanduser().resolve() if model_value else path.parent,
            separator=_command(raw.get("separator")),
            converter=converter,
            mixer=_command(raw.get("mixer")),
            working_directory=(
                Path(working_value).expanduser().resolve() if working_value else None
            ),
            timeout_seconds=max(30, min(3600, int(raw.get("timeout_seconds", 900)))),
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "model_root": str(self.model_root),
            "has_separator": bool(self.separator),
            "has_mixer": bool(self.mixer),
            "timeout_seconds": self.timeout_seconds,
        }


class ExternalSingingProvider:
    """Runs a fixed local SVC pipeline declared by the administrator."""

    def __init__(
        self,
        manifest_path: Path,
        cache_dir: Path,
        resources: InferenceResourceManager,
    ) -> None:
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        self.cache_dir = Path(cache_dir).resolve() / "singing"
        self.resources = resources
        self._manifest: ExternalPipelineManifest | None = None
        self._load_error = ""
        self._last_quality: dict[str, Any] | None = None

    def status(self) -> dict[str, object]:
        manifest = self._load_manifest()
        ready = manifest is not None and _command_available(
            manifest.converter,
            manifest.working_directory,
        )
        return {
            "engine": "external_svc",
            "enabled": bool(str(self.manifest_path)),
            "ready": ready,
            "manifest_path": str(self.manifest_path),
            "manifest": manifest.public_dict() if manifest else None,
            "load_error": self._load_error,
            "last_quality": self._last_quality,
        }

    async def synthesize(
        self,
        request: SingingJobRequest,
        progress: ProgressCallback,
    ) -> SynthesisResult:
        manifest = self._load_manifest()
        if manifest is None:
            raise ProviderError(
                self._load_error or "尚未配置实验歌声转换管线"
            )
        if request.source_audio_path is None:
            raise ProviderError("生成式唱歌需要歌曲源音频；原声音频匹配不需要")
        if request.reference_audio_path is None:
            raise ProviderError("歌声转换档案缺少角色参考音频")
        cache_key = await asyncio.to_thread(
            _pipeline_cache_key,
            request,
            self.manifest_path,
        )
        output = self.cache_dir / f"{cache_key}.wav"
        if output.is_file():
            quality = evaluate_audio_file(output)
            self._last_quality = quality
            progress(100, "已使用缓存歌声")
            return SynthesisResult(
                output,
                duration_seconds=_quality_duration(quality),
                source="singing_cache",
                quality=quality,
            )

        work_dir = self.cache_dir / "jobs" / uuid.uuid4().hex
        work_dir.mkdir(parents=True, exist_ok=False)
        input_path = work_dir / "source-preview.wav"
        vocal_path = work_dir / "vocal.wav"
        instrumental_path = work_dir / "instrumental.wav"
        converted_path = work_dir / "converted.wav"
        staged_output = work_dir / "output.wav"
        placeholders = {
            "source": str(input_path),
            "reference": str(request.reference_audio_path),
            "vocal": str(vocal_path),
            "instrumental": str(instrumental_path),
            "converted": str(converted_path),
            "output": str(staged_output),
            "pitch_shift": str(request.pitch_shift),
            "preview_seconds": str(request.preview_seconds),
            "model_root": str(manifest.model_root),
        }
        try:
            progress(5, "准备试听片段")
            await _prepare_preview(
                request.source_audio_path,
                input_path,
                request.preview_seconds,
            )
            async with self.resources.lease(f"singing:{manifest.id}"):
                if manifest.separator:
                    progress(15, "分离人声与伴奏")
                    await _run_command(manifest.separator, placeholders, manifest)
                    _require_output(vocal_path, "人声分离")
                else:
                    shutil.copy2(input_path, vocal_path)

                progress(45, "转换为角色歌声音色")
                await _run_command(manifest.converter, placeholders, manifest)
                _require_output(converted_path, "歌声音色转换")

                if manifest.mixer and instrumental_path.is_file():
                    progress(80, "重新混合伴奏")
                    await _run_command(manifest.mixer, placeholders, manifest)
                    _require_output(staged_output, "伴奏混合")
                else:
                    shutil.copy2(converted_path, staged_output)

            progress(92, "检查歌声音频")
            quality = await asyncio.to_thread(evaluate_audio_file, staged_output)
            if not quality["passed"]:
                raise ProviderError(f"歌声质量检查失败：{quality['reason']}")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            os.replace(staged_output, output)
            self._last_quality = quality
            progress(100, "歌声生成完成")
            return SynthesisResult(
                output,
                duration_seconds=_quality_duration(quality),
                source=f"singing_svc:{manifest.id}",
                quality=quality,
            )
        finally:
            await asyncio.to_thread(_remove_job_directory, work_dir, self.cache_dir)

    def _load_manifest(self) -> ExternalPipelineManifest | None:
        if self._manifest is not None:
            return self._manifest
        if not self.manifest_path.is_file():
            self._load_error = "管线配置文件不存在"
            return None
        try:
            self._manifest = ExternalPipelineManifest.load(self.manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._load_error = str(exc)
            return None
        self._load_error = ""
        return self._manifest


async def _prepare_preview(source: Path, output: Path, seconds: int) -> None:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ProviderError(f"无法定位 FFmpeg：{exc}") from exc
    command = (
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-t",
        str(seconds),
        "-ac",
        "1",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(output),
    )
    await _run_process(command, None, timeout_seconds=120)
    _require_output(output, "试听片段准备")


async def _run_command(
    command: tuple[str, ...],
    placeholders: dict[str, str],
    manifest: ExternalPipelineManifest,
) -> None:
    resolved = tuple(_format_argument(argument, placeholders) for argument in command)
    await _run_process(
        resolved,
        manifest.working_directory,
        timeout_seconds=manifest.timeout_seconds,
    )


async def _run_process(
    command: tuple[str, ...],
    cwd: Path | None,
    *,
    timeout_seconds: int,
) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **hidden_subprocess_options(),
        )
    except OSError as exc:
        raise ProviderError(f"无法启动歌声引擎：{exc}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.CancelledError:
        process.terminate()
        await process.wait()
        raise
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ProviderError(f"歌声引擎执行超过 {timeout_seconds} 秒") from exc
    if process.returncode:
        detail = (stderr or stdout).decode("utf-8", errors="replace")[-1500:].strip()
        raise ProviderError(f"歌声引擎执行失败（{process.returncode}）：{detail}")


def evaluate_audio_file(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
            content = audio.readframes(frames)
    except (OSError, wave.Error) as exc:
        return {"passed": False, "reason": f"无法读取 WAV：{exc}"}
    duration = frames / max(1, sample_rate)
    if channels not in {1, 2} or sample_width != 2 or not 8000 <= sample_rate <= 96000:
        return {
            "passed": False,
            "reason": "音频格式必须是 16-bit 单声道或双声道 WAV",
        }
    if duration < 0.5:
        return {"passed": False, "reason": "有效歌声不足 0.5 秒"}
    samples = struct.unpack(f"<{len(content) // 2}h", content)
    if not samples:
        return {"passed": False, "reason": "音频没有采样数据"}
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
    clipping_ratio = sum(abs(sample) >= 32760 for sample in samples) / len(samples)
    silence_ratio = sum(abs(sample) < 128 for sample in samples) / len(samples)
    passed = rms >= 0.001 and clipping_ratio <= 0.01 and silence_ratio < 0.98
    reason = ""
    if rms < 0.001:
        reason = "音频接近静音"
    elif clipping_ratio > 0.01:
        reason = "削波采样超过 1%"
    elif silence_ratio >= 0.98:
        reason = "静音比例过高"
    return {
        "passed": passed,
        "reason": reason,
        "duration_seconds": round(duration, 3),
        "sample_rate": sample_rate,
        "channels": channels,
        "peak": round(peak, 5),
        "rms": round(rms, 5),
        "clipping_ratio": round(clipping_ratio, 6),
        "silence_ratio": round(silence_ratio, 6),
    }


def _command(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("管线命令必须是字符串数组")
    return tuple(item for item in value if item)


def _format_argument(argument: str, values: dict[str, str]) -> str:
    try:
        return argument.format_map(values)
    except KeyError as exc:
        allowed = "、".join(sorted(PIPELINE_PLACEHOLDERS))
        raise ProviderError(f"未知管线占位符 {exc}；允许：{allowed}") from exc


def _command_available(command: tuple[str, ...], cwd: Path | None) -> bool:
    if not command:
        return False
    executable = Path(command[0]).expanduser()
    if executable.is_absolute():
        return executable.is_file()
    if cwd and (cwd / executable).is_file():
        return True
    return shutil.which(command[0]) is not None


def _pipeline_cache_key(
    request: SingingJobRequest,
    manifest_path: Path,
) -> str:
    digest = hashlib.sha256()
    assert request.source_audio_path is not None
    with request.source_audio_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(manifest_path.read_bytes())
    digest.update(
        f"{request.preview_seconds}|{request.pitch_shift}|{request.profile}".encode("utf-8")
    )
    digest.update(request.reference_audio_path.read_bytes() if request.reference_audio_path else b"")
    return digest.hexdigest()[:32]


def _require_output(path: Path, stage: str) -> None:
    if not path.is_file() or path.stat().st_size < 44:
        raise ProviderError(f"{stage}没有生成有效音频：{path}")


def _quality_duration(quality: dict[str, Any]) -> float | None:
    value = quality.get("duration_seconds")
    return float(value) if isinstance(value, (int, float)) else None


def _payload_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _remove_job_directory(path: Path, cache_root: Path) -> None:
    resolved = path.resolve()
    root = cache_root.resolve()
    if root not in resolved.parents:
        raise RuntimeError("拒绝清理歌声缓存目录之外的路径")
    shutil.rmtree(resolved, ignore_errors=True)
