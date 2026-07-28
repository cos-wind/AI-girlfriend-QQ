from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from atri_qq_bot.runtime.paths import PROJECT_ROOT


LOCAL_MODELS_ROOT = Path(os.environ.get("LOCAL_MODELS_ROOT", r"D:\本地大模型\models"))
ATRI_MODELS_ROOT = LOCAL_MODELS_ROOT / "AI_ATRI"
ASCII_ATRI_MODELS_ROOT = Path(os.environ.get("ASCII_ATRI_MODELS_ROOT", r"D:\AtriModels"))


def default_voice_models_root() -> Path:
    return ATRI_MODELS_ROOT / "voice"


def default_modelscope_cache() -> Path:
    return default_voice_models_root() / "modelscope"


def default_sensevoice_model() -> str:
    local = (
        default_modelscope_cache()
        / "models"
        / "iic--SenseVoiceSmall"
        / "snapshots"
        / "master"
    )
    return str(local) if (local / "model.pt").is_file() else "iic/SenseVoiceSmall"


def default_vad_model() -> str:
    local = (
        default_modelscope_cache()
        / "models"
        / "iic--speech_fsmn_vad_zh-cn-16k-common-pytorch"
        / "snapshots"
        / "master"
    )
    return (
        str(local)
        if (local / "model.pt").is_file()
        else "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
    )


@dataclass(frozen=True)
class VoiceServiceConfig:
    host: str = "127.0.0.1"
    port: int = 8790
    asr_provider: str = "sensevoice"
    asr_model: str = "iic/SenseVoiceSmall"
    asr_device: str = "cuda:0"
    asr_vad_model: str = ""
    asr_vad_max_segment_ms: int = 30_000
    asr_preprocess_enabled: bool = True
    asr_max_duration_seconds: int = 300
    modelscope_cache: Path = field(default_factory=default_modelscope_cache)
    asr_lexicon_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data" / "voice" / "asr-hotwords.json"
    )
    tts_pronunciation_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data" / "voice" / "tts-pronunciations.json"
    )
    tts_postprocess_enabled: bool = True
    tts_target_rms_dbfs: float = -22.0
    tts_max_gain_db: float = 6.0
    profiles_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data" / "voice" / "profiles"
    )
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "voice" / "cache")
    original_library_dir: Path = field(
        default_factory=lambda: Path.home() / "Music" / "ATRI训练音频素材"
    )
    original_clip_enabled: bool = True
    tts_quality_gate_enabled: bool = False
    tts_quality_max_error_rate: float = 0.22
    tts_quality_retries: int = 1
    singing_enabled: bool = True
    singing_pipeline_manifest: Path = field(
        default_factory=lambda: PROJECT_ROOT
        / "data"
        / "voice"
        / "singing-pipeline.json"
    )
    singing_maximum_jobs: int = 50

    @classmethod
    def from_env(cls) -> "VoiceServiceConfig":
        modelscope_cache = _env_model_path("MODELSCOPE_CACHE", default_modelscope_cache())
        local_sensevoice = (
            modelscope_cache
            / "models"
            / "iic--SenseVoiceSmall"
            / "snapshots"
            / "master"
        )
        default_asr_model = (
            str(local_sensevoice)
            if (local_sensevoice / "model.pt").is_file()
            else "iic/SenseVoiceSmall"
        )
        return cls(
            host=os.getenv("ATRI_VOICE_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_env_int("ATRI_VOICE_PORT", 8790),
            asr_provider=os.getenv("ATRI_ASR_PROVIDER", "sensevoice").strip().lower(),
            asr_model=os.getenv("ATRI_ASR_MODEL", default_asr_model).strip(),
            asr_device=os.getenv("ATRI_ASR_DEVICE", "cpu").strip() or "cpu",
            asr_vad_model=os.getenv("ATRI_ASR_VAD_MODEL", default_vad_model()).strip(),
            asr_vad_max_segment_ms=max(
                5_000, min(60_000, _env_int("ATRI_ASR_VAD_MAX_SEGMENT_MS", 30_000))
            ),
            asr_preprocess_enabled=_env_bool("ATRI_ASR_PREPROCESS_ENABLED", True),
            asr_max_duration_seconds=max(
                10, min(1_800, _env_int("ATRI_ASR_MAX_DURATION_SECONDS", 300))
            ),
            modelscope_cache=modelscope_cache,
            asr_lexicon_path=_env_path(
                "ATRI_ASR_LEXICON_PATH", PROJECT_ROOT / "data" / "voice" / "asr-hotwords.json"
            ),
            tts_pronunciation_path=_env_path(
                "ATRI_TTS_PRONUNCIATION_PATH",
                PROJECT_ROOT / "data" / "voice" / "tts-pronunciations.json",
            ),
            tts_postprocess_enabled=_env_bool("ATRI_TTS_POSTPROCESS_ENABLED", True),
            tts_target_rms_dbfs=max(
                -30.0, min(-16.0, _env_float("ATRI_TTS_TARGET_RMS_DBFS", -22.0))
            ),
            tts_max_gain_db=max(
                0.0, min(12.0, _env_float("ATRI_TTS_MAX_GAIN_DB", 6.0))
            ),
            profiles_dir=_env_path(
                "ATRI_VOICE_PROFILES_DIR", PROJECT_ROOT / "data" / "voice" / "profiles"
            ),
            cache_dir=_env_path(
                "ATRI_VOICE_CACHE_DIR", PROJECT_ROOT / "data" / "voice" / "cache"
            ),
            original_library_dir=_env_path(
                "ATRI_ORIGINAL_VOICE_LIBRARY",
                Path.home() / "Music" / "ATRI训练音频素材",
            ),
            original_clip_enabled=_env_bool("ATRI_ORIGINAL_CLIP_ENABLED", True),
            tts_quality_gate_enabled=_env_bool("ATRI_TTS_QUALITY_GATE_ENABLED", False),
            tts_quality_max_error_rate=max(
                0.0, min(1.0, _env_float("ATRI_TTS_QUALITY_MAX_ERROR_RATE", 0.22))
            ),
            tts_quality_retries=max(
                0, min(3, _env_int("ATRI_TTS_QUALITY_RETRIES", 1))
            ),
            singing_enabled=_env_bool("ATRI_SINGING_ENABLED", True),
            singing_pipeline_manifest=_env_path(
                "ATRI_SINGING_PIPELINE_MANIFEST",
                PROJECT_ROOT / "data" / "voice" / "singing-pipeline.json",
            ),
            singing_maximum_jobs=max(
                10, min(200, _env_int("ATRI_SINGING_MAXIMUM_JOBS", 50))
            ),
        )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser().resolve()


def _env_model_path(name: str, default: Path) -> Path:
    path = Path(os.getenv(name, str(default))).expanduser()
    return path if path.is_absolute() else Path.cwd() / path
