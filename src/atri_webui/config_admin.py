from __future__ import annotations

from pathlib import Path
from typing import Any

from atri_qq_bot.config import BotConfig
from atri_qq_bot.runtime import ENV_PATH


CONFIG_FIELDS: dict[str, str] = {
    "OPENAI_API_KEY": "openai_api_key",
    "OPENAI_BASE_URL": "openai_base_url",
    "OPENAI_MODEL": "openai_model",
    "TEMPERATURE": "temperature",
    "FREQUENCY_PENALTY": "frequency_penalty",
    "MAX_TOKENS": "max_tokens",
    "REPLY_MODE": "reply_mode",
    "MESSAGE_SPLIT_MAX_CHARS": "message_split_max_chars",
    "MESSAGE_SPLIT_MAX_PARTS": "message_split_max_parts",
    "MESSAGE_SEND_DELAY_MIN": "message_send_delay_min",
    "MESSAGE_SEND_DELAY_MAX": "message_send_delay_max",
    "STICKER_CHANCE": "sticker_chance",
    "STICKER_COOLDOWN_SECONDS": "sticker_cooldown_seconds",
    "MEMORY_RETRIEVAL_ENABLED": "memory_retrieval_enabled",
    "MEMORY_RETRIEVAL_PATH": "memory_retrieval_path",
    "MEMORY_RETRIEVAL_MAX_CHARS": "memory_retrieval_max_chars",
    "MEMORY_RETRIEVAL_LORE_LIMIT": "memory_retrieval_lore_limit",
    "MEMORY_RETRIEVAL_MEMORY_LIMIT": "memory_retrieval_memory_limit",
    "MEMORY_VECTOR_ENABLED": "memory_vector_enabled",
    "MEMORY_EMBEDDING_MODEL": "memory_embedding_model",
    "MEMORY_EMBEDDING_BASE_URL": "memory_embedding_base_url",
    "MEMORY_EMBEDDING_TIMEOUT_SECONDS": "memory_embedding_timeout_seconds",
    "PROACTIVE_V2_ENABLED": "proactive_v2_enabled",
    "IDLE_PROACTIVE_ENABLED": "idle_proactive_enabled",
    "IDLE_MINUTES": "idle_minutes",
    "IDLE_COOLDOWN_MINUTES": "idle_cooldown_minutes",
    "GROUP_PROACTIVE_ENABLED": "group_proactive_enabled",
    "GROUP_PROACTIVE_IDLE_MINUTES": "group_proactive_idle_minutes",
    "GROUP_PROACTIVE_COOLDOWN_MINUTES": "group_proactive_cooldown_minutes",
    "GROUP_PROACTIVE_DAILY_LIMIT": "group_proactive_daily_limit",
    "GROUP_PROACTIVE_MAX_SILENCE_DAYS": "group_proactive_max_silence_days",
    "MORNING_GREETING_ENABLED": "morning_greeting_enabled",
    "MORNING_GREETING_TIME": "morning_greeting_time",
    "TOOLBOX_VISION_ENABLED": "toolbox_vision_enabled",
    "TOOLBOX_VISION_MODEL": "toolbox_vision_model",
    "TOOLBOX_VISION_FALLBACK_MODEL": "toolbox_vision_fallback_model",
    "TOOLBOX_VISION_BASE_URL": "toolbox_vision_base_url",
    "TOOLBOX_VISION_API_KEY": "toolbox_vision_api_key",
    "TOOLBOX_VISION_RETRY_COUNT": "toolbox_vision_retry_count",
    "TOOLBOX_VISION_RESOURCE_WAIT_SECONDS": "toolbox_vision_resource_wait_seconds",
    "TOOLBOX_VISION_UNLOAD_OTHER_OLLAMA_MODELS": "toolbox_vision_unload_other_ollama_models",
    "TOOLBOX_OCR_ENABLED": "toolbox_ocr_enabled",
    "VOICE_ASR_ENABLED": "voice_asr_enabled",
    "VOICE_TTS_ENABLED": "voice_tts_enabled",
    "VOICE_SERVICE_URL": "voice_service_url",
    "VOICE_SERVICE_TIMEOUT_SECONDS": "voice_service_timeout_seconds",
    "VOICE_PROFILE": "voice_profile",
    "VOICE_GROUP_ENABLED": "voice_group_enabled",
    "VOICE_REPLY_TO_VOICE": "voice_reply_to_voice",
    "VOICE_MAX_CHARS": "voice_max_chars",
    "VOICE_COOLDOWN_SECONDS": "voice_cooldown_seconds",
    "VOICE_INPUT_MAX_BYTES": "voice_input_max_bytes",
    "WEBUI_ENABLED": "webui_enabled",
    "WEBUI_PORT": "webui_port",
}

SECRET_KEYS = {"OPENAI_API_KEY", "TOOLBOX_VISION_API_KEY"}

def config_payload(config: BotConfig) -> dict[str, Any]:
    result: dict[str, Any] = {}
    env = read_env()
    for key, attr in CONFIG_FIELDS.items():
        value = getattr(config, attr)
        if isinstance(value, Path):
            value = str(value)
        raw = env.get(key, "")
        result[key] = {
            "value": mask_secret(str(value or "")) if key in SECRET_KEYS else value,
            "raw": mask_secret(raw) if key in SECRET_KEYS else raw,
            "has_secret": bool(raw) if key in SECRET_KEYS else False,
        }
    return result


def update_env(changes: dict[str, Any]) -> None:
    current = read_env()
    allowed = set(CONFIG_FIELDS)
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key in SECRET_KEYS and (
            str(value).strip() == "" or "*" in str(value)
        ):
            continue
        current[key] = normalize_env_value(value)
    write_env(current)


def read_env() -> dict[str, str]:
    result: dict[str, str] = {}
    if not ENV_PATH.exists():
        return result
    for line in ENV_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def write_env(values: dict[str, str]) -> None:
    existing_lines: list[str] = []
    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines()

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in values:
            new_lines.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            new_lines.append(line)

    for key in CONFIG_FIELDS:
        if key in values and key not in seen:
            new_lines.append(f"{key}={values[key]}")
    ENV_PATH.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def normalize_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if value == "ollama":
        return value
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}****{value[-4:]}"

