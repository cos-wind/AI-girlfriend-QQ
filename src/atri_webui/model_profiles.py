from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from atri_qq_bot.config import BotConfig
from atri_qq_bot.retrieval import SemanticMemoryRepository
from atri_qq_bot.runtime import MODEL_PROFILE_PATH, WEBUI_DIR
from .config_admin import mask_secret, read_env, update_env


OLLAMA_OPENAI_BASE_URL = "http://127.0.0.1:11434/v1"
OLLAMA_NATIVE_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODELS = Path(os.environ.get("LOCAL_MODELS_ROOT", r"D:\本地大模型\models"))

MODEL_PROFILE_TYPES: list[dict[str, str]] = [
    {
        "id": "chat",
        "name": "聊天模型",
        "description": "QQ 对话、人格回复、工具调用后的最终回复主模型。",
    },
    {
        "id": "vision",
        "name": "视觉模型",
        "description": "图片识别和视频抽帧分析使用的多模态模型。",
    },
    {
        "id": "embedding",
        "name": "向量模型",
        "description": "向量检索或语义索引用模型；当前项目暂未接入独立启用配置。",
    },
]
VALID_MODEL_PROFILE_TYPES = {item["id"] for item in MODEL_PROFILE_TYPES}

MODEL_PROVIDER_CATALOG: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "name": "本地 Ollama",
        "provider": "Ollama",
        "base_url": OLLAMA_OPENAI_BASE_URL,
        "api_key": "ollama",
        "temperature": "0.60",
        "frequency_penalty": "0.35",
        "max_tokens": "260",
        "models": [
            {"id": "qwen2.5:7b", "label": "Qwen2.5 7B"},
            {"id": "qwen3:4b-instruct", "label": "Qwen3 4B Instruct"},
            {"id": "deepseek-r1:8b", "label": "DeepSeek R1 8B"},
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek 官方",
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
        ],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "provider": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "gpt-4.1-mini", "label": "gpt-4.1-mini"},
            {"id": "gpt-4.1", "label": "gpt-4.1"},
            {"id": "gpt-4o-mini", "label": "gpt-4o-mini"},
        ],
    },
    {
        "id": "dashscope",
        "name": "通义千问 / DashScope",
        "provider": "DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "qwen-plus", "label": "qwen-plus"},
            {"id": "qwen-turbo", "label": "qwen-turbo"},
            {"id": "qwen-max", "label": "qwen-max"},
        ],
    },
    {
        "id": "moonshot",
        "name": "Moonshot / Kimi",
        "provider": "Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "moonshot-v1-8k", "label": "moonshot-v1-8k"},
            {"id": "moonshot-v1-32k", "label": "moonshot-v1-32k"},
            {"id": "moonshot-v1-128k", "label": "moonshot-v1-128k"},
        ],
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "provider": "智谱",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "glm-4-flash", "label": "glm-4-flash"},
            {"id": "glm-4-plus", "label": "glm-4-plus"},
        ],
    },
    {
        "id": "siliconflow",
        "name": "硅基流动",
        "provider": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "Qwen/Qwen2.5-7B-Instruct", "label": "Qwen2.5 7B Instruct"},
            {"id": "deepseek-ai/DeepSeek-V3", "label": "DeepSeek V3"},
            {"id": "deepseek-ai/DeepSeek-R1", "label": "DeepSeek R1"},
        ],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "provider": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "deepseek/deepseek-chat", "label": "deepseek/deepseek-chat"},
            {"id": "openai/gpt-4o-mini", "label": "openai/gpt-4o-mini"},
            {"id": "qwen/qwen-2.5-72b-instruct", "label": "qwen/qwen-2.5-72b-instruct"},
        ],
    },
    {
        "id": "custom",
        "name": "OpenAI 兼容接口",
        "provider": "OpenAI 兼容",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "temperature": "0.65",
        "frequency_penalty": "0.35",
        "max_tokens": "320",
        "models": [
            {"id": "gpt-4.1-mini", "label": "手动填写模型名"},
        ],
    },
]

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
        "label": "DeepSeek - V4 Flash",
        "description": "适合日常聊天和泛用问答，延迟和成本低于 Pro。需要 DeepSeek API Key。",
        "values": {
            "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
            "OPENAI_MODEL": "deepseek-v4-flash",
            "TEMPERATURE": "0.65",
            "FREQUENCY_PENALTY": "0.35",
            "MAX_TOKENS": "260",
        },
    },
    "deepseek_reasoner": {
        "label": "DeepSeek - V4 Pro",
        "description": "更偏复杂推理和分析，成本高于 Flash。",
        "values": {
            "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
            "OPENAI_MODEL": "deepseek-v4-pro",
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
    "model_type",
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
            "model_type": "chat",
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
            "name": "DeepSeek V4 Flash",
            "model_type": "chat",
            "provider": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
            "api_key": "",
            "temperature": "0.65",
            "frequency_penalty": "0.35",
            "max_tokens": "260",
            "created_at": now,
            "updated_at": now,
        },
    ]


def builtin_profile_signatures() -> dict[str, dict[str, str]]:
    return {
        "ollama-qwen3-4b": {
            "model_type": "chat",
            "provider": "Ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3:4b-instruct",
        },
        "deepseek-official-chat": {
            "model_type": "chat",
            "provider": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    }


def repair_builtin_profile_collisions(
    profiles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    signatures = builtin_profile_signatures()
    defaults = {profile["id"]: profile for profile in default_model_profiles()}
    used_ids: set[str] = set()
    repaired: list[dict[str, Any]] = []
    changed = False

    for profile in profiles:
        profile_id = str(profile.get("id") or "")
        signature = signatures.get(profile_id)
        if signature and not profile_matches_signature(profile, signature):
            moved = dict(profile)
            moved["id"] = unique_profile_id(
                slugify_profile_id(f"{moved.get('name') or moved.get('model')}-{moved.get('model')}"),
                used_ids,
            )
            repaired.append(moved)
            used_ids.add(str(moved["id"]))
            changed = True
            continue
        repaired.append(profile)
        used_ids.add(profile_id)

    if changed:
        existing_ids = {str(profile.get("id") or "") for profile in repaired}
        for profile_id, default in defaults.items():
            if profile_id not in existing_ids:
                repaired.append(default)
                existing_ids.add(profile_id)
    return repaired, changed


def profile_matches_signature(profile: dict[str, Any], signature: dict[str, str]) -> bool:
    return all(str(profile.get(key) or "").rstrip("/") == value.rstrip("/") for key, value in signature.items())


def unique_profile_id(base_id: str, used_ids: set[str]) -> str:
    base_id = base_id or f"profile-{int(time.time())}"
    candidate = base_id[:60]
    suffix = 2
    while candidate in used_ids or candidate in builtin_profile_signatures():
        tail = f"-{suffix}"
        candidate = f"{base_id[: 60 - len(tail)]}{tail}"
        suffix += 1
    return candidate


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
    if not normalized:
        return default_model_profiles()
    migrated, migrated_changed = migrate_deprecated_deepseek_profiles(normalized)
    repaired, repaired_changed = repair_builtin_profile_collisions(migrated)
    if migrated_changed or repaired_changed:
        save_model_profiles(repaired)
    return repaired


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
    model_type = normalize_model_type(profile.get("model_type"), model)
    return {
        "id": profile_id or f"profile-{now}",
        "name": name or model or "未命名模型",
        "model_type": model_type,
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


def migrate_deprecated_deepseek_profiles(
    profiles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    aliases = {
        "deepseek-chat": ("deepseek-v4-flash", "DeepSeek V4 Flash"),
        "deepseek-reasoner": ("deepseek-v4-pro", "DeepSeek V4 Pro"),
    }
    migrated: list[dict[str, Any]] = []
    changed = False
    for profile in profiles:
        item = dict(profile)
        base_url = str(item.get("base_url") or "").casefold()
        old_model = str(item.get("model") or "").strip().casefold()
        replacement = aliases.get(old_model)
        if "api.deepseek.com" in base_url and replacement is not None:
            item["model"] = replacement[0]
            if (
                str(item.get("id") or "") == "deepseek-official-chat"
                or str(item.get("name") or "").strip().casefold()
                in {"deepseek-chat", "deepseek 官方 deepseek-chat", "deepseek-reasoner"}
            ):
                item["name"] = replacement[1]
            item["updated_at"] = int(time.time())
            changed = True
        migrated.append(item)
    return migrated, changed


def normalize_model_type(value: Any, model: str = "") -> str:
    raw = str(value or "").strip().lower()
    if raw in VALID_MODEL_PROFILE_TYPES:
        return raw
    return infer_model_type(model)


def infer_model_type(model: str) -> str:
    lowered = str(model or "").lower()
    if any(token in lowered for token in ("bge", "embed", "embedding")):
        return "embedding"
    if any(token in lowered for token in ("vl", "vision", "visual", "qwen2.5-vl")):
        return "vision"
    return "chat"


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


def current_chat_profile(config: BotConfig) -> dict[str, Any]:
    return {
        "model_type": "chat",
        "name": infer_provider(config.openai_base_url, config.openai_model),
        "base_url": config.openai_base_url,
        "model": config.openai_model,
        "temperature": config.temperature,
        "frequency_penalty": config.frequency_penalty,
        "max_tokens": config.max_tokens,
        "has_api_key": bool(config.openai_api_key),
        "api_key_masked": mask_secret(config.openai_api_key or ""),
    }


def current_vision_profile(config: BotConfig) -> dict[str, Any]:
    model = config.toolbox_vision_model or ""
    base_url = config.toolbox_vision_base_url or ""
    api_key = config.toolbox_vision_api_key or ""
    return {
        "model_type": "vision",
        "name": infer_provider(base_url, model) if model or base_url else "未配置",
        "base_url": base_url,
        "model": model,
        "enabled": bool(config.toolbox_vision_enabled),
        "has_api_key": bool(api_key),
        "api_key_masked": mask_secret(api_key),
    }


def current_embedding_profile(config: BotConfig) -> dict[str, Any]:
    """将记忆检索配置映射成和聊天/视觉一致的当前模型卡片。"""

    model = str(getattr(config, "memory_embedding_model", "") or "")
    native_base_url = str(
        getattr(config, "memory_embedding_base_url", "http://127.0.0.1:11434") or ""
    ).rstrip("/")
    display_base_url = (
        native_base_url if native_base_url.endswith("/v1") else native_base_url + "/v1"
    )
    try:
        indexed_entries = SemanticMemoryRepository(config.memory_retrieval_path).embedding_count(model)
    except Exception:
        indexed_entries = 0
    return {
        "model_type": "embedding",
        "name": infer_provider(display_base_url, model) if model else "未配置",
        "base_url": display_base_url,
        "model": model,
        "enabled": bool(getattr(config, "memory_vector_enabled", False)),
        "has_api_key": True,
        "api_key_masked": "ollama",
        "retrieval_enabled": bool(getattr(config, "memory_retrieval_enabled", True)),
        "indexed_entries": indexed_entries,
    }


def profile_matches_current(profile: dict[str, Any], current: dict[str, Any], api_key: str | None) -> bool:
    return (
        str(profile.get("base_url") or "").rstrip("/") == str(current.get("base_url") or "").rstrip("/")
        and str(profile.get("model") or "") == str(current.get("model") or "")
        and str(profile.get("api_key") or "") == str(api_key or "")
    )


def model_profiles_payload(config: BotConfig) -> dict[str, Any]:
    profiles = load_model_profiles()
    current_by_type = {
        "chat": current_chat_profile(config),
        "vision": current_vision_profile(config),
        "embedding": current_embedding_profile(config),
    }
    active_ids: dict[str, str] = {}
    for profile in profiles:
        model_type = normalize_model_type(profile.get("model_type"), str(profile.get("model") or ""))
        if model_type == "chat" and profile_matches_current(
            profile, current_by_type["chat"], config.openai_api_key
        ):
            active_ids["chat"] = str(profile.get("id") or "")
        if model_type == "vision" and profile_matches_current(
            profile, current_by_type["vision"], config.toolbox_vision_api_key
        ):
            active_ids["vision"] = str(profile.get("id") or "")
        if (
            model_type == "embedding"
            and current_by_type["embedding"].get("enabled")
            and profile_matches_current(profile, current_by_type["embedding"], "ollama")
        ):
            active_ids["embedding"] = str(profile.get("id") or "")
    return {
        "path": str(MODEL_PROFILE_PATH),
        "active_id": active_ids.get("chat", ""),
        "active_ids": active_ids,
        "current": current_by_type["chat"],
        "current_by_type": current_by_type,
        "profiles": [public_model_profile(p) for p in profiles],
        "profile_types": MODEL_PROFILE_TYPES,
        "provider_catalog": MODEL_PROVIDER_CATALOG,
    }


def ollama_models_path() -> Path:
    configured = read_env().get("OLLAMA_MODELS", "").strip() or os.environ.get("OLLAMA_MODELS", "").strip()
    return Path(configured) if configured else DEFAULT_OLLAMA_MODELS


def local_models_payload(
    models_path: Path | None = None,
    *,
    include_api: bool = True,
) -> dict[str, Any]:
    models_path = models_path or ollama_models_path()
    api_models = query_ollama_models() if include_api else []
    manifest_models = scan_ollama_manifest_models(models_path)
    merged: dict[str, dict[str, Any]] = {}
    for model in manifest_models:
        merged[str(model["name"])] = model
    for model in api_models:
        merged[str(model["name"])] = model
    models = sorted(
        merged.values(),
        key=lambda item: (
            0 if item.get("source") == "ollama_api" else 1,
            str(item.get("name") or "").lower(),
        ),
    )
    return {
        "ok": True,
        "provider": "Ollama",
        "base_url": OLLAMA_OPENAI_BASE_URL,
        "api_key": "ollama",
        "models_path": str(models_path),
        "models_path_exists": models_path.exists(),
        "ollama_running": bool(api_models),
        "models": models,
    }


def query_ollama_models(timeout: float = 1.2) -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_NATIVE_BASE_URL}/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in models:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
        result.append(
            {
                "name": name,
                "source": "ollama_api",
                "runnable": True,
                "size": raw.get("size"),
                "modified_at": raw.get("modified_at"),
                "parameter_size": details.get("parameter_size"),
                "family": details.get("family"),
            }
        )
    return result


def scan_ollama_manifest_models(models_path: Path) -> list[dict[str, Any]]:
    manifest_root = next(
        (
            candidate
            for candidate in (models_path / "manifests", models_path / "models" / "manifests")
            if candidate.is_dir()
        ),
        None,
    )
    if manifest_root is None:
        return []
    registry_root = manifest_root / "registry.ollama.ai"
    scan_root = registry_root if registry_root.is_dir() else manifest_root
    result: list[dict[str, Any]] = []
    for path in scan_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(scan_root).parts
        except ValueError:
            continue
        if len(rel) < 2:
            continue
        model_name = rel[-2]
        tag = rel[-1]
        if not model_name or not tag:
            continue
        result.append(
            {
                "name": f"{model_name}:{tag}",
                "source": "manifest",
                "runnable": False,
                "manifest": str(path),
                "modified_at": path.stat().st_mtime,
            }
        )
    return dedupe_models(result)


def dedupe_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for model in models:
        name = str(model.get("name") or "").strip()
        if name:
            result[name] = model
    return list(result.values())


def upsert_model_profile(payload: dict[str, Any]) -> dict[str, Any]:
    incoming = {key: payload.get(key) for key in PROFILE_FIELDS if key in payload}
    incoming["id"] = str(payload.get("id") or "").strip()
    signature = builtin_profile_signatures().get(str(incoming["id"]))
    if signature and not profile_matches_signature(
        {
            "model_type": normalize_model_type(incoming.get("model_type"), str(incoming.get("model") or "")),
            "provider": incoming.get("provider"),
            "base_url": incoming.get("base_url"),
            "model": incoming.get("model"),
        },
        signature,
    ):
        incoming["id"] = ""
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
        env = read_env()
        model_type = normalize_model_type(merged.get("model_type"), str(merged.get("model") or ""))
        current_key = (
            env.get("TOOLBOX_VISION_API_KEY", "").strip()
            if model_type == "vision"
            else env.get("OPENAI_API_KEY", "").strip()
        )
        if not current_key and model_type == "vision":
            current_key = env.get("OPENAI_API_KEY", "").strip()
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
    model_type = normalize_model_type(profile.get("model_type"), str(profile.get("model") or ""))
    if model_type == "chat":
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
    elif model_type == "vision":
        update_env(
            {
                "TOOLBOX_VISION_ENABLED": True,
                "TOOLBOX_VISION_API_KEY": profile["api_key"],
                "TOOLBOX_VISION_BASE_URL": profile["base_url"],
                "TOOLBOX_VISION_MODEL": profile["model"],
            }
        )
    elif model_type == "embedding":
        base_url = str(profile["base_url"]).rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3].rstrip("/")
        if "11434" not in base_url and str(profile.get("provider") or "").casefold() != "ollama":
            raise ValueError("当前向量适配器使用 Ollama 原生接口，请选择本地 Ollama 向量模型")
        update_env(
            {
                "MEMORY_RETRIEVAL_ENABLED": True,
                "MEMORY_VECTOR_ENABLED": True,
                "MEMORY_EMBEDDING_MODEL": profile["model"],
                "MEMORY_EMBEDDING_BASE_URL": base_url,
            }
        )
    else:
        raise ValueError("不支持的模型类型")
    return profile


