from __future__ import annotations

import json
import re
import time
from typing import Any

from atri_qq_bot.config import BotConfig
from atri_qq_bot.runtime import MODEL_PROFILE_PATH, WEBUI_DIR
from .config_admin import mask_secret, read_env, update_env


MODEL_PRESETS = {
    "current": {
        "label": "保持当前配置",
        "description": "不覆盖任何模型字段，继续使用 .env 当前值。",
        "values": {},
    },
    "ollama_qwen3_4b": {
        "label": "本地 Ollama - Qwen3 4B",
        "description": "免费本地模型，适合低成本日常聊天，质量取决于本机模型。",
        "values": {
            "OPENAI_API_KEY": "ollama",
            "OPENAI_BASE_URL": "http://127.0.0.1:11434/v1",
            "OPENAI_MODEL": "qwen3:4b-instruct",
            "TEMPERATURE": "0.60",
            "FREQUENCY_PENALTY": "0.35",
            "MAX_TOKENS": "180",
        },
    },
    "ollama_qwen3_8b": {
        "label": "本地 Ollama - Qwen3 8B",
        "description": "本地质量更好一些，需要先在 Ollama 拉取对应模型。",
        "values": {
            "OPENAI_API_KEY": "ollama",
            "OPENAI_BASE_URL": "http://127.0.0.1:11434/v1",
            "OPENAI_MODEL": "qwen3:8b-instruct",
            "TEMPERATURE": "0.60",
            "FREQUENCY_PENALTY": "0.35",
            "MAX_TOKENS": "220",
        },
    },
    "deepseek_chat": {
        "label": "DeepSeek - deepseek-chat",
        "description": "适合日常聊天和泛用问答。需要你填写 DeepSeek API Key。",
        "values": {
            "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
            "OPENAI_MODEL": "deepseek-chat",
            "TEMPERATURE": "0.65",
            "FREQUENCY_PENALTY": "0.35",
            "MAX_TOKENS": "260",
        },
    },
    "deepseek_reasoner": {
        "label": "DeepSeek - deepseek-reasoner",
        "description": "更偏复杂推理和分析，日常女友聊天不一定比 chat 更自然。",
        "values": {
            "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
            "OPENAI_MODEL": "deepseek-reasoner",
            "TEMPERATURE": "0.60",
            "FREQUENCY_PENALTY": "0.35",
            "MAX_TOKENS": "320",
        },
    },
    "openai_compatible": {
        "label": "OpenAI 兼容接口",
        "description": "用于硅基流动、OpenRouter、火山等兼容接口，base_url/model/key 手动填。",
        "values": {
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OPENAI_MODEL": "gpt-4.1-mini",
            "TEMPERATURE": "0.65",
            "FREQUENCY_PENALTY": "0.35",
            "MAX_TOKENS": "260",
        },
    },
}
PROFILE_FIELDS = {
    "name",
    "provider",
    "base_url",
    "model",
    "api_key",
    "temperature",
    "frequency_penalty",
    "max_tokens",
}


def default_model_profiles() -> list[dict[str, Any]]:
    now = int(time.time())
    return [
        {
            "id": "ollama-qwen3-4b",
            "name": "本地 Ollama Qwen3 4B",
            "provider": "Ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3:4b-instruct",
            "api_key": "ollama",
            "temperature": "0.60",
            "frequency_penalty": "0.35",
            "max_tokens": "180",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "deepseek-official-chat",
            "name": "DeepSeek 官方 deepseek-chat",
            "provider": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "",
            "temperature": "0.65",
            "frequency_penalty": "0.35",
            "max_tokens": "260",
            "created_at": now,
            "updated_at": now,
        },
    ]


def load_model_profiles() -> list[dict[str, Any]]:
    if not MODEL_PROFILE_PATH.exists():
        return default_model_profiles()
    try:
        data = json.loads(MODEL_PROFILE_PATH.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return default_model_profiles()
    if isinstance(data, dict):
        profiles = data.get("profiles")
    else:
        profiles = data
    if not isinstance(profiles, list):
        return default_model_profiles()
    normalized = [normalize_model_profile(p) for p in profiles if isinstance(p, dict)]
    return normalized or default_model_profiles()


def save_model_profiles(profiles: list[dict[str, Any]]) -> None:
    WEBUI_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "profiles": profiles}
    MODEL_PROFILE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_model_profile(profile: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    name = str(profile.get("name") or "").strip()[:80]
    provider = str(profile.get("provider") or "").strip()[:40]
    model = str(profile.get("model") or "").strip()
    base_url = str(profile.get("base_url") or "").strip().rstrip("/")
    profile_id = str(profile.get("id") or slugify_profile_id(name or model or provider)).strip()
    return {
        "id": profile_id or f"profile-{now}",
        "name": name or model or "未命名模型",
        "provider": provider or infer_provider(base_url, model),
        "base_url": base_url,
        "model": model,
        "api_key": str(profile.get("api_key") or "").strip(),
        "temperature": str(profile.get("temperature") or "0.65").strip(),
        "frequency_penalty": str(profile.get("frequency_penalty") or "0.35").strip(),
        "max_tokens": str(profile.get("max_tokens") or "260").strip(),
        "created_at": int(profile.get("created_at") or now),
        "updated_at": int(profile.get("updated_at") or now),
    }


def slugify_profile_id(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-_")
    return value[:60]


def infer_provider(base_url: str, model: str) -> str:
    merged = f"{base_url} {model}".lower()
    if "deepseek" in merged:
        return "DeepSeek"
    if "127.0.0.1" in merged or "localhost" in merged or "ollama" in merged:
        return "Ollama"
    if "openai" in merged:
        return "OpenAI"
    return "OpenAI 兼容"


def public_model_profile(profile: dict[str, Any]) -> dict[str, Any]:
    item = dict(profile)
    api_key = str(item.pop("api_key", "") or "")
    item["has_api_key"] = bool(api_key)
    item["api_key_masked"] = mask_secret(api_key)
    return item


def model_profiles_payload(config: BotConfig) -> dict[str, Any]:
    profiles = load_model_profiles()
    current = {
        "name": infer_provider(config.openai_base_url, config.openai_model),
        "base_url": config.openai_base_url,
        "model": config.openai_model,
        "temperature": config.temperature,
        "frequency_penalty": config.frequency_penalty,
        "max_tokens": config.max_tokens,
        "has_api_key": bool(config.openai_api_key),
        "api_key_masked": mask_secret(config.openai_api_key or ""),
    }
    active_id = ""
    for profile in profiles:
        if (
            str(profile.get("base_url") or "").rstrip("/") == config.openai_base_url.rstrip("/")
            and str(profile.get("model") or "") == config.openai_model
            and str(profile.get("api_key") or "") == str(config.openai_api_key or "")
        ):
            active_id = str(profile.get("id") or "")
            break
    return {
        "path": str(MODEL_PROFILE_PATH),
        "active_id": active_id,
        "current": current,
        "profiles": [public_model_profile(p) for p in profiles],
    }


def upsert_model_profile(payload: dict[str, Any]) -> dict[str, Any]:
    incoming = {key: payload.get(key) for key in PROFILE_FIELDS if key in payload}
    incoming["id"] = str(payload.get("id") or "").strip()
    profiles = load_model_profiles()
    now = int(time.time())
    old: dict[str, Any] | None = None
    if incoming["id"]:
        old = next((p for p in profiles if p.get("id") == incoming["id"]), None)
    if old is None and str(incoming.get("name") or "").strip():
        old = next(
            (
                p
                for p in profiles
                if str(p.get("name") or "").strip().lower()
                == str(incoming.get("name") or "").strip().lower()
            ),
            None,
        )
    merged = dict(old or {})
    for key, value in incoming.items():
        if key == "api_key" and (str(value or "").strip() == "" or "*" in str(value or "")):
            continue
        if key == "id" and not value:
            continue
        merged[key] = value
    if not str(merged.get("api_key") or "").strip() and old:
        merged["api_key"] = str(old.get("api_key") or "")
    if not str(merged.get("api_key") or "").strip():
        current_key = read_env().get("OPENAI_API_KEY", "").strip()
        if current_key and current_key != "ollama" and "*" not in current_key:
            merged["api_key"] = current_key
    merged["created_at"] = int(merged.get("created_at") or now)
    merged["updated_at"] = now
    profile = normalize_model_profile(merged)
    if not profile["base_url"]:
        raise ValueError("接口地址不能为空")
    if not profile["model"]:
        raise ValueError("模型名称不能为空")
    if not profile["api_key"]:
        raise ValueError("API Key 不能为空；本地 Ollama 可以填 ollama")
    replaced = False
    for index, existing in enumerate(profiles):
        if existing.get("id") == profile["id"]:
            profiles[index] = profile
            replaced = True
            break
    if not replaced:
        profiles.append(profile)
    save_model_profiles(profiles)
    return profile


def delete_model_profile(profile_id: str) -> None:
    if not profile_id:
        raise ValueError("缺少模型档案 id")
    profiles = load_model_profiles()
    kept = [p for p in profiles if p.get("id") != profile_id]
    if len(kept) == len(profiles):
        raise ValueError("模型档案不存在")
    save_model_profiles(kept)


def activate_model_profile(profile_id: str) -> dict[str, Any]:
    if not profile_id:
        raise ValueError("缺少模型档案 id")
    profiles = load_model_profiles()
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if not profile:
        raise ValueError("模型档案不存在")
    if not str(profile.get("api_key") or "").strip():
        raise ValueError("这个模型档案还没有 API Key")
    update_env(
        {
            "OPENAI_API_KEY": profile["api_key"],
            "OPENAI_BASE_URL": profile["base_url"],
            "OPENAI_MODEL": profile["model"],
            "TEMPERATURE": profile["temperature"],
            "FREQUENCY_PENALTY": profile["frequency_penalty"],
            "MAX_TOKENS": profile["max_tokens"],
        }
    )
    return profile


