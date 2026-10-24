from __future__ import annotations

import asyncio
import gc
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from atri_qq_bot.runtime.paths import PROJECT_ROOT
from atri_qq_bot.voice import SynthesisResult, TranscriptionResult, VoiceRequest

from .asr_lexicon import AsrLexicon
from .audio_processing import (
    AudioPreprocessError,
    AudioValidationError,
    PreparedAudio,
    postprocess_synthesized_audio,
    prepare_speech_audio,
    validate_synthesized_speech_timing,
)
from .config import ASCII_ATRI_MODELS_ROOT, ATRI_MODELS_ROOT, VoiceServiceConfig
from .profiles import VoiceProfile
from .tts_text import TtsPronunciationLexicon, normalize_tts_text


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = bool(retryable)


class SenseVoiceProvider:
    def __init__(
        self,
        model_name: str,
        device: str,
        cache_dir: Path,
        *,
        vad_model: str = "",
        vad_max_segment_ms: int = 30_000,
        audio_cache_dir: Path | None = None,
        lexicon_path: Path | None = None,
        preprocess_enabled: bool = True,
        max_duration_seconds: int = 300,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.cache_dir = Path(cache_dir).expanduser()
        self.vad_model = str(vad_model or "").strip()
        self.vad_max_segment_ms = max(5_000, int(vad_max_segment_ms))
        self.audio_cache_dir = Path(audio_cache_dir or self.cache_dir / "asr-cache")
        self.preprocess_enabled = bool(preprocess_enabled)
        self.max_duration_seconds = max(10, int(max_duration_seconds))
        self.lexicon = AsrLexicon(lexicon_path or self.cache_dir / "asr-hotwords.json")
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()
        self._loading = False
        self._load_error = ""
        self._last_preprocess_error = ""
        self.last_timings: dict[str, float] = {}

    def status(self) -> dict[str, Any]:
        return {
            "provider": "sensevoice",
            "dependency_available": importlib.util.find_spec("funasr") is not None,
            "model": self.model_name,
            "device": self.device,
            "vad_model": self.vad_model,
            "preprocess_enabled": self.preprocess_enabled,
            "audio_format": "16kHz mono PCM",
            "hotwords": self.lexicon.terms(),
            "hotwords_supported": False,
            "lexicon_mode": "postprocess_aliases",
            "last_timings": dict(self.last_timings),
            "loaded": self._model is not None,
            "loading": self._loading,
            "load_error": self._load_error,
            "last_preprocess_error": self._last_preprocess_error,
        }

    async def warmup(self) -> None:
        await self._get_model()

    async def unload(self) -> None:
        """Release the lazy ASR model after a bounded transcription."""
        async with self._load_lock:
            model = self._model
            self._model = None
        if model is None:
            return
        del model
        await asyncio.to_thread(gc.collect)

    async def transcribe(self, audio_path: Path, language: str) -> TranscriptionResult:
        started = time.perf_counter()
        model = await self._get_model()
        loaded = time.perf_counter()
        prepared = PreparedAudio(Path(audio_path).resolve())
        self._last_preprocess_error = ""
        try:
            prepared = await asyncio.to_thread(
                prepare_speech_audio,
                audio_path,
                self.audio_cache_dir,
                enabled=self.preprocess_enabled,
                max_duration_seconds=self.max_duration_seconds,
            )
        except AudioValidationError as exc:
            raise ProviderError(str(exc)) from exc
        except AudioPreprocessError as exc:
            self._last_preprocess_error = str(exc)
        preprocessed = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                model.generate,
                input=str(prepared.path),
                cache={},
                language=language or "auto",
                use_itn=True,
                batch_size_s=60,
                merge_vad=True,
            )
        except Exception as exc:
            raise ProviderError(f"SenseVoice 识别失败：{exc}") from exc
        finally:
            prepared.cleanup()
        inferred = time.perf_counter()
        raw_text = _sensevoice_result_text(result)
        text, detected_language, emotion = parse_sensevoice_output(raw_text)
        text = self.lexicon.correct(text)
        if not text:
            raise ProviderError("SenseVoice 没有识别出文本")
        self.last_timings = {
            "load_seconds": round(loaded - started, 4),
            "preprocess_seconds": round(preprocessed - loaded, 4),
            "inference_seconds": round(inferred - preprocessed, 4),
            "provider_seconds": round(time.perf_counter() - started, 4),
        }
        return TranscriptionResult(text, detected_language or language or "auto", emotion)

    async def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            self._loading = True
            self._load_error = ""
            try:
                from funasr import AutoModel
            except ImportError as exc:
                self._loading = False
                self._load_error = "未安装 funasr"
                raise ProviderError("未安装 funasr，请先安装语音运行时") from exc
            try:
                model_source = await self._model_source()
                model_options: dict[str, Any] = {
                    "model": model_source,
                    "trust_remote_code": True,
                    "device": self.device,
                    "disable_update": True,
                }
                if self.vad_model:
                    model_options["vad_model"] = self.vad_model
                    model_options["vad_kwargs"] = {
                        "max_single_segment_time": self.vad_max_segment_ms
                    }
                self._model = await asyncio.to_thread(AutoModel, **model_options)
            except Exception as exc:
                self._load_error = str(exc)
                raise ProviderError(f"SenseVoice 模型加载失败：{exc}") from exc
            finally:
                self._loading = False
            return self._model

    async def _model_source(self) -> str:
        local = Path(self.model_name).expanduser()
        if local.exists():
            return str(local)
        if "/" not in self.model_name:
            return self.model_name
        try:
            from modelscope import snapshot_download
        except ImportError:
            return self.model_name
        await asyncio.to_thread(
            snapshot_download,
            self.model_name,
            cache_dir=str(self.cache_dir),
        )
        owner, name = self.model_name.split("/", 1)
        snapshot = self.cache_dir / "models" / f"{owner}--{name}" / "snapshots" / "master"
        return str(snapshot) if snapshot.is_dir() else self.model_name


class IsolatedSenseVoiceProvider:
    """Reuse one owned CPU worker until idle; GPU workers exit after each request.

    Process exit still guarantees Windows reclaims PyTorch commit memory. CPU
    reuse is bounded and retains no VRAM alongside TTS or other GPU models.
    """

    def __init__(self, config: VoiceServiceConfig) -> None:
        self.config = config
        self.lexicon = AsrLexicon(config.asr_lexicon_path)
        self._loading = False
        self._load_error = ""
        self.last_timings: dict[str, float] = {}
        self._worker: subprocess.Popen[str] | None = None
        self._worker_loaded = False
        self._request_lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None
        self._keep_loaded = False

    @property
    def idle_seconds(self) -> float:
        return self.config.asr_worker_idle_seconds if self.config.asr_device.lower() == "cpu" else 0.0

    def status(self) -> dict[str, Any]:
        return {
            "provider": "sensevoice",
            "dependency_available": importlib.util.find_spec("funasr") is not None,
            "model": self.config.asr_model,
            "device": self.config.asr_device,
            "vad_model": self.config.asr_vad_model,
            "preprocess_enabled": self.config.asr_preprocess_enabled,
            "audio_format": "16kHz mono PCM",
            "hotwords": self.lexicon.terms(),
            "loaded": self._worker_loaded and self._worker_alive(),
            "loading": self._loading,
            "isolated_worker": True,
            "worker_pid": self._worker.pid if self._worker_alive() else None,
            "worker_idle_seconds": self.idle_seconds,
            "keep_loaded": self._keep_loaded,
            "manual_residency_supported": self.config.asr_device.lower() == "cpu",
            "model_control": True,
            "hotwords_supported": False,
            "lexicon_mode": "postprocess_aliases",
            "last_timings": dict(self.last_timings),
            "load_error": self._load_error,
            "last_preprocess_error": "",
        }

    async def warmup(self) -> None:
        # Keep service startup lazy; do not compete with TTS model loading.
        return None

    async def load_resident(self) -> None:
        """Explicit user opt-in; ordinary service startup remains lazy."""
        if self.config.asr_device.lower() != "cpu":
            raise ProviderError("常驻识别目前仅支持 CPU，请将 ASR 设备设为 cpu 后重启语音服务")
        async with self._request_lock:
            self._cancel_idle()
            try:
                await self._transcribe(None, "auto")
                self._keep_loaded = True
            except BaseException:
                self._keep_loaded = False
                await asyncio.shield(self._stop_worker())
                raise

    def _worker_alive(self) -> bool:
        return self._worker is not None and self._worker.poll() is None

    def _start_worker(self) -> subprocess.Popen[str]:
        from .process_utils import hidden_subprocess_options

        env = os.environ.copy()
        env.update({
            "ATRI_ASR_MODEL": self.config.asr_model,
            "ATRI_ASR_DEVICE": self.config.asr_device,
            "MODELSCOPE_CACHE": str(self.config.modelscope_cache),
            "ATRI_ASR_VAD_MODEL": self.config.asr_vad_model,
            "ATRI_ASR_VAD_MAX_SEGMENT_MS": str(self.config.asr_vad_max_segment_ms),
            "ATRI_ASR_PREPROCESS_ENABLED": str(self.config.asr_preprocess_enabled).lower(),
            "ATRI_ASR_MAX_DURATION_SECONDS": str(self.config.asr_max_duration_seconds),
            "ATRI_ASR_LEXICON_PATH": str(self.config.asr_lexicon_path),
            "ATRI_VOICE_CACHE_DIR": str(self.config.cache_dir),
        })
        return subprocess.Popen(
            [sys.executable, "-m", "atri_voice_service.asr_worker", "--serve"],
            cwd=str(PROJECT_ROOT), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=env, **hidden_subprocess_options(),
        )

    def _cancel_idle(self) -> None:
        task, self._idle_task = self._idle_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _stop_worker(self) -> None:
        child, self._worker = self._worker, None
        self._worker_loaded = False
        if child is None:
            return

        def stop() -> None:
            if child.stdin:
                try:
                    child.stdin.close()
                except OSError:
                    pass
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)

        await asyncio.to_thread(stop)

    async def unload(self) -> None:
        async with self._request_lock:
            self._keep_loaded = False
            self._cancel_idle()
            await self._stop_worker()

    async def release_after_request(self) -> None:
        if not self._keep_loaded and self.idle_seconds <= 0:
            await self.unload()

    async def _stop_after_idle(self) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
            async with self._request_lock:
                if not self._keep_loaded:
                    await self._stop_worker()
        except asyncio.CancelledError:
            return

    async def transcribe(self, audio_path: Path, language: str) -> TranscriptionResult:
        async with self._request_lock:
            self._cancel_idle()
            try:
                result = await self._transcribe(audio_path, language)
            except BaseException:
                await asyncio.shield(self._stop_worker())
                raise
            if self._keep_loaded:
                pass
            elif self.idle_seconds > 0:
                self._idle_task = asyncio.create_task(self._stop_after_idle())
            else:
                await self._stop_worker()
            return result

    async def _transcribe(self, audio_path: Path | None, language: str) -> TranscriptionResult:
        started = time.perf_counter()
        job_dir = self.config.cache_dir / "asr-jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        request_path = job_dir / f"{job_id}.request.json"
        result_path = job_dir / f"{job_id}.result.json"
        request_path.write_text(json.dumps({
            "action": "load" if audio_path is None else "transcribe",
            "audio_path": str(Path(audio_path).expanduser().resolve()) if audio_path is not None else "",
            "language": str(language or "auto"),
        }, ensure_ascii=False), encoding="utf-8")
        self._loading = not (self._worker_loaded and self._worker_alive())
        self._load_error = ""
        self.last_timings = {}
        succeeded = False
        try:
            if not self._worker_alive():
                await self._stop_worker()
                self._worker = self._start_worker()
            assert self._worker is not None and self._worker.stdin is not None
            self._worker.stdin.write(json.dumps([str(request_path), str(result_path)]) + "\n")
            self._worker.stdin.flush()
            deadline = started + max(90, self.config.asr_max_duration_seconds + 90)
            while not result_path.is_file():
                if not self._worker_alive():
                    raise ProviderError("SenseVoice worker exited; the next request will restart it")
                if time.perf_counter() >= deadline:
                    raise ProviderError("SenseVoice worker timed out")
                await asyncio.sleep(0.02)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.last_timings = dict(payload.get("timings") or {})
            self.last_timings["worker_seconds"] = round(time.perf_counter() - started, 4)
            if not payload.get("ok"):
                raise ProviderError(str(payload.get("error") or "SenseVoice transcription failed"))
            text = str(payload.get("text") or "").strip()
            if not text and audio_path is not None:
                raise ProviderError("SenseVoice returned no text")
            self._worker_loaded = True
            succeeded = True
            return TranscriptionResult(
                text, str(payload.get("language") or language or "auto"),
                str(payload.get("emotion") or "neutral"), payload.get("confidence"),
            )
        except (ProviderError, OSError, ValueError, TypeError) as exc:
            self._load_error = str(exc)
            raise ProviderError(f"SenseVoice worker failed: {exc}") from exc
        finally:
            self._loading = False
            if not succeeded:
                await asyncio.shield(self._stop_worker())
            request_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)
            result_path.with_suffix(result_path.suffix + ".tmp").unlink(missing_ok=True)


class GptSovitsProvider:
    def __init__(
        self,
        cache_dir: Path,
        timeout_seconds: float = 90.0,
        *,
        pronunciation_path: Path | None = None,
        postprocess_enabled: bool = True,
        target_rms_dbfs: float = -22.0,
        max_gain_db: float = 6.0,
    ) -> None:
        self.cache_dir = Path(cache_dir).resolve()
        self.timeout_seconds = max(5.0, timeout_seconds)
        self.pronunciations = TtsPronunciationLexicon(
            pronunciation_path or self.cache_dir.parent / "tts-pronunciations.json"
        )
        self.postprocess_enabled = bool(postprocess_enabled)
        self.target_rms_dbfs = float(target_rms_dbfs)
        self.max_gain_db = float(max_gain_db)
        self._active_weights: tuple[str, str] | None = None
        self._last_inference_preset = ""
        self._last_postprocess: dict[str, float] | None = None
        self._last_postprocess_error = ""
        self._last_split_fallback: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "provider": "gpt_sovits",
            "api_url": "http://127.0.0.1:9880",
            "active_weights": list(self._active_weights) if self._active_weights else None,
            "last_inference_preset": self._last_inference_preset,
            "pronunciations": self.pronunciations.terms(),
            "postprocess_enabled": self.postprocess_enabled,
            "last_postprocess": self._last_postprocess,
            "last_postprocess_error": self._last_postprocess_error,
            "last_split_fallback": self._last_split_fallback,
        }

    async def synthesize(
        self,
        request: VoiceRequest,
        profile: VoiceProfile,
        *,
        variation: int = 0,
    ) -> SynthesisResult:
        """一次语音会话；内置 ``cut0`` ↔ ``cut5`` 自动降级。

        为什么需要降级
        --------------
        本地 v2Pro 模型没有哪一种切分方式**永远**安全（2026-10-05 实测）：

        * ``cut0``（按标点整句送）在长句上会把已生成的前段当成参考继续续写，
          产出「异常拖长 / 超长静音」的废音频 —— 例：25 个发音单位吐出 38 秒；
        * ``cut5``（标点 + 长度二次切）在长句上稳定，但在短句上偶尔切得太碎、
          韵律发飘。

        于是：单次生成被自家质量检查判废（``AudioPreprocessError``）时，
        **换另一种切分方式再试一次**，而不是只改随机种子重掷 ——
        ``synthesize_with_quality`` 的 ``variation`` 重试只换种子，
        对这种确定性退化无效。
        """
        text_language = _tts_language(request.language, profile.text_language, request.text)
        preset = _tts_inference_preset(profile, request.emotion, text_language)
        spoken_text = self.prepare_spoken_text(request, profile)
        if not spoken_text:
            raise ProviderError("语音文本清理后为空")
        split_method = _tts_split_method(spoken_text, text_language, preset=preset)
        self._last_split_fallback = None
        try:
            return await self._synthesize_once(
                request,
                profile,
                spoken_text=spoken_text,
                text_language=text_language,
                preset=preset,
                split_method=split_method,
                variation=variation,
            )
        except ProviderError as exc:
            fallback = (
                _alternate_split_method(split_method)
                if _candidate_was_rejected(exc)
                else None
            )
            if not fallback:
                raise
            # `exc` 在 except 块结束时会被 Python 解绑，先取出文本备用。
            rejected_reason = str(exc)[:200]
        try:
            result = await self._synthesize_once(
                request,
                profile,
                spoken_text=spoken_text,
                text_language=text_language,
                preset=preset,
                split_method=fallback,
                variation=variation,
            )
        except ProviderError as retry_exc:
            self._last_split_fallback = {
                "from": split_method,
                "to": fallback,
                "reason": rejected_reason,
                "retry_error": str(retry_exc)[:200],
            }
            raise ProviderError(
                f"{retry_exc}（已从 {split_method} 自动切换到 {fallback} 重试，仍未通过）",
                retryable=retry_exc.retryable,
            ) from retry_exc
        self._last_split_fallback = {
            "from": split_method,
            "to": fallback,
            "reason": rejected_reason,
        }
        return result

    async def _synthesize_once(
        self,
        request: VoiceRequest,
        profile: VoiceProfile,
        *,
        spoken_text: str,
        text_language: str,
        preset: str,
        split_method: str,
        variation: int,
    ) -> SynthesisResult:
        reference, prompt_text, prompt_language = _reference_context(
            profile,
            request.emotion,
            text_language,
        )
        if not reference or not Path(reference).is_file():
            raise ProviderError("角色语音档案还没有有效的参考音频")
        style = _tts_style(request.emotion, request.intensity, preset=preset)
        payload = {
            "text": spoken_text,
            "text_lang": text_language,
            "ref_audio_path": reference,
            "aux_ref_audio_paths": _auxiliary_reference_paths(
                profile,
                reference,
                request.emotion,
                text_language,
            ),
            "prompt_text": prompt_text,
            "prompt_lang": prompt_language,
            "media_type": "wav",
            "streaming_mode": False,
            "text_split_method": split_method,
            "top_k": style["top_k"],
            "top_p": style["top_p"],
            "temperature": style["temperature"],
            "speed_factor": style["speed_factor"],
            "fragment_interval": style["fragment_interval"],
            "repetition_penalty": style["repetition_penalty"],
            "seed": _tts_seed(text_language) + max(0, int(variation)) * 9973,
            # Keep the v0.3-compatible serial path.  Parallel inference and
            # length bucketing caused long silent spans with this v2Pro model.
            "parallel_infer": False,
            "split_bucket": False,
        }
        self._last_inference_preset = preset
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                await self._activate_profile(client, profile)
                response = await client.post(profile.api_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _http_response_detail(exc.response)
            raise ProviderError(
                f"GPT-SoVITS 请求失败（HTTP {exc.response.status_code}）：{detail}",
                retryable=exc.response.status_code in {429, 500, 502, 503, 504},
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"GPT-SoVITS 服务不可用：{exc}",
                retryable=True,
            ) from exc

        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                result = response.json()
            except ValueError as exc:
                raise ProviderError("GPT-SoVITS 返回了无效 JSON") from exc
            path = Path(str(result.get("audio_path") or "")).expanduser().resolve()
            if not path.is_file():
                raise ProviderError(str(result.get("error") or "GPT-SoVITS 没有返回音频"))
            return SynthesisResult(path)

        if not response.content:
            raise ProviderError("GPT-SoVITS 返回了空音频")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        output = self.cache_dir / f"atri-{uuid.uuid4().hex}.wav"
        output.write_bytes(response.content)
        self._last_postprocess = None
        self._last_postprocess_error = ""
        if not self.postprocess_enabled:
            return SynthesisResult(output)
        try:
            processed = await asyncio.to_thread(
                postprocess_synthesized_audio,
                output,
                target_rms_dbfs=self.target_rms_dbfs,
                max_gain_db=self.max_gain_db,
            )
        except AudioPreprocessError as exc:
            self._last_postprocess_error = str(exc)
            output.unlink(missing_ok=True)
            raise ProviderError(
                f"合成音频质量检查失败：{exc}",
                retryable=True,
            ) from exc
        self._last_postprocess = {
            "duration_seconds": round(processed.duration_seconds, 3),
            "gain_db": round(processed.gain_db, 3),
            "trimmed_leading_seconds": round(processed.trimmed_leading_seconds, 3),
            "trimmed_trailing_seconds": round(processed.trimmed_trailing_seconds, 3),
        }
        try:
            validate_synthesized_speech_timing(
                spoken_text,
                text_language,
                processed.duration_seconds,
            )
        except AudioPreprocessError as exc:
            self._last_postprocess_error = str(exc)
            output.unlink(missing_ok=True)
            raise ProviderError(
                f"合成音频质量检查失败：{exc}",
                retryable=True,
            ) from exc
        return SynthesisResult(output, processed.duration_seconds)

    def prepare_spoken_text(
        self,
        request: VoiceRequest,
        profile: VoiceProfile,
    ) -> str:
        text_language = _tts_language(request.language, profile.text_language, request.text)
        return normalize_tts_text(
            self.pronunciations.apply(request.text, text_language),
            text_language,
        )

    async def _activate_profile(
        self,
        client: httpx.AsyncClient,
        profile: VoiceProfile,
    ) -> None:
        if not profile.gpt_weights and not profile.sovits_weights:
            return
        # Profiles may refer to the same files through the Unicode model root
        # or its ASCII junction. Compare the engine-facing paths so changing
        # language/reference does not reload identical multi-GB weights.
        weights = (
            _engine_weight_path(profile.gpt_weights),
            _engine_weight_path(profile.sovits_weights),
        )
        if weights == self._active_weights:
            return
        if not all(path and Path(path).is_file() for path in weights):
            raise ProviderError("语音模型权重不完整，请在 WebUI 查看候选模型状态")
        base_url = profile.api_url.rsplit("/", 1)[0]
        for endpoint, path in (
            ("set_sovits_weights", weights[1]),
            ("set_gpt_weights", weights[0]),
        ):
            response = await client.get(
                f"{base_url}/{endpoint}",
                params={"weights_path": path},
            )
            if response.is_error:
                detail = response.text[:500]
                raise ProviderError(f"GPT-SoVITS 切换权重失败：{detail}")
        self._active_weights = weights


def _engine_weight_path(value: str) -> str:
    path = Path(value).expanduser()
    try:
        relative = path.relative_to(ATRI_MODELS_ROOT)
    except ValueError:
        return str(path)
    alias = ASCII_ATRI_MODELS_ROOT / relative
    return str(alias) if alias.is_file() else str(path)


def create_asr_provider(config: VoiceServiceConfig) -> IsolatedSenseVoiceProvider:
    if config.asr_provider != "sensevoice":
        raise ProviderError(f"不支持的 ASR 提供器：{config.asr_provider}")
    return IsolatedSenseVoiceProvider(config)


def parse_sensevoice_output(raw: str) -> tuple[str, str, str]:
    tags = re.findall(r"<\|([^|>]+)\|>", raw or "")
    text = re.sub(r"<\|[^|>]+\|>", "", raw or "").strip()
    language = "auto"
    emotion = "neutral"
    language_map = {"zh": "zh", "en": "en", "ja": "ja", "yue": "yue", "ko": "ko"}
    emotion_map = {
        "HAPPY": "happy",
        "SAD": "sad",
        "ANGRY": "serious",
        "NEUTRAL": "neutral",
        "SURPRISE": "surprised",
    }
    for tag in tags:
        language = language_map.get(tag.lower(), language)
        emotion = emotion_map.get(tag.upper(), emotion)
    return text, language, emotion


def _sensevoice_result_text(result: Any) -> str:
    if isinstance(result, list) and result:
        item = result[0]
        if isinstance(item, dict):
            return str(item.get("text") or "")
        return str(item)
    if isinstance(result, dict):
        return str(result.get("text") or "")
    return str(result or "")


def _reference_context(
    profile: VoiceProfile,
    emotion: str,
    language: str = "auto",
) -> tuple[str, str, str]:
    emotion_reference = profile.emotion_references.get(emotion)
    emotion_prompt_text = profile.emotion_prompt_texts.get(emotion, "")
    emotion_prompt_language = (
        profile.emotion_prompt_languages.get(emotion)
        or _prompt_language(emotion_prompt_text, profile.prompt_language)
    )
    if emotion_reference and language not in {"", "auto"}:
        if emotion_prompt_language != language:
            emotion_reference = None
    language_reference = profile.language_references.get(language)
    reference = emotion_reference or language_reference or profile.reference_audio
    prompt_text = profile.prompt_text
    prompt_language = profile.prompt_language
    if emotion_reference:
        configured_prompt = emotion_prompt_text
        filename_prompt = Path(reference).stem.strip("… .")
        prompt_text = configured_prompt or (
            filename_prompt
            if filename_prompt and any(ord(char) > 127 for char in filename_prompt)
            else prompt_text
        )
        prompt_language = (
            emotion_prompt_language
            or _prompt_language(prompt_text, profile.prompt_language)
        )
    elif language_reference:
        prompt_text = profile.language_prompt_texts.get(language) or prompt_text
        prompt_language = profile.language_prompt_languages.get(language) or prompt_language
    return reference, prompt_text, prompt_language


def _auxiliary_reference_paths(
    profile: VoiceProfile,
    primary_reference: str,
    emotion: str,
    language: str,
) -> list[str]:
    candidates: list[str] = []
    if profile.emotion_references.get(emotion) == primary_reference:
        candidates.append(profile.language_references.get(language, ""))
    candidates.extend(profile.auxiliary_references)

    resolved: list[str] = []
    seen = {str(Path(primary_reference).expanduser())}
    for value in candidates:
        path = str(value or "").strip()
        if not path or path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        resolved.append(path)
        if len(resolved) >= 8:
            break
    return resolved


def _prompt_language(text: str, fallback: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return fallback


def _tts_inference_preset(
    profile: VoiceProfile,
    emotion: str,
    language: str,
) -> str:
    emotion_preset = profile.emotion_inference_presets.get(emotion)
    if not emotion_preset:
        return profile.inference_preset
    prompt_text = profile.emotion_prompt_texts.get(emotion, "")
    prompt_language = (
        profile.emotion_prompt_languages.get(emotion)
        or _prompt_language(prompt_text, profile.prompt_language)
    )
    return emotion_preset if prompt_language == language else profile.inference_preset


def _tts_language(requested: str, configured: str, text: str = "") -> str:
    language = requested if requested not in {"", "auto"} else configured
    if language not in {"", "auto"}:
        return language
    has_kana = bool(re.search(r"[\u3040-\u30ff]", text))
    has_han = bool(re.search(r"[\u4e00-\u9fff]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_kana:
        return "ja"
    if has_han:
        return "zh"
    return "en" if has_latin else "zh"


def _tts_style(
    emotion: str,
    intensity: float,
    *,
    preset: str = "stable",
) -> dict[str, float | int]:
    if preset == "fidelity":
        return {
            "top_k": 15,
            "top_p": 0.9,
            "temperature": 0.8,
            "speed_factor": 0.967,
            "fragment_interval": 0.311,
            "repetition_penalty": 1.35,
        }
    strength = min(1.0, max(0.0, float(intensity)))
    targets = {
        "neutral": (5, 0.76, 0.58, 1.0, 0.18, 1.30),
        "gentle": (5, 0.76, 0.56, 0.992, 0.20, 1.28),
        "happy": (8, 0.82, 0.64, 1.012, 0.16, 1.26),
        "shy": (5, 0.76, 0.57, 0.995, 0.205, 1.28),
        "sad": (5, 0.74, 0.54, 0.985, 0.225, 1.30),
        "serious": (4, 0.72, 0.52, 1.0, 0.18, 1.32),
        "sleepy": (4, 0.72, 0.52, 0.98, 0.225, 1.30),
        "surprised": (8, 0.82, 0.64, 1.015, 0.15, 1.25),
    }
    neutral = targets["neutral"]
    target = targets.get(emotion, neutral)

    def blended(index: int) -> float:
        return float(neutral[index]) + (
            float(target[index]) - float(neutral[index])
        ) * strength

    return {
        "top_k": max(1, int(round(blended(0)))),
        "top_p": round(blended(1), 3),
        "temperature": round(blended(2), 3),
        "speed_factor": round(blended(3), 3),
        "fragment_interval": round(blended(4), 3),
        "repetition_penalty": round(blended(5), 3),
    }


_CUT0_UNITS_LIMIT = 42

# 单次生成被判废时换用的切分方式。两种切分各有失效场景（见 synthesize 注释），
# 所以这里做成对称映射：谁出的废音频就换另一个。
_SPLIT_FALLBACK = {"cut0": "cut5", "cut5": "cut0"}


def _tts_split_method(text: str, language: str, *, preset: str = "stable") -> str:
    if preset == "fidelity":
        return "cut5"
    if language == "en":
        units = len(re.findall(r"[A-Za-z0-9]+", text))
    else:
        units = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9]", text))
    return "cut0" if units <= _CUT0_UNITS_LIMIT else "cut5"


def _alternate_split_method(split_method: str) -> str:
    """另一种切分方式；未知输入退化为 cut5（长句上更稳的一档）。"""
    return _SPLIT_FALLBACK.get(str(split_method or "").strip().lower(), "cut5")


def _candidate_was_rejected(error: ProviderError) -> bool:
    """这次生成的音频是否被**自家质量检查**判废（而非网络 / 引擎故障）。

    ``postprocess_synthesized_audio`` 与 ``validate_synthesized_speech_timing``
    抛的都是 ``AudioPreprocessError``，调用处又用 ``raise ... from exc`` 包成
    ``ProviderError``，所以看 ``__cause__`` 就能区分「生成的候选不合格」（值得换
    切分方式重试）与「GPT-SoVITS 不可用 / 返回空音频」（换切分方式没有意义）。
    """
    return isinstance(getattr(error, "__cause__", None), AudioPreprocessError)


def _http_response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = str(
            payload.get("message")
            or payload.get("error")
            or payload.get("detail")
            or ""
        ).strip()
        if detail:
            return detail[:500]
    return (response.text or response.reason_phrase or "未知错误").strip()[:500]


def _tts_seed(language: str) -> int:
    # The former seeds (19/42) reproducibly made this v2Pro checkpoint emit
    # long near-silent WAVs for ordinary short replies.  These alternates were
    # verified against Chinese, Japanese and English speech samples.
    return 9992 if language == "zh" else 10015
