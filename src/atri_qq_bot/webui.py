from __future__ import annotations

import asyncio
import cgi
import contextlib
import html
import json
import mimetypes
import re
import shutil
import subprocess
import time
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .config import BotConfig, load_config
from .persona import AtriReplyEngine
from .stickers import IMAGE_EXTENSIONS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
WEBUI_DIR = PROJECT_ROOT / "data" / "webui"
MODEL_PROFILE_PATH = WEBUI_DIR / "model_profiles.json"
STICKER_ROOT = PROJECT_ROOT / "data" / "stickers"
MEMORY_PATH = PROJECT_ROOT / "data" / "memory" / "users.json"
MEMORY_BACKUP_DIR = PROJECT_ROOT / "data" / "memory" / "backups"
STICKER_DELETED_DIR = STICKER_ROOT / "_deleted"
MAX_UPLOAD_BYTES = 8_000_000

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
    "TOOLBOX_VISION_BASE_URL": "toolbox_vision_base_url",
    "TOOLBOX_VISION_API_KEY": "toolbox_vision_api_key",
    "WEBUI_ENABLED": "webui_enabled",
    "WEBUI_PORT": "webui_port",
}

SECRET_KEYS = {"OPENAI_API_KEY", "TOOLBOX_VISION_API_KEY"}

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


class WebUIState:
    def __init__(self, config: BotConfig, server: Any) -> None:
        self.config = config
        self.server = server
        self.lock = asyncio.Lock()

    async def reload_config(self) -> BotConfig:
        async with self.lock:
            new_config = load_config()
            self.config = new_config
            self.server.config = new_config
            self.server.reply_engine.config = new_config
            self.server.tools.config = new_config
            self.server.tools.enabled = bool(new_config.toolbox_enabled)
            self.server.tools.timeout = float(new_config.toolbox_timeout_seconds)
            self.server.tools.max_bytes = int(new_config.toolbox_max_bytes)
            self.server.tools.vision_enabled = bool(new_config.toolbox_vision_enabled)
            self.server.tools.vision_model = str(
                new_config.toolbox_vision_model or new_config.openai_model or ""
            )
            self.server.tools.vision_base_url = str(
                new_config.toolbox_vision_base_url or new_config.openai_base_url or ""
            ).rstrip("/")
            self.server.tools.vision_api_key = (
                new_config.toolbox_vision_api_key or new_config.openai_api_key
            )
            return new_config


async def start_webui(config: BotConfig, onebot_server: Any) -> Any | None:
    if not getattr(config, "webui_enabled", True):
        return None

    host = str(getattr(config, "webui_host", "127.0.0.1") or "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        host = "127.0.0.1"
    port = int(getattr(config, "webui_port", 8787) or 8787)
    state = WebUIState(config, onebot_server)

    class Handler(AtriWebUIHandler):
        webui_state = state

    try:
        httpd = LocalThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"[webui] skipped because http://{host}:{port} is unavailable: {exc}")
        return None
    task = asyncio.create_task(asyncio.to_thread(httpd.serve_forever))
    httpd._atri_task = task  # type: ignore[attr-defined]
    print(f"[webui] Listening on http://{host}:{port}")
    return httpd


async def stop_webui(httpd: Any | None) -> None:
    if httpd is None:
        return
    httpd.shutdown()
    task = getattr(httpd, "_atri_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class AtriWebUIHandler(BaseHTTPRequestHandler):
    webui_state: WebUIState

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_html(render_index())
        if parsed.path == "/api/status":
            return self._send_json(self._status())
        if parsed.path == "/api/config":
            return self._send_json(config_payload(self.webui_state.config))
        if parsed.path == "/api/model-presets":
            return self._send_json({"presets": MODEL_PRESETS})
        if parsed.path == "/api/model-profiles":
            return self._send_json(model_profiles_payload(self.webui_state.config))
        if parsed.path == "/api/stickers":
            return self._send_json(sticker_summary())
        if parsed.path == "/api/stickers/file":
            return self._send_sticker_file(parsed.query)
        if parsed.path == "/api/memory":
            return self._send_json(memory_summary())
        if parsed.path == "/api/memory/detail":
            return self._send_json(memory_detail(parsed.query))
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            return self._handle_config_update()
        if parsed.path == "/api/model-profiles/save":
            return self._handle_model_profile_save()
        if parsed.path == "/api/model-profiles/delete":
            return self._handle_model_profile_delete()
        if parsed.path == "/api/model-profiles/activate":
            return self._handle_model_profile_activate()
        if parsed.path == "/api/test-chat":
            return self._handle_test_chat()
        if parsed.path == "/api/restart":
            return self._send_json(restart_background_services())
        if parsed.path == "/api/stickers/category":
            return self._handle_sticker_category()
        if parsed.path == "/api/stickers/upload":
            return self._handle_sticker_upload()
        if parsed.path == "/api/stickers/delete":
            return self._handle_sticker_delete()
        if parsed.path == "/api/memory/save":
            return self._handle_memory_save()
        if parsed.path == "/api/memory/delete":
            return self._handle_memory_delete()
        if parsed.path == "/api/memory/backup":
            backup = backup_memory("manual")
            return self._send_json({"ok": True, "backup": str(backup)})
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def _handle_config_update(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            update_env(payload)
            config = run_coro(self.webui_state.reload_config())
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "config": config_payload(config)})

    def _handle_model_profile_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            profile = upsert_model_profile(payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "profile": public_model_profile(profile)})

    def _handle_model_profile_delete(self) -> None:
        payload = self._read_json()
        profile_id = str((payload or {}).get("id") or "").strip()
        try:
            delete_model_profile(profile_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True})

    def _handle_model_profile_activate(self) -> None:
        payload = self._read_json()
        profile_id = str((payload or {}).get("id") or "").strip()
        try:
            profile = activate_model_profile(profile_id)
            config = run_coro(self.webui_state.reload_config())
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {
                "ok": True,
                "profile": public_model_profile(profile),
                "config": config_payload(config),
                "status": self._status(),
            }
        )

    def _handle_test_chat(self) -> None:
        payload = self._read_json()
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return self._send_error(HTTPStatus.BAD_REQUEST, "text is required")
        try:
            reply = run_coro(test_chat(self.webui_state.config, text))
        except Exception as exc:
            return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        self._send_json({"ok": True, "reply": reply})

    def _handle_sticker_category(self) -> None:
        payload = self._read_json()
        name = sanitize_category(str((payload or {}).get("name") or ""))
        if not name:
            return self._send_error(HTTPStatus.BAD_REQUEST, "分类名只能包含中文、英文、数字、横线和下划线")
        target = STICKER_ROOT / name
        target.mkdir(parents=True, exist_ok=True)
        self._send_json({"ok": True, "category": name, "path": str(target)})

    def _handle_sticker_upload(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0:
            return self._send_error(HTTPStatus.BAD_REQUEST, "empty upload")
        if content_length > MAX_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "文件太大，单个表情包最多 8MB")

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(content_length),
            },
        )
        category = sanitize_category(str(form.getfirst("category") or "default"))
        if not category:
            return self._send_error(HTTPStatus.BAD_REQUEST, "分类名不合法")
        file_item = form["file"] if "file" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            return self._send_error(HTTPStatus.BAD_REQUEST, "请选择图片文件")

        filename = safe_filename(str(file_item.filename))
        suffix = Path(filename).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            return self._send_error(HTTPStatus.BAD_REQUEST, "只支持 jpg/png/gif/webp")
        data = file_item.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return self._send_error(HTTPStatus.BAD_REQUEST, "文件太大，单个表情包最多 8MB")
        if not looks_like_image_bytes(data, suffix):
            return self._send_error(HTTPStatus.BAD_REQUEST, "文件内容不像有效图片")

        target_dir = STICKER_ROOT / category
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(filename).stem or "sticker"
        target = unique_path(target_dir / f"{stem}{suffix}")
        target.write_bytes(data)
        self._send_json({"ok": True, "file": sticker_file_payload(target)})

    def _handle_sticker_delete(self) -> None:
        payload = self._read_json()
        rel = str((payload or {}).get("path") or "")
        path = resolve_under(STICKER_ROOT, rel)
        if path is None or not path.is_file():
            return self._send_error(HTTPStatus.BAD_REQUEST, "文件不存在")
        STICKER_DELETED_DIR.mkdir(parents=True, exist_ok=True)
        target = unique_path(STICKER_DELETED_DIR / path.name)
        shutil.move(str(path), str(target))
        meta = path.with_suffix(path.suffix + ".json")
        if meta.exists():
            shutil.move(str(meta), str(unique_path(STICKER_DELETED_DIR / meta.name)))
        self._send_json({"ok": True, "moved_to": str(target)})

    def _handle_memory_save(self) -> None:
        payload = self._read_json()
        conversation_id = str((payload or {}).get("id") or "")
        content = (payload or {}).get("content")
        if not conversation_id or not isinstance(content, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "参数不完整")
        try:
            backup = save_memory_conversation(conversation_id, content)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "backup": str(backup)})

    def _handle_memory_delete(self) -> None:
        payload = self._read_json()
        conversation_id = str((payload or {}).get("id") or "")
        if not conversation_id:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少会话 id")
        try:
            backup = delete_memory_conversation(conversation_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "backup": str(backup)})

    def _status(self) -> dict[str, Any]:
        config = self.webui_state.config
        return {
            "atri": is_port_listening(int(config.port)),
            "napcat": has_established_port(int(config.port)),
            "ollama": is_port_listening(11434),
            "webui": True,
            "bot_qq": config.bot_qq,
            "onebot": f"ws://{config.host}:{config.port}/onebot",
            "webui_url": f"http://{config.webui_host}:{config.webui_port}",
            "model": config.openai_model,
            "base_url": config.openai_base_url,
            "reply_mode": config.reply_mode,
        }

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 1024 * 1024))
        return json.loads(raw.decode("utf-8"))

    def _send_sticker_file(self, query: str) -> None:
        rel = parse_qs(query).get("path", [""])[0]
        path = resolve_under(STICKER_ROOT, rel)
        if path is None or not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            return self._send_error(HTTPStatus.NOT_FOUND, "image not found")
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"ok": False, "error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_coro(coro: Any) -> Any:
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop())
    return future.result(timeout=90)


_LOOP: asyncio.AbstractEventLoop | None = None


def _main_loop() -> asyncio.AbstractEventLoop:
    if _LOOP is None:
        raise RuntimeError("webui loop is not initialized")
    return _LOOP


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _LOOP
    _LOOP = loop


async def test_chat(config: BotConfig, text: str) -> str:
    engine = AtriReplyEngine(
        replace(config, idle_proactive_enabled=False, group_proactive_enabled=False)
    )
    return await engine.reply("webui:test", text, "主人", observed=False)


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


def hidden_subprocess_startupinfo() -> Any | None:
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = 0
    return startupinfo


def run_hidden(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        startupinfo=hidden_subprocess_startupinfo(),
    )


def is_port_listening(port: int) -> bool:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"if (Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
    ]
    return run_hidden(command).returncode == 0


def has_established_port(port: int) -> bool:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$c=Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
            f"Where-Object {{ $_.LocalPort -eq {port} -or $_.RemotePort -eq {port} }}; "
            "if ($c) { exit 0 } else { exit 1 }"
        ),
    ]
    return run_hidden(command).returncode == 0


def restart_background_services() -> dict[str, Any]:
    script = PROJECT_ROOT / "tools" / "start-with-qq.vbs"
    if not script.exists():
        script = PROJECT_ROOT / "tools" / "start-with-qq.ps1"
    try:
        if script.suffix.lower() == ".vbs":
            subprocess.Popen(["wscript.exe", str(script)], cwd=str(PROJECT_ROOT))
        else:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                cwd=str(PROJECT_ROOT),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return {"ok": True, "message": "后台重启命令已发出"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def sticker_summary() -> dict[str, Any]:
    STICKER_ROOT.mkdir(parents=True, exist_ok=True)
    folders = []
    for child in sorted(STICKER_ROOT.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        files = [
            sticker_file_payload(path)
            for path in sorted(child.rglob("*"), key=lambda p: p.name.lower())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        folders.append(
            {
                "name": child.name,
                "count": len(files),
                "path": str(child),
                "files": files[:80],
            }
        )
    return {"path": str(STICKER_ROOT), "folders": folders}


def sticker_file_payload(path: Path) -> dict[str, Any]:
    rel = path.relative_to(STICKER_ROOT).as_posix()
    return {
        "name": path.name,
        "path": rel,
        "size": path.stat().st_size,
        "url": f"/api/stickers/file?path={url_escape(rel)}",
    }


def sanitize_category(value: str) -> str:
    value = value.strip().replace("\\", "_").replace("/", "_")
    if not value or value.startswith("."):
        return ""
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]{1,40}", value):
        return ""
    if value.lower() in {"con", "prn", "aux", "nul"}:
        return ""
    return value


def safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    name = re.sub(r"[^\w\-.()\u4e00-\u9fff]+", "_", name)
    return name[:120] or f"sticker_{int(time.time())}.jpg"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


def looks_like_image_bytes(data: bytes, suffix: str) -> bool:
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def resolve_under(root: Path, rel: str) -> Path | None:
    try:
        rel = unquote(rel).replace("\\", "/").lstrip("/")
        path = (root / rel).resolve()
        root_resolved = root.resolve()
        if path == root_resolved or root_resolved in path.parents:
            return path
    except Exception:
        return None
    return None


def url_escape(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def memory_summary() -> dict[str, Any]:
    data = load_memory_data()
    conversations = memory_conversations(data)
    items = []
    for key, item in sorted(
        conversations.items(),
        key=lambda pair: float((pair[1] or {}).get("last_user_at") or 0),
        reverse=True,
    ):
        if not isinstance(item, dict):
            continue
        display_name = memory_display_name(key, item)
        items.append(
            {
                "id": key,
                "type": memory_type_label(key),
                "display_name": display_name,
                "summary": natural_memory_summary(item),
                "messages": item.get("message_count", 0),
                "last_user_at": item.get("last_user_at"),
                "last_bot_at": item.get("last_bot_at"),
                "affection": item.get("affection_score"),
                "activity": item.get("group_activity_score"),
                "target": item.get("target") or {},
                "history_count": len(item.get("history") or []),
            }
        )
    return {"path": str(MEMORY_PATH), "conversations": len(items), "items": items}


def memory_detail(query: str) -> dict[str, Any]:
    conversation_id = parse_qs(query).get("id", [""])[0]
    data = load_memory_data()
    conversations = memory_conversations(data)
    item = conversations.get(conversation_id)
    if not isinstance(item, dict):
        return {"ok": False, "error": "memory not found"}
    return {
        "ok": True,
        "id": conversation_id,
        "display_name": memory_display_name(conversation_id, item),
        "natural": natural_memory_detail(item),
        "content": item,
    }


def save_memory_conversation(conversation_id: str, content: dict[str, Any]) -> Path:
    data = load_memory_data()
    conversations = memory_conversations(data)
    if conversation_id not in conversations:
        raise ValueError("会话不存在")
    backup = backup_memory("edit")
    conversations[conversation_id] = content
    write_memory_data(data)
    return backup


def delete_memory_conversation(conversation_id: str) -> Path:
    data = load_memory_data()
    conversations = memory_conversations(data)
    if conversation_id not in conversations:
        raise ValueError("会话不存在")
    backup = backup_memory("delete")
    conversations.pop(conversation_id, None)
    write_memory_data(data)
    return backup


def load_memory_data() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return {"version": 2, "conversations": {}}
    data = json.loads(MEMORY_PATH.read_text(encoding="utf-8-sig", errors="replace"))
    return data if isinstance(data, dict) else {"version": 2, "conversations": {}}


def memory_conversations(data: dict[str, Any]) -> dict[str, Any]:
    conversations = data.setdefault("conversations", {})
    if not isinstance(conversations, dict):
        data["conversations"] = {}
        return data["conversations"]
    return conversations


def write_memory_data(data: dict[str, Any]) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_memory(reason: str) -> Path:
    MEMORY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    target = MEMORY_BACKUP_DIR / f"users.webui-{reason}-{timestamp}.json"
    if MEMORY_PATH.exists():
        shutil.copy2(MEMORY_PATH, target)
    else:
        target.write_text(json.dumps({"version": 2, "conversations": {}}, indent=2), encoding="utf-8")
    return target


def memory_type_label(conversation_id: str) -> str:
    if conversation_id.startswith("private:"):
        return "私聊"
    if ":user:" in conversation_id:
        return "群内用户"
    if conversation_id.startswith("group:"):
        return "群聊"
    return "未知"


def memory_display_name(conversation_id: str, item: dict[str, Any]) -> str:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    history = item.get("history") if isinstance(item.get("history"), list) else []
    nickname = latest_nickname(history)
    user_id = str(target.get("user_id") or parse_memory_id_piece(conversation_id, "private") or "")
    group_id = str(target.get("group_id") or parse_memory_id_piece(conversation_id, "group") or "")
    if conversation_id.startswith("private:"):
        if nickname:
            return f"{nickname}（QQ {user_id or '未知'}）"
        return f"QQ {user_id or conversation_id.removeprefix('private:')}"
    if ":user:" in conversation_id:
        group_piece = group_id or "未知群"
        user_piece = str(target.get("user_id") or parse_memory_id_piece(conversation_id, "user") or "")
        if nickname:
            return f"{nickname}（群 {group_piece} / QQ {user_piece or '未知'}）"
        return f"群 {group_piece} 的 QQ {user_piece or '未知'}"
    if conversation_id.startswith("group:"):
        return f"群 {group_id or conversation_id.removeprefix('group:')}"
    return nickname or conversation_id


def parse_memory_id_piece(conversation_id: str, kind: str) -> str:
    if kind == "private" and conversation_id.startswith("private:"):
        return conversation_id.split(":", 1)[1]
    if kind == "group" and conversation_id.startswith("group:"):
        parts = conversation_id.split(":")
        return parts[1] if len(parts) > 1 else ""
    if kind == "user" and ":user:" in conversation_id:
        return conversation_id.rsplit(":user:", 1)[1]
    return ""


def latest_nickname(history: list[Any]) -> str:
    for entry in reversed(history[-200:]):
        if not isinstance(entry, dict):
            continue
        nickname = str(entry.get("nickname") or "").strip()
        if nickname and not looks_like_bad_text(nickname):
            return nickname[:40]
    return ""


def natural_memory_summary(item: dict[str, Any]) -> str:
    lines = [line for line in natural_memory_detail(item).splitlines() if line.strip()]
    return "；".join(lines[:3])[:180] or "暂无可读摘要，可能只有原始聊天统计。"


def natural_memory_detail(item: dict[str, Any]) -> str:
    lines: list[str] = []
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l1 = [m for m in structured.get("l1", []) if isinstance(m, dict)]
    l2 = [m for m in structured.get("l2", []) if isinstance(m, dict)]
    rules = item.get("accepted_iteration_rules") if isinstance(item.get("accepted_iteration_rules"), list) else []
    topics = item.get("topic_words") if isinstance(item.get("topic_words"), list) else []
    history = item.get("history") if isinstance(item.get("history"), list) else []

    profile_lines = natural_memory_values(l1, limit=5)
    if profile_lines:
        lines.append("用户信息：" + "；".join(profile_lines))

    event_lines = natural_memory_values(l2, limit=5)
    if event_lines:
        lines.append("最近重要事件：" + "；".join(event_lines))

    clean_topics = [shorten_plain(str(x), 18) for x in topics if useful_plain_text(str(x))][:8]
    if clean_topics:
        lines.append("常聊话题：" + "、".join(clean_topics))

    clean_rules = [
        shorten_plain(str(rule.get("rule") or ""), 42)
        for rule in rules
        if isinstance(rule, dict) and useful_plain_text(str(rule.get("rule") or ""))
    ][:4]
    if clean_rules:
        lines.append("用户明确要求：" + "；".join(clean_rules))

    recent = []
    for entry in history[-10:]:
        if not isinstance(entry, dict):
            continue
        role = "用户" if entry.get("role") == "user" else "亚托莉"
        text = str(entry.get("text") or "").strip()
        if useful_plain_text(text):
            recent.append(f"{role}：{shorten_plain(text, 36)}")
    if recent:
        lines.append("最近聊天：" + " / ".join(recent[-4:]))

    if not lines:
        lines.append("暂无可读摘要。可以在下方高级编辑里查看和修改原始 JSON。")
    return "\n".join(lines)


def natural_memory_values(memories: list[dict[str, Any]], limit: int = 5) -> list[str]:
    result: list[str] = []
    for memory in memories:
        value = str(memory.get("value") or memory.get("key") or "").strip()
        category = str(memory.get("category") or "").strip()
        if not useful_plain_text(value):
            continue
        label = memory_category_label(category)
        text = shorten_plain(value, 34)
        result.append(f"{label}{text}" if label else text)
        if len(result) >= limit:
            break
    return result


def memory_category_label(category: str) -> str:
    labels = {
        "interest": "兴趣：",
        "profile_fact": "资料：",
        "communication_style": "说话习惯：",
        "schedule": "日程：",
        "event": "事件：",
        "important_interaction": "互动：",
    }
    return labels.get(category, "")


def useful_plain_text(text: str) -> bool:
    text = text.strip()
    if not text or len(text) < 2:
        return False
    if looks_like_bad_text(text):
        return False
    if re.fullmatch(r"[\W_0-9]+", text):
        return False
    return True


def looks_like_bad_text(text: str) -> bool:
    if "\ufffd" in text:
        return True
    if re.search(r"[锟斤拷]{2,}|[�]{1,}", text):
        return True
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_count < 6:
        return False
    mojibake_hits = len(re.findall(r"[绋佹浣犳槸鍚楃殑鐢ㄦ埛鎴戜笉]", text))
    return mojibake_hits / max(chinese_count, 1) > 0.65


def shorten_plain(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _legacy_render_index() -> str:
    preset_options = "\n".join(
        f'<option value="{html.escape(key)}">{html.escape(value["label"])}</option>'
        for key, value in MODEL_PRESETS.items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>亚托莉控制台</title>
  <style>
    :root {{ --bg:#f6f7fb; --panel:#fff; --ink:#1f2937; --muted:#667085; --line:#d7dce7; --blue:#2563eb; --blue2:#eff4ff; --green:#16803c; --red:#c02626; --orange:#b45309; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Microsoft YaHei UI","Segoe UI",Arial,sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ padding:22px 28px 14px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:2; }}
    h1 {{ margin:0 0 5px; font-size:22px; letter-spacing:0; }}
    h2 {{ margin:0 0 14px; font-size:16px; }}
    h3 {{ margin:16px 0 10px; font-size:14px; }}
    .sub,.note {{ color:var(--muted); font-size:13px; line-height:1.7; }}
    main {{ display:grid; grid-template-columns:300px 1fr; gap:18px; padding:18px; max-width:1360px; margin:0 auto; }}
    aside, section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .tabs {{ display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }}
    button {{ border:0; border-radius:6px; background:var(--blue); color:#fff; padding:10px 14px; cursor:pointer; font-weight:700; }}
    button.secondary {{ background:#475467; }}
    button.ghost {{ background:var(--blue2); color:#1e3a8a; }}
    button.warn {{ background:var(--orange); }}
    button.danger {{ background:var(--red); }}
    .tab {{ background:#eef2f6; color:#344054; }}
    .tab.active {{ background:var(--blue); color:#fff; }}
    .panel {{ display:none; }}
    .panel.active {{ display:block; }}
    .status {{ display:grid; gap:10px; }}
    .pill {{ display:flex; justify-content:space-between; align-items:center; gap:8px; padding:10px 12px; border:1px solid var(--line); border-radius:6px; }}
    .ok {{ color:var(--green); font-weight:700; }}
    .bad {{ color:var(--red); font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(2, minmax(220px,1fr)); gap:12px; }}
    label {{ display:grid; gap:6px; color:#344054; font-size:13px; }}
    input, select, textarea {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; }}
    textarea {{ min-height:150px; resize:vertical; font-family:Consolas,"Microsoft YaHei UI",monospace; }}
    .row {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }}
    .out {{ white-space:pre-wrap; background:#101828; color:#f2f4f7; border-radius:6px; padding:12px; min-height:72px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ text-align:left; border-bottom:1px solid var(--line); padding:8px; vertical-align:top; }}
    tr:hover {{ background:#f8fafc; }}
    .split {{ display:grid; grid-template-columns:minmax(300px, 0.9fr) minmax(360px, 1.1fr); gap:14px; }}
    .scroll {{ max-height:560px; overflow:auto; border:1px solid var(--line); border-radius:6px; }}
    .thumbs {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(116px,1fr)); gap:10px; }}
    .thumb {{ border:1px solid var(--line); border-radius:7px; padding:8px; background:#fff; }}
    .thumb img {{ width:100%; height:92px; object-fit:contain; background:#f2f4f7; border-radius:5px; }}
    .thumb small {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); margin-top:6px; }}
    .mono {{ font-family:Consolas,monospace; }}
    @media (max-width: 920px) {{ main,.split {{ grid-template-columns:1fr; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>亚托莉控制台</h1>
    <div class="sub">本地页面，只监听 127.0.0.1。这里可以改模型、上传表情包、查看和编辑记忆。</div>
  </header>
  <main>
    <aside>
      <h2>运行状态</h2>
      <div class="status" id="status"></div>
      <div class="row">
        <button class="ghost" onclick="loadStatus()">刷新</button>
        <button class="secondary" onclick="restartServices()">后台重启</button>
      </div>
      <p class="note">模型配置保存后会影响新的 QQ 消息。DeepSeek 预设不会替你生成 key，key 需要你自己填。</p>
    </aside>
    <section>
      <div class="tabs">
        <button class="tab active" onclick="showTab(event,'model')">模型配置</button>
        <button class="tab" onclick="showTab(event,'stickers')">表情包</button>
        <button class="tab" onclick="showTab(event,'memory')">记忆</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
      </div>

      <div id="model" class="panel active">
        <h2>模型配置选项</h2>
        <label>模型预设
          <select id="MODEL_PRESET" onchange="applyPreset(this.value)">
            {preset_options}
          </select>
        </label>
        <p class="note" id="presetNote">不选择预设时保持当前默认配置。</p>
        <div class="grid" id="configForm"></div>
        <div class="row">
          <button onclick="saveConfig()">保存配置</button>
          <button class="ghost" onclick="loadConfig()">恢复页面当前值</button>
        </div>
      </div>

      <div id="stickers" class="panel">
        <h2>表情包管理</h2>
        <div class="grid">
          <label>新建情绪分类<input id="newCategory" placeholder="例如 comfort / happy / 摸摸头"></label>
          <label>上传到分类<select id="uploadCategory"></select></label>
        </div>
        <div class="row">
          <button onclick="createCategory()">新建分类</button>
          <input id="stickerFile" type="file" accept=".jpg,.jpeg,.png,.gif,.webp,image/*">
          <button onclick="uploadSticker()">上传表情包</button>
        </div>
        <p class="note" id="stickerInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>分类</th><th>数量</th><th>位置</th></tr></thead><tbody id="stickerRows"></tbody></table></div>
          <div>
            <h3 id="stickerFolderTitle">预览</h3>
            <div class="thumbs" id="stickerPreview"></div>
          </div>
        </div>
      </div>

      <div id="memory" class="panel">
        <h2>记忆管理</h2>
        <div class="row">
          <button class="ghost" onclick="loadMemory()">刷新记忆</button>
          <button class="warn" onclick="backupMemory()">手动备份</button>
        </div>
        <p class="note" id="memoryInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>会话</th><th>类型</th><th>消息</th><th>操作</th></tr></thead><tbody id="memoryRows"></tbody></table></div>
          <div>
            <h3 id="memoryTitle">详情</h3>
            <textarea id="memoryEditor" spellcheck="false"></textarea>
            <div class="row">
              <button onclick="saveMemory()">保存当前记忆</button>
              <button class="danger" onclick="deleteMemory()">删除当前会话记忆</button>
            </div>
            <p class="note">保存和删除前都会自动备份。这里只改记忆 JSON，不改底层提示词。</p>
          </div>
        </div>
      </div>

      <div id="test" class="panel">
        <h2>测试一句话</h2>
        <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
        <div class="row"><button onclick="testChat()">发送测试</button></div>
        <div class="out" id="testOut"></div>
      </div>
    </section>
  </main>

<script>
const fields = [
  ["OPENAI_API_KEY","API Key","password"],
  ["OPENAI_BASE_URL","接口地址","text"],
  ["OPENAI_MODEL","聊天模型","text"],
  ["TEMPERATURE","温度","number"],
  ["FREQUENCY_PENALTY","重复惩罚","number"],
  ["MAX_TOKENS","最大输出","number"],
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["IDLE_PROACTIVE_ENABLED","私聊主动关心","checkbox"],
  ["IDLE_MINUTES","私聊空闲分钟","number"],
  ["IDLE_COOLDOWN_MINUTES","主动关心冷却","number"],
  ["GROUP_PROACTIVE_ENABLED","群聊主动发言","checkbox"],
  ["GROUP_PROACTIVE_IDLE_MINUTES","群聊冷场分钟","number"],
  ["GROUP_PROACTIVE_COOLDOWN_MINUTES","群聊主动冷却","number"],
  ["GROUP_PROACTIVE_DAILY_LIMIT","单群日上限","number"],
  ["MORNING_GREETING_ENABLED","早安启用","checkbox"],
  ["MORNING_GREETING_TIME","早安时间","text"],
  ["TOOLBOX_VISION_ENABLED","图片识别","checkbox"],
  ["TOOLBOX_VISION_MODEL","视觉模型","text"],
  ["TOOLBOX_VISION_BASE_URL","视觉接口","text"],
  ["TOOLBOX_VISION_API_KEY","视觉 API Key","password"]
];
let presets = {json.dumps(MODEL_PRESETS, ensure_ascii=False)};
let currentMemoryId = "";
function $(id) {{ return document.getElementById(id); }}
async function api(path, opts={{}}) {{
  const res = await fetch(path, {{headers:{{'Content-Type':'application/json'}}, ...opts}});
  const data = await res.json();
  if(!res.ok) throw new Error(data.error || res.statusText);
  return data;
}}
function showTab(event, id) {{
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active'); $(id).classList.add('active');
  if(id==='stickers') loadStickers();
  if(id==='memory') loadMemory();
}}
async function loadStatus() {{
  const s = await api('/api/status');
  $('status').innerHTML = [
    ['Atri 服务', s.atri], ['NapCat 连接', s.napcat], ['Ollama', s.ollama], ['WebUI', s.webui]
  ].map(([k,v])=>`<div class="pill"><span>${{k}}</span><span class="${{v?'ok':'bad'}}">${{v?'正常':'未连接'}}</span></div>`).join('')
  + `<p class="note">QQ：${{s.bot_qq}}<br>模型：${{s.model}}<br>接口：${{s.base_url}}<br>OneBot：${{s.onebot}}</p>`;
}}
async function loadConfig() {{
  const cfg = await api('/api/config');
  $('configForm').innerHTML = fields.map(([key,label,type])=>{{
    const item = cfg[key] || {{}}; let value = item.raw || item.value || '';
    if(type==='select') return `<label>${{label}}<select id="${{key}}"><option>private</option><option>mention</option><option>smart</option><option>all</option></select></label>`;
    if(type==='checkbox') return `<label>${{label}}<input id="${{key}}" type="checkbox" ${{String(value).toLowerCase()==='true'?'checked':''}}></label>`;
    if(type==='password') {{
      const placeholder = item.has_secret ? '已保存，留空则保持原值' : '未设置';
      return `<label>${{label}}<input id="${{key}}" type="password" placeholder="${{placeholder}}"></label>`;
    }}
    return `<label>${{label}}<input id="${{key}}" type="${{type}}" step="0.01" value="${{String(value).replaceAll('"','&quot;')}}"></label>`;
  }}).join('');
  for (const [key,,type] of fields) if(type==='select' && cfg[key]) $(key).value = cfg[key].raw || cfg[key].value;
}}
function applyPreset(key) {{
  const preset = presets[key] || presets.current;
  $('presetNote').textContent = preset.description || '保持当前配置。';
  for (const [field, value] of Object.entries(preset.values || {{}})) {{
    const el = $(field);
    if (el) el.value = value;
  }}
}}
async function saveConfig() {{
  const body = {{}};
  for (const [key,,type] of fields) {{
    const el = $(key); body[key] = type==='checkbox' ? el.checked : el.value;
  }}
  await api('/api/config', {{method:'POST', body:JSON.stringify(body)}});
  await loadConfig(); await loadStatus();
  alert('保存完成，新消息会使用新配置。');
}}
async function loadStickers() {{
  const s = await api('/api/stickers');
  $('stickerInfo').textContent = `表情包根目录：${{s.path}}`;
  $('uploadCategory').innerHTML = (s.folders||[]).filter(f=>!f.name.startsWith('_deleted')).map(f=>`<option value="${{f.name}}">${{f.name}} (${{f.count}})</option>`).join('');
  $('stickerRows').innerHTML = (s.folders||[]).map(f=>`<tr><td><button class="ghost" onclick='previewFolder(${{JSON.stringify(f)}})'>${{f.name}}</button></td><td>${{f.count}}</td><td class="mono">${{f.path}}</td></tr>`).join('');
  if ((s.folders||[]).length) previewFolder(s.folders[0]);
}}
function previewFolder(folder) {{
  $('stickerFolderTitle').textContent = `预览：${{folder.name}}`;
  $('stickerPreview').innerHTML = (folder.files||[]).map(file=>`
    <div class="thumb">
      <img src="${{file.url}}" alt="${{file.name}}">
      <small title="${{file.path}}">${{file.name}}</small>
      <button class="danger" onclick="deleteSticker('${{file.path.replaceAll("'","%27")}}')">删除</button>
    </div>`).join('') || '<p class="note">这个分类暂时没有图片。</p>';
}}
async function createCategory() {{
  const name = $('newCategory').value.trim();
  if(!name) return alert('先输入分类名。');
  await api('/api/stickers/category', {{method:'POST', body:JSON.stringify({{name}})}});
  $('newCategory').value = '';
  await loadStickers();
}}
async function uploadSticker() {{
  const file = $('stickerFile').files[0];
  if(!file) return alert('先选择图片。');
  const form = new FormData();
  form.append('category', $('uploadCategory').value || 'default');
  form.append('file', file);
  const res = await fetch('/api/stickers/upload', {{method:'POST', body:form}});
  const data = await res.json();
  if(!res.ok) throw new Error(data.error || '上传失败');
  $('stickerFile').value = '';
  await loadStickers();
}}
async function deleteSticker(path) {{
  if(!confirm('删除后会移动到 _deleted 备份文件夹，确认吗？')) return;
  await api('/api/stickers/delete', {{method:'POST', body:JSON.stringify({{path}})}});
  await loadStickers();
}}
async function loadMemory() {{
  const m = await api('/api/memory');
  $('memoryInfo').textContent = `记忆文件：${{m.path}}，会话数：${{m.conversations}}`;
  $('memoryRows').innerHTML = (m.items||[]).map(x=>`<tr><td class="mono">${{x.id}}</td><td>${{x.type}}</td><td>${{x.messages||0}}</td><td><button class="ghost" onclick="openMemory('${{x.id}}')">打开</button></td></tr>`).join('');
}}
async function openMemory(id) {{
  const d = await api('/api/memory/detail?id=' + encodeURIComponent(id));
  currentMemoryId = id;
  $('memoryTitle').textContent = `详情：${{id}}`;
  $('memoryEditor').value = JSON.stringify(d.content, null, 2);
}}
async function saveMemory() {{
  if(!currentMemoryId) return alert('先打开一个会话记忆。');
  let content;
  try {{ content = JSON.parse($('memoryEditor').value); }} catch(e) {{ return alert('JSON 格式错误：' + e.message); }}
  const r = await api('/api/memory/save', {{method:'POST', body:JSON.stringify({{id:currentMemoryId, content}})}});
  alert('保存完成，备份位置：' + r.backup);
  await loadMemory();
}}
async function deleteMemory() {{
  if(!currentMemoryId) return alert('先打开一个会话记忆。');
  if(!confirm('确认删除这个会话的记忆？删除前会自动备份。')) return;
  const r = await api('/api/memory/delete', {{method:'POST', body:JSON.stringify({{id:currentMemoryId}})}});
  currentMemoryId = ''; $('memoryEditor').value = ''; $('memoryTitle').textContent = '详情';
  alert('已删除，备份位置：' + r.backup);
  await loadMemory();
}}
async function backupMemory() {{
  const r = await api('/api/memory/backup', {{method:'POST', body:'{{}}'}});
  alert('备份完成：' + r.backup);
}}
async function testChat() {{
  $('testOut').textContent='亚托莉生成中。';
  const r = await api('/api/test-chat', {{method:'POST', body:JSON.stringify({{text:$('testText').value}})}});
  $('testOut').textContent = r.reply;
}}
async function restartServices() {{
  const r = await api('/api/restart', {{method:'POST', body:'{{}}'}});
  alert(r.message || r.error || '已执行');
}}
loadStatus(); loadConfig();
</script>
</body>
</html>"""


def render_index() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>亚托莉控制台</title>
  <style>
    :root { --bg:#f5f6f8; --panel:#fff; --ink:#20242c; --muted:#667085; --line:#d8dde8; --blue:#2563eb; --blue-soft:#edf3ff; --green:#16803c; --red:#c02626; --amber:#a15c07; --dark:#111827; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Microsoft YaHei UI","Segoe UI",Arial,sans-serif; background:var(--bg); color:var(--ink); }
    header { background:#fff; border-bottom:1px solid var(--line); padding:18px 24px; position:sticky; top:0; z-index:5; }
    h1 { margin:0 0 6px; font-size:22px; letter-spacing:0; }
    h2 { margin:0 0 14px; font-size:17px; }
    h3 { margin:16px 0 10px; font-size:14px; }
    p { margin:8px 0; }
    main { max-width:1440px; margin:0 auto; padding:18px; display:grid; grid-template-columns:310px 1fr; gap:18px; }
    aside, section, .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .sub,.note,.hint { color:var(--muted); font-size:13px; line-height:1.65; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
    button { border:0; border-radius:6px; background:var(--blue); color:#fff; padding:9px 13px; cursor:pointer; font-weight:700; }
    button.secondary { background:#475467; }
    button.ghost { background:var(--blue-soft); color:#1e3a8a; }
    button.warn { background:var(--amber); }
    button.danger { background:var(--red); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .tab { background:#edf0f5; color:#344054; }
    .tab.active { background:var(--blue); color:#fff; }
    .panel { display:none; }
    .panel.active { display:block; }
    .status { display:grid; gap:10px; }
    .pill { display:flex; justify-content:space-between; gap:10px; align-items:center; padding:10px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; }
    .ok { color:var(--green); font-weight:700; }
    .bad { color:var(--red); font-weight:700; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:12px; }
    .three { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr)); gap:12px; }
    .split { display:grid; grid-template-columns:minmax(360px,.95fr) minmax(420px,1.05fr); gap:14px; }
    label { display:grid; gap:6px; color:#344054; font-size:13px; }
    input, select, textarea { width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; }
    textarea { min-height:150px; resize:vertical; line-height:1.5; }
    .json-editor { min-height:340px; font-family:Consolas,"Microsoft YaHei UI",monospace; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }
    .stack { display:grid; gap:12px; }
    .scroll { max-height:610px; overflow:auto; border:1px solid var(--line); border-radius:7px; background:#fff; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { text-align:left; border-bottom:1px solid var(--line); padding:9px; vertical-align:top; }
    tr:hover { background:#f8fafc; }
    .profile-list { display:grid; gap:10px; }
    .profile { border:1px solid var(--line); border-radius:7px; padding:12px; background:#fff; display:grid; gap:7px; }
    .profile.active { border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.12); }
    .profile-title { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .badge { display:inline-flex; align-items:center; border-radius:999px; padding:2px 8px; font-size:12px; background:#eef2f6; color:#344054; }
    .badge.active { background:#dcfce7; color:#166534; }
    .mono { font-family:Consolas,monospace; }
    .out,.natural-box { white-space:pre-wrap; background:#101828; color:#f2f4f7; border-radius:7px; padding:12px; min-height:90px; line-height:1.55; }
    .natural-box { background:#f8fafc; color:#1f2937; border:1px solid var(--line); }
    .thumbs { display:grid; grid-template-columns:repeat(auto-fill,minmax(112px,1fr)); gap:10px; }
    .thumb { border:1px solid var(--line); border-radius:7px; padding:8px; background:#fff; }
    .thumb img { width:100%; height:92px; object-fit:contain; background:#f2f4f7; border-radius:5px; }
    .thumb small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); margin:6px 0; }
    details { border:1px solid var(--line); border-radius:7px; padding:10px 12px; background:#fff; }
    summary { cursor:pointer; font-weight:700; }
    .toast { position:fixed; right:18px; bottom:18px; max-width:420px; background:#111827; color:#fff; padding:12px 14px; border-radius:7px; box-shadow:0 10px 28px rgba(15,23,42,.25); opacity:0; pointer-events:none; transform:translateY(8px); transition:.18s ease; z-index:10; }
    .toast.show { opacity:1; transform:translateY(0); }
    @media (max-width:980px) { main,.split { grid-template-columns:1fr; } .grid,.three { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>亚托莉控制台</h1>
    <div class="sub">本地 WebUI，只监听 127.0.0.1。你可以在这里切换模型、管理表情包、查看和编辑记忆。</div>
  </header>
  <main>
    <aside>
      <h2>运行状态</h2>
      <div class="status" id="status"></div>
      <div class="row">
        <button class="ghost" onclick="loadStatus()">刷新</button>
        <button class="secondary" onclick="restartServices()">后台重启</button>
      </div>
      <p class="note">API Key 会安全隐藏。看到输入框变空不是丢失，显示“已保存”就代表还在。</p>
    </aside>
    <section>
      <div class="tabs">
        <button class="tab active" onclick="showTab(event,'model')">模型</button>
        <button class="tab" onclick="showTab(event,'stickers')">表情包</button>
        <button class="tab" onclick="showTab(event,'memory')">记忆</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
        <button class="tab" onclick="showTab(event,'advanced')">高级</button>
      </div>

      <div id="model" class="panel active">
        <div class="split">
          <div class="stack">
            <div class="card">
              <h2>当前聊天模型</h2>
              <div id="currentModel" class="natural-box">读取中...</div>
            </div>
            <div class="card">
              <h2>模型档案</h2>
              <p class="note">新建或点选一个档案。启用档案时，会把 API Key、接口地址、模型名和生成参数一起写入配置。</p>
              <div class="profile-list" id="profileList"></div>
            </div>
          </div>
          <div class="card">
            <h2 id="profileFormTitle">新建模型档案</h2>
            <input id="profileId" type="hidden">
            <div class="grid">
              <label>档案名称<input id="profileName" placeholder="例如：DeepSeek 官方"></label>
              <label>服务商<input id="profileProvider" placeholder="例如：DeepSeek / Ollama / OpenAI兼容"></label>
              <label>接口地址<input id="profileBaseUrl" placeholder="https://api.deepseek.com/v1"></label>
              <label>模型名称<input id="profileModel" placeholder="deepseek-chat"></label>
              <label>API Key<input id="profileApiKey" type="password" placeholder="已保存时留空可保持原值"></label>
              <label>温度<input id="profileTemperature" type="number" min="0" max="2" step="0.01" value="0.65"></label>
              <label>重复惩罚<input id="profileFrequencyPenalty" type="number" min="0" max="2" step="0.01" value="0.35"></label>
              <label>最大输出<input id="profileMaxTokens" type="number" min="32" max="4096" step="1" value="260"></label>
            </div>
            <div class="row">
              <button onclick="saveProfile()">保存档案</button>
              <button class="ghost" onclick="activateSelectedProfile()">启用档案</button>
              <button class="secondary" onclick="newProfile()">新建空档案</button>
              <button class="danger" onclick="deleteSelectedProfile()">删除档案</button>
            </div>
            <h3>快速填充</h3>
            <div class="row">
              <button class="ghost" onclick="quickFillDeepSeek()">DeepSeek 官方</button>
              <button class="ghost" onclick="quickFillOllama()">本地 Ollama</button>
              <button class="ghost" onclick="quickFillOpenAICompatible()">OpenAI 兼容</button>
            </div>
          </div>
        </div>
      </div>

      <div id="stickers" class="panel">
        <h2>表情包管理</h2>
        <div class="grid">
          <label>新建情绪分类<input id="newCategory" placeholder="例如 happy / comfort / tsundere / 摸摸头"></label>
          <label>上传到分类<select id="uploadCategory"></select></label>
        </div>
        <div class="row">
          <button onclick="createCategory()">新建分类</button>
          <input id="stickerFile" type="file" accept=".jpg,.jpeg,.png,.gif,.webp,image/*">
          <button onclick="uploadSticker()">上传表情包</button>
        </div>
        <p class="note" id="stickerInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>分类</th><th>数量</th><th>位置</th></tr></thead><tbody id="stickerRows"></tbody></table></div>
          <div>
            <h3 id="stickerFolderTitle">预览</h3>
            <div class="thumbs" id="stickerPreview"></div>
          </div>
        </div>
      </div>

      <div id="memory" class="panel">
        <h2>记忆管理</h2>
        <div class="row">
          <button class="ghost" onclick="loadMemory()">刷新记忆</button>
          <button class="warn" onclick="backupMemory()">手动备份</button>
        </div>
        <p class="note" id="memoryInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>对象</th><th>摘要</th><th>操作</th></tr></thead><tbody id="memoryRows"></tbody></table></div>
          <div class="stack">
            <div>
              <h3 id="memoryTitle">详情</h3>
              <div id="memoryNatural" class="natural-box">打开一条记忆后，这里会显示自然语言摘要。</div>
            </div>
            <details open>
              <summary>高级编辑：原始 JSON</summary>
              <p class="note">修改前会自动备份。只改提示词和记忆文本时建议小步保存，避免 JSON 格式错误。</p>
              <textarea id="memoryEditor" class="json-editor" spellcheck="false"></textarea>
              <div class="row">
                <button onclick="saveMemory()">保存当前记忆</button>
                <button class="danger" onclick="deleteMemory()">删除当前会话记忆</button>
              </div>
            </details>
          </div>
        </div>
      </div>

      <div id="test" class="panel">
        <h2>测试一句话</h2>
        <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
        <div class="row"><button onclick="testChat()">发送测试</button></div>
        <div class="out" id="testOut"></div>
      </div>

      <div id="advanced" class="panel">
        <h2>高级配置</h2>
        <p class="note">这里保留旧式字段编辑。一般只需要用“模型档案”页；高级配置适合调整回复频率、分条发送、表情包概率等数值。</p>
        <div class="grid" id="configForm"></div>
        <div class="row">
          <button onclick="saveConfig()">保存高级配置</button>
          <button class="ghost" onclick="loadConfig()">恢复页面当前值</button>
        </div>
      </div>
    </section>
  </main>
  <div id="toast" class="toast"></div>

<script>
const fields = [
  ["OPENAI_API_KEY","API Key","password"],
  ["OPENAI_BASE_URL","接口地址","text"],
  ["OPENAI_MODEL","聊天模型","text"],
  ["TEMPERATURE","温度","number"],
  ["FREQUENCY_PENALTY","重复惩罚","number"],
  ["MAX_TOKENS","最大输出","number"],
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["IDLE_PROACTIVE_ENABLED","私聊主动关心","checkbox"],
  ["IDLE_MINUTES","私聊空闲分钟","number"],
  ["IDLE_COOLDOWN_MINUTES","主动关心冷却","number"],
  ["GROUP_PROACTIVE_ENABLED","群聊主动发言","checkbox"],
  ["GROUP_PROACTIVE_IDLE_MINUTES","群聊冷场分钟","number"],
  ["GROUP_PROACTIVE_COOLDOWN_MINUTES","群聊主动冷却","number"],
  ["GROUP_PROACTIVE_DAILY_LIMIT","单群日上限","number"],
  ["MORNING_GREETING_ENABLED","早安启用","checkbox"],
  ["MORNING_GREETING_TIME","早安时间","text"],
  ["TOOLBOX_VISION_ENABLED","图片识别","checkbox"],
  ["TOOLBOX_VISION_MODEL","视觉模型","text"],
  ["TOOLBOX_VISION_BASE_URL","视觉接口","text"],
  ["TOOLBOX_VISION_API_KEY","视觉 API Key","password"]
];
let selectedProfileId = "";
let currentMemoryId = "";
window._profiles = [];
window._memoryItems = [];
function $(id) { return document.getElementById(id); }
function toast(text) {
  const el = $('toast'); el.textContent = text; el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'), 2600);
}
async function api(path, opts={}) {
  const headers = opts.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const res = await fetch(path, {headers, ...opts});
  const data = await res.json();
  if(!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function showTab(event, id) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active'); $(id).classList.add('active');
  if(id==='stickers') loadStickers();
  if(id==='memory') loadMemory();
  if(id==='advanced') loadConfig();
  if(id==='model') loadProfiles();
}
async function loadStatus() {
  const s = await api('/api/status');
  $('status').innerHTML = [
    ['Atri 服务', s.atri], ['NapCat 连接', s.napcat], ['Ollama', s.ollama], ['WebUI', s.webui]
  ].map(([k,v])=>`<div class="pill"><span>${k}</span><span class="${v?'ok':'bad'}">${v?'正常':'未连接'}</span></div>`).join('')
  + `<p class="note">机器人 QQ：${escapeHtml(s.bot_qq)}<br>模型：${escapeHtml(s.model)}<br>接口：${escapeHtml(s.base_url)}<br>回复模式：${escapeHtml(s.reply_mode)}</p>`;
}
async function loadProfiles() {
  const data = await api('/api/model-profiles');
  window._profiles = data.profiles || [];
  const c = data.current || {};
  $('currentModel').innerHTML = `服务商：${escapeHtml(c.name)}\n模型：${escapeHtml(c.model)}\n接口：${escapeHtml(c.base_url)}\nAPI Key：${c.has_api_key ? '已保存（' + escapeHtml(c.api_key_masked) + '）' : '未填写'}\n参数：温度 ${escapeHtml(c.temperature)}，重复惩罚 ${escapeHtml(c.frequency_penalty)}，最大输出 ${escapeHtml(c.max_tokens)}`;
  $('profileList').innerHTML = window._profiles.map((p, index) => `
    <div class="profile ${p.id===data.active_id?'active':''}">
      <div class="profile-title">
        <div><strong>${escapeHtml(p.name)}</strong><br><span class="note">${escapeHtml(p.provider)} · ${escapeHtml(p.model)}</span></div>
        <span class="badge ${p.id===data.active_id?'active':''}">${p.id===data.active_id?'当前启用':'可选'}</span>
      </div>
      <div class="note">接口：${escapeHtml(p.base_url)}<br>API Key：${p.has_api_key ? '已保存（' + escapeHtml(p.api_key_masked) + '）' : '未填写'}</div>
      <div class="row">
        <button class="ghost" onclick="selectProfileByIndex(${index})">编辑</button>
        <button onclick="activateProfileByIndex(${index})">启用</button>
      </div>
    </div>`).join('') || '<p class="note">还没有模型档案。</p>';
}
function selectProfileByIndex(index) {
  const p = window._profiles[index];
  if(p) selectProfile(p);
}
function activateProfileByIndex(index) {
  const p = window._profiles[index];
  if(p) activateProfile(p.id);
}
function selectProfile(p) {
  selectedProfileId = p.id || "";
  $('profileFormTitle').textContent = '编辑模型档案';
  $('profileId').value = p.id || "";
  $('profileName').value = p.name || "";
  $('profileProvider').value = p.provider || "";
  $('profileBaseUrl').value = p.base_url || "";
  $('profileModel').value = p.model || "";
  $('profileApiKey').value = "";
  $('profileApiKey').placeholder = p.has_api_key ? '已保存，留空保持原值' : '未填写，请输入 API Key';
  $('profileTemperature').value = p.temperature || "0.65";
  $('profileFrequencyPenalty').value = p.frequency_penalty || "0.35";
  $('profileMaxTokens').value = p.max_tokens || "260";
}
function profilePayload() {
  return {
    id: $('profileId').value.trim(),
    name: $('profileName').value.trim(),
    provider: $('profileProvider').value.trim(),
    base_url: $('profileBaseUrl').value.trim(),
    model: $('profileModel').value.trim(),
    api_key: $('profileApiKey').value.trim(),
    temperature: $('profileTemperature').value.trim(),
    frequency_penalty: $('profileFrequencyPenalty').value.trim(),
    max_tokens: $('profileMaxTokens').value.trim()
  };
}
async function saveProfile() {
  const r = await api('/api/model-profiles/save', {method:'POST', body:JSON.stringify(profilePayload())});
  selectProfile(r.profile);
  await loadProfiles();
  toast('模型档案已保存');
}
async function activateProfile(id) {
  const r = await api('/api/model-profiles/activate', {method:'POST', body:JSON.stringify({id})});
  await loadProfiles(); await loadStatus(); await loadConfig();
  toast(`已启用：${r.profile.name}`);
}
async function activateSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择或保存一个模型档案');
  await activateProfile(id);
}
async function deleteSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择一个模型档案');
  if(!confirm('确认删除这个模型档案？不会删除 .env 里当前正在使用的配置。')) return;
  await api('/api/model-profiles/delete', {method:'POST', body:JSON.stringify({id})});
  newProfile(); await loadProfiles(); toast('模型档案已删除');
}
function newProfile() {
  selectedProfileId = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileId','profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
}
function quickFillDeepSeek() {
  $('profileName').value = $('profileName').value || 'DeepSeek 官方';
  $('profileProvider').value = 'DeepSeek';
  $('profileBaseUrl').value = 'https://api.deepseek.com/v1';
  $('profileModel').value = 'deepseek-chat';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
}
function quickFillOllama() {
  $('profileName').value = $('profileName').value || '本地 Ollama Qwen3 4B';
  $('profileProvider').value = 'Ollama';
  $('profileBaseUrl').value = 'http://127.0.0.1:11434/v1';
  $('profileModel').value = 'qwen3:4b-instruct';
  $('profileApiKey').value = 'ollama';
  $('profileTemperature').value = '0.60';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '180';
}
function quickFillOpenAICompatible() {
  $('profileName').value = $('profileName').value || 'OpenAI 兼容模型';
  $('profileProvider').value = 'OpenAI 兼容';
  $('profileBaseUrl').value = 'https://api.openai.com/v1';
  $('profileModel').value = 'gpt-4.1-mini';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
}
async function loadConfig() {
  const cfg = await api('/api/config');
  $('configForm').innerHTML = fields.map(([key,label,type])=>{
    const item = cfg[key] || {}; const value = item.raw || item.value || '';
    if(type==='select') return `<label>${label}<select id="${key}"><option>private</option><option>mention</option><option>smart</option><option>all</option></select></label>`;
    if(type==='checkbox') return `<label>${label}<input id="${key}" type="checkbox" ${String(value).toLowerCase()==='true'?'checked':''}></label>`;
    if(type==='password') return `<label>${label}<input id="${key}" type="password" placeholder="${item.has_secret ? '已保存，留空保持原值' : '未填写'}"></label>`;
    return `<label>${label}<input id="${key}" type="${type}" step="0.01" value="${escapeHtml(value)}"></label>`;
  }).join('');
  for (const [key,,type] of fields) if(type==='select' && cfg[key]) $(key).value = cfg[key].raw || cfg[key].value;
}
async function saveConfig() {
  const body = {};
  for (const [key,,type] of fields) {
    const el = $(key); if(!el) continue;
    body[key] = type==='checkbox' ? el.checked : el.value;
  }
  await api('/api/config', {method:'POST', body:JSON.stringify(body)});
  await loadConfig(); await loadStatus(); await loadProfiles();
  toast('高级配置已保存');
}
async function loadStickers() {
  const s = await api('/api/stickers');
  $('stickerInfo').textContent = `表情包根目录：${s.path}`;
  const folders = (s.folders||[]).filter(f=>!f.name.startsWith('_deleted'));
  $('uploadCategory').innerHTML = folders.map(f=>`<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)} (${f.count})</option>`).join('');
  $('stickerRows').innerHTML = folders.map((f,i)=>`<tr><td><button class="ghost" onclick="previewFolderByIndex(${i})">${escapeHtml(f.name)}</button></td><td>${f.count}</td><td class="mono">${escapeHtml(f.path)}</td></tr>`).join('');
  window._stickerFolders = folders;
  if (folders.length) previewFolderByIndex(0); else $('stickerPreview').innerHTML = '<p class="note">还没有表情包分类。</p>';
}
function previewFolderByIndex(index) {
  const folder = (window._stickerFolders || [])[index];
  if(!folder) return;
  window._stickerFiles = folder.files || [];
  $('stickerFolderTitle').textContent = `预览：${folder.name}`;
  $('stickerPreview').innerHTML = window._stickerFiles.map((file, fileIndex)=>`
    <div class="thumb">
      <img src="${file.url}" alt="${escapeHtml(file.name)}">
      <small title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</small>
      <button class="danger" onclick="deleteStickerByIndex(${fileIndex})">删除</button>
    </div>`).join('') || '<p class="note">这个分类暂时没有图片。</p>';
}
async function createCategory() {
  const name = $('newCategory').value.trim();
  if(!name) return toast('先输入分类名');
  await api('/api/stickers/category', {method:'POST', body:JSON.stringify({name})});
  $('newCategory').value = ''; await loadStickers(); toast('分类已创建');
}
async function uploadSticker() {
  const file = $('stickerFile').files[0];
  if(!file) return toast('先选择图片');
  const form = new FormData();
  form.append('category', $('uploadCategory').value || 'default');
  form.append('file', file);
  await api('/api/stickers/upload', {method:'POST', body:form});
  $('stickerFile').value = ''; await loadStickers(); toast('表情包已上传');
}
async function deleteStickerByIndex(index) {
  const file = (window._stickerFiles || [])[index];
  if(!file) return toast('没有找到这个文件');
  if(!confirm('删除后会移动到 _deleted 备份文件夹，确认吗？')) return;
  await api('/api/stickers/delete', {method:'POST', body:JSON.stringify({path:file.path})});
  await loadStickers(); toast('已移动到 _deleted');
}
async function loadMemory() {
  const m = await api('/api/memory');
  window._memoryItems = m.items || [];
  $('memoryInfo').textContent = `记忆文件：${m.path}，会话数：${m.conversations}`;
  $('memoryRows').innerHTML = window._memoryItems.map((x, index)=>`
    <tr>
      <td><strong>${escapeHtml(x.display_name || x.id)}</strong><br><span class="note">${escapeHtml(x.type)} · ${escapeHtml(x.id)} · ${x.messages||0} 条</span></td>
      <td>${escapeHtml(x.summary || '暂无摘要')}</td>
      <td><button class="ghost" onclick="openMemoryByIndex(${index})">打开</button></td>
    </tr>`).join('');
}
function openMemoryByIndex(index) {
  const item = (window._memoryItems || [])[index];
  if(item) openMemory(item.id);
}
async function openMemory(id) {
  const d = await api('/api/memory/detail?id=' + encodeURIComponent(id));
  currentMemoryId = id;
  $('memoryTitle').textContent = `详情：${d.display_name || id}`;
  $('memoryNatural').textContent = d.natural || '暂无可读摘要。';
  $('memoryEditor').value = JSON.stringify(d.content, null, 2);
}
async function saveMemory() {
  if(!currentMemoryId) return toast('先打开一条记忆');
  let content;
  try { content = JSON.parse($('memoryEditor').value); } catch(e) { return toast('JSON 格式错误：' + e.message); }
  const r = await api('/api/memory/save', {method:'POST', body:JSON.stringify({id:currentMemoryId, content})});
  await openMemory(currentMemoryId); await loadMemory();
  toast('记忆已保存，已自动备份');
}
async function deleteMemory() {
  if(!currentMemoryId) return toast('先打开一条记忆');
  if(!confirm('确认删除这个会话的记忆？删除前会自动备份。')) return;
  await api('/api/memory/delete', {method:'POST', body:JSON.stringify({id:currentMemoryId})});
  currentMemoryId = ''; $('memoryEditor').value = ''; $('memoryNatural').textContent = '打开一条记忆后，这里会显示自然语言摘要。'; $('memoryTitle').textContent = '详情';
  await loadMemory(); toast('记忆已删除，已自动备份');
}
async function backupMemory() {
  await api('/api/memory/backup', {method:'POST', body:'{}'});
  toast('记忆已备份');
}
async function testChat() {
  $('testOut').textContent='亚托莉生成中...';
  const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:$('testText').value})});
  $('testOut').textContent = r.reply;
}
async function restartServices() {
  const r = await api('/api/restart', {method:'POST', body:'{}'});
  toast(r.message || r.error || '已执行');
}
loadStatus(); loadProfiles(); loadConfig();
</script>
</body>
</html>"""


def render_index() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>亚托莉控制台</title>
  <style>
    :root {
      --bg:#f5f6f8; --panel:#fff; --ink:#20242c; --muted:#667085; --line:#d8dde8;
      --blue:#2563eb; --blue-soft:#edf3ff; --green:#16803c; --red:#c02626;
      --amber:#a15c07; --soft:#f8fafc; --dark:#111827;
    }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Microsoft YaHei UI","Segoe UI",Arial,sans-serif; background:var(--bg); color:var(--ink); }
    header { background:#fff; border-bottom:1px solid var(--line); padding:18px 24px; position:sticky; top:0; z-index:8; }
    h1 { margin:0 0 6px; font-size:22px; letter-spacing:0; }
    h2 { margin:0 0 14px; font-size:17px; }
    h3 { margin:16px 0 10px; font-size:14px; }
    p { margin:8px 0; }
    main { max-width:1480px; margin:0 auto; padding:18px; display:grid; grid-template-columns:310px 1fr; gap:18px; }
    aside, section, .surface { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .sub,.note,.hint { color:var(--muted); font-size:13px; line-height:1.65; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
    button { border:0; border-radius:6px; background:var(--blue); color:#fff; padding:9px 13px; cursor:pointer; font-weight:700; }
    button.secondary { background:#475467; }
    button.ghost { background:var(--blue-soft); color:#1e3a8a; }
    button.warn { background:var(--amber); }
    button.danger { background:var(--red); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .tab { background:#edf0f5; color:#344054; }
    .tab.active { background:var(--blue); color:#fff; }
    .panel { display:none; }
    .panel.active { display:block; }
    .status { display:grid; gap:10px; }
    .pill { display:flex; justify-content:space-between; gap:10px; align-items:center; padding:10px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; }
    .ok { color:var(--green); font-weight:700; }
    .bad { color:var(--red); font-weight:700; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:12px; }
    .three { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr)); gap:12px; }
    .split { display:grid; grid-template-columns:minmax(360px,.95fr) minmax(420px,1.05fr); gap:14px; }
    label { display:grid; gap:6px; color:#344054; font-size:13px; }
    input, select, textarea { width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; }
    textarea { min-height:130px; resize:vertical; line-height:1.5; }
    .json-editor { min-height:340px; font-family:Consolas,"Microsoft YaHei UI",monospace; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }
    .stack { display:grid; gap:12px; }
    .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:end; margin:10px 0 14px; }
    .toolbar label { min-width:170px; flex:1; }
    .scroll { max-height:640px; overflow:auto; border:1px solid var(--line); border-radius:7px; background:#fff; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { text-align:left; border-bottom:1px solid var(--line); padding:9px; vertical-align:top; }
    tr:hover { background:#f8fafc; }
    .profile-list { display:grid; gap:10px; }
    .profile { border:1px solid var(--line); border-radius:7px; padding:12px; background:#fff; display:grid; gap:7px; }
    .profile.active { border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.12); }
    .profile-title { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .badge { display:inline-flex; align-items:center; border-radius:999px; padding:2px 8px; font-size:12px; background:#eef2f6; color:#344054; white-space:nowrap; }
    .badge.active { background:#dcfce7; color:#166534; }
    .badge.warn { background:#fef3c7; color:#92400e; }
    .badge.red { background:#fee2e2; color:#991b1b; }
    .mono { font-family:Consolas,monospace; }
    .out,.natural-box { white-space:pre-wrap; background:#101828; color:#f2f4f7; border-radius:7px; padding:12px; min-height:90px; line-height:1.55; }
    .natural-box { background:#f8fafc; color:#1f2937; border:1px solid var(--line); }
    .thumbs { display:grid; grid-template-columns:repeat(auto-fill,minmax(112px,1fr)); gap:10px; }
    .thumb { border:1px solid var(--line); border-radius:7px; padding:8px; background:#fff; }
    .thumb img { width:100%; height:92px; object-fit:contain; background:#f2f4f7; border-radius:5px; }
    .thumb small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); margin:6px 0; }
    details { border:1px solid var(--line); border-radius:7px; padding:10px 12px; background:#fff; }
    summary { cursor:pointer; font-weight:700; }
    .toast { position:fixed; right:18px; bottom:18px; max-width:420px; background:#111827; color:#fff; padding:12px 14px; border-radius:7px; box-shadow:0 10px 28px rgba(15,23,42,.25); opacity:0; pointer-events:none; transform:translateY(8px); transition:.18s ease; z-index:30; }
    .toast.show { opacity:1; transform:translateY(0); }
    .memory-name { font-weight:700; margin-bottom:4px; }
    .memory-meta { color:var(--muted); font-size:12px; line-height:1.55; }
    .memory-summary { line-height:1.6; max-width:620px; }
    .empty { color:var(--muted); padding:22px; text-align:center; }
    .modal { position:fixed; inset:0; display:none; align-items:center; justify-content:center; background:rgba(15,23,42,.46); padding:22px; z-index:20; }
    .modal.show { display:flex; }
    .dialog { width:min(1180px,96vw); max-height:92vh; overflow:hidden; background:#fff; border-radius:8px; border:1px solid var(--line); box-shadow:0 24px 70px rgba(15,23,42,.32); display:grid; grid-template-rows:auto auto 1fr auto; }
    .dialog-head { padding:16px 18px; border-bottom:1px solid var(--line); display:flex; gap:12px; justify-content:space-between; align-items:flex-start; }
    .dialog-title { font-size:18px; font-weight:800; }
    .dialog-body { overflow:auto; padding:16px 18px; background:#fbfcfe; }
    .dialog-foot { padding:12px 18px; border-top:1px solid var(--line); background:#fff; display:flex; justify-content:space-between; gap:12px; align-items:center; }
    .mini-tabs { display:flex; gap:8px; flex-wrap:wrap; padding:10px 18px; border-bottom:1px solid var(--line); background:#fff; }
    .mini-tab { background:#eef2f6; color:#344054; }
    .mini-tab.active { background:var(--blue); color:#fff; }
    .stat-grid { display:grid; grid-template-columns:repeat(4,minmax(130px,1fr)); gap:10px; margin:12px 0; }
    .stat { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px; }
    .stat strong { display:block; font-size:18px; margin-bottom:2px; }
    .entry-list { display:grid; gap:10px; }
    .entry { border:1px solid var(--line); border-radius:7px; background:#fff; padding:12px; display:grid; gap:10px; }
    .entry-head { display:flex; justify-content:space-between; gap:10px; align-items:center; }
    .entry-grid { display:grid; grid-template-columns:180px 1fr 130px 130px; gap:10px; }
    .history-item { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px; display:grid; gap:8px; margin-bottom:8px; }
    .dirty { color:var(--amber); font-weight:700; }
    .saved { color:var(--green); font-weight:700; }
    @media (max-width:980px) {
      main,.split { grid-template-columns:1fr; }
      .grid,.three,.stat-grid,.entry-grid { grid-template-columns:1fr; }
      .dialog { width:98vw; }
    }
  </style>
</head>
<body>
  <header>
    <h1>亚托莉控制台</h1>
    <div class="sub">本地 WebUI，只监听 127.0.0.1。这里可以切换模型、管理表情包、查看和编辑记忆。</div>
  </header>
  <main>
    <aside>
      <h2>运行状态</h2>
      <div class="status" id="status"></div>
      <div class="row">
        <button class="ghost" onclick="loadStatus()">刷新</button>
        <button class="secondary" onclick="restartServices()">后台重启</button>
      </div>
      <p class="note">API Key 会隐藏显示。输入框变空不是丢失，显示“已保存”就代表仍在配置里。</p>
    </aside>
    <section>
      <div class="tabs">
        <button class="tab active" onclick="showTab(event,'model')">模型</button>
        <button class="tab" onclick="showTab(event,'stickers')">表情包</button>
        <button class="tab" onclick="showTab(event,'memory')">记忆</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
        <button class="tab" onclick="showTab(event,'advanced')">高级</button>
      </div>

      <div id="model" class="panel active">
        <div class="split">
          <div class="stack">
            <div class="surface">
              <h2>当前聊天模型</h2>
              <div id="currentModel" class="natural-box">读取中...</div>
            </div>
            <div class="surface">
              <h2>模型档案</h2>
              <p class="note">新建或点选一个档案。启用档案时，会把 API Key、接口地址、模型名和生成参数一起写入配置。</p>
              <div class="profile-list" id="profileList"></div>
            </div>
          </div>
          <div class="surface">
            <h2 id="profileFormTitle">新建模型档案</h2>
            <input id="profileId" type="hidden">
            <div class="grid">
              <label>档案名称<input id="profileName" placeholder="例如：DeepSeek 官方"></label>
              <label>服务商<input id="profileProvider" placeholder="例如：DeepSeek / Ollama / OpenAI兼容"></label>
              <label>接口地址<input id="profileBaseUrl" placeholder="https://api.deepseek.com/v1"></label>
              <label>模型名称<input id="profileModel" placeholder="deepseek-chat"></label>
              <label>API Key<input id="profileApiKey" type="password" placeholder="已保存时留空可保持原值"></label>
              <label>温度<input id="profileTemperature" type="number" min="0" max="2" step="0.01" value="0.65"></label>
              <label>重复惩罚<input id="profileFrequencyPenalty" type="number" min="0" max="2" step="0.01" value="0.35"></label>
              <label>最大输出<input id="profileMaxTokens" type="number" min="32" max="4096" step="1" value="260"></label>
            </div>
            <div class="row">
              <button onclick="saveProfile()">保存档案</button>
              <button class="ghost" onclick="activateSelectedProfile()">启用档案</button>
              <button class="secondary" onclick="newProfile()">新建空档案</button>
              <button class="danger" onclick="deleteSelectedProfile()">删除档案</button>
            </div>
            <h3>快速填入</h3>
            <div class="row">
              <button class="ghost" onclick="quickFillDeepSeek()">DeepSeek 官方</button>
              <button class="ghost" onclick="quickFillOllama()">本地 Ollama</button>
              <button class="ghost" onclick="quickFillOpenAICompatible()">OpenAI 兼容</button>
            </div>
          </div>
        </div>
      </div>

      <div id="stickers" class="panel">
        <h2>表情包管理</h2>
        <div class="grid">
          <label>新建情绪分类<input id="newCategory" placeholder="例如 happy / comfort / tsundere / 摸摸头"></label>
          <label>上传到分类<select id="uploadCategory"></select></label>
        </div>
        <div class="row">
          <button onclick="createCategory()">新建分类</button>
          <input id="stickerFile" type="file" accept=".jpg,.jpeg,.png,.gif,.webp,image/*">
          <button onclick="uploadSticker()">上传表情包</button>
        </div>
        <p class="note" id="stickerInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>分类</th><th>数量</th><th>位置</th></tr></thead><tbody id="stickerRows"></tbody></table></div>
          <div>
            <h3 id="stickerFolderTitle">预览</h3>
            <div class="thumbs" id="stickerPreview"></div>
          </div>
        </div>
      </div>

      <div id="memory" class="panel">
        <h2>记忆管理</h2>
        <div class="toolbar">
          <label>搜索用户 / QQ / 群 / 关键词<input id="memorySearch" oninput="renderMemoryRows()" placeholder="输入昵称、QQ号、群号或记忆关键词"></label>
          <label>类型筛选<select id="memoryTypeFilter" onchange="renderMemoryRows()">
            <option value="all">全部</option>
            <option value="private">私聊</option>
            <option value="group">群聊</option>
            <option value="member">群内用户</option>
            <option value="important">有重要记忆</option>
          </select></label>
          <label>排序<select id="memorySort" onchange="renderMemoryRows()">
            <option value="recent">最近互动</option>
            <option value="messages">消息数量</option>
            <option value="memories">记忆数量</option>
            <option value="affection">亲密状态</option>
          </select></label>
        </div>
        <div class="row">
          <button class="ghost" onclick="loadMemory()">刷新记忆</button>
          <button class="warn" onclick="backupMemory()">手动备份</button>
        </div>
        <p class="note" id="memoryInfo"></p>
        <div class="scroll">
          <table>
            <thead><tr><th>对象</th><th>核心记忆</th><th>状态</th><th>操作</th></tr></thead>
            <tbody id="memoryRows"></tbody>
          </table>
        </div>
      </div>

      <div id="test" class="panel">
        <h2>测试一句话</h2>
        <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
        <div class="row"><button onclick="testChat()">发送测试</button></div>
        <div class="out" id="testOut"></div>
      </div>

      <div id="advanced" class="panel">
        <h2>高级配置</h2>
        <p class="note">这里适合调整回复频率、分条发送、表情包概率和群聊主动发言规则。群聊沉默天数设为 0 表示不按天数停用主动发言。</p>
        <div class="grid" id="configForm"></div>
        <div class="row">
          <button onclick="saveConfig()">保存高级配置</button>
          <button class="ghost" onclick="loadConfig()">恢复页面当前值</button>
        </div>
      </div>
    </section>
  </main>

  <div id="memoryModal" class="modal" onclick="modalBackdrop(event)">
    <div class="dialog">
      <div class="dialog-head">
        <div>
          <div class="dialog-title" id="memoryModalTitle">记忆详情</div>
          <div class="note" id="memoryModalMeta"></div>
        </div>
        <button class="secondary" onclick="closeMemoryModal()">关闭</button>
      </div>
      <div class="mini-tabs">
        <button class="mini-tab active" onclick="showMemoryPane(event,'memoryOverview')">概览</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryProfile')">用户档案</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryEvents')">事件</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryStyle')">习惯</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryHistory')">最近聊天</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryRaw')">高级 JSON</button>
      </div>
      <div class="dialog-body">
        <div id="memoryOverview" class="memory-pane"></div>
        <div id="memoryProfile" class="memory-pane" style="display:none"></div>
        <div id="memoryEvents" class="memory-pane" style="display:none"></div>
        <div id="memoryStyle" class="memory-pane" style="display:none"></div>
        <div id="memoryHistory" class="memory-pane" style="display:none"></div>
        <div id="memoryRaw" class="memory-pane" style="display:none"></div>
      </div>
      <div class="dialog-foot">
        <span id="memorySaveState" class="saved">未修改</span>
        <div class="row" style="margin:0">
          <button class="ghost" onclick="addMemoryEntryFromActivePane()">新增当前分类</button>
          <button id="memorySaveButton" onclick="saveSelectedMemory()">保存修改</button>
          <button class="danger" onclick="deleteSelectedMemory()">删除此会话记忆</button>
        </div>
      </div>
    </div>
  </div>
  <div id="toast" class="toast"></div>

<script>
const fields = [
  ["OPENAI_API_KEY","API Key","password"],
  ["OPENAI_BASE_URL","接口地址","text"],
  ["OPENAI_MODEL","聊天模型","text"],
  ["TEMPERATURE","温度","number"],
  ["FREQUENCY_PENALTY","重复惩罚","number"],
  ["MAX_TOKENS","最大输出","number"],
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["IDLE_PROACTIVE_ENABLED","私聊主动关心","checkbox"],
  ["IDLE_MINUTES","私聊空闲分钟","number"],
  ["IDLE_COOLDOWN_MINUTES","主动关心冷却","number"],
  ["GROUP_PROACTIVE_ENABLED","群聊主动发言","checkbox"],
  ["GROUP_PROACTIVE_IDLE_MINUTES","群聊冷场分钟","number"],
  ["GROUP_PROACTIVE_COOLDOWN_MINUTES","群聊主动冷却","number"],
  ["GROUP_PROACTIVE_DAILY_LIMIT","单群日上限","number"],
  ["GROUP_PROACTIVE_MAX_SILENCE_DAYS","群聊沉默停用天数","number"],
  ["MORNING_GREETING_ENABLED","早安启用","checkbox"],
  ["MORNING_GREETING_TIME","早安时间","text"],
  ["TOOLBOX_VISION_ENABLED","图片识别","checkbox"],
  ["TOOLBOX_VISION_MODEL","视觉模型","text"],
  ["TOOLBOX_VISION_BASE_URL","视觉接口","text"],
  ["TOOLBOX_VISION_API_KEY","视觉 API Key","password"]
];
const categoryLabels = {
  interest:"兴趣爱好", profile_fact:"用户资料", communication_style:"聊天习惯",
  schedule:"日程提醒", event:"事件经历", important_interaction:"重要互动"
};
let selectedProfileId = "";
let currentMemoryId = "";
let selectedMemory = null;
let selectedMemoryContent = null;
let memoryDirty = false;
let activeMemoryPane = "memoryOverview";
window._profiles = [];
window._memoryItems = [];
function $(id) { return document.getElementById(id); }
function toast(text) {
  const el = $('toast'); el.textContent = text; el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'), 2600);
}
async function api(path, opts={}) {
  const headers = opts.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const res = await fetch(path, {headers, ...opts});
  const data = await res.json();
  if(!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function showTab(event, id) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active'); $(id).classList.add('active');
  if(id==='stickers') loadStickers();
  if(id==='memory') loadMemory();
  if(id==='advanced') loadConfig();
  if(id==='model') loadProfiles();
}
async function loadStatus() {
  const s = await api('/api/status');
  $('status').innerHTML = [
    ['Atri 服务', s.atri], ['NapCat 连接', s.napcat], ['Ollama', s.ollama], ['WebUI', s.webui]
  ].map(([k,v])=>`<div class="pill"><span>${k}</span><span class="${v?'ok':'bad'}">${v?'正常':'未连接'}</span></div>`).join('')
  + `<p class="note">机器人 QQ：${escapeHtml(s.bot_qq)}<br>模型：${escapeHtml(s.model)}<br>接口：${escapeHtml(s.base_url)}<br>回复模式：${escapeHtml(s.reply_mode)}</p>`;
}
async function loadProfiles() {
  const data = await api('/api/model-profiles');
  window._profiles = data.profiles || [];
  const c = data.current || {};
  $('currentModel').innerHTML = `服务商：${escapeHtml(c.name)}\n模型：${escapeHtml(c.model)}\n接口：${escapeHtml(c.base_url)}\nAPI Key：${c.has_api_key ? '已保存（' + escapeHtml(c.api_key_masked) + '）' : '未填写'}\n参数：温度 ${escapeHtml(c.temperature)}，重复惩罚 ${escapeHtml(c.frequency_penalty)}，最大输出 ${escapeHtml(c.max_tokens)}`;
  $('profileList').innerHTML = window._profiles.map((p, index) => `
    <div class="profile ${p.id===data.active_id?'active':''}">
      <div class="profile-title">
        <div><strong>${escapeHtml(p.name)}</strong><br><span class="note">${escapeHtml(p.provider)} · ${escapeHtml(p.model)}</span></div>
        <span class="badge ${p.id===data.active_id?'active':''}">${p.id===data.active_id?'当前启用':'可选择'}</span>
      </div>
      <div class="note">接口：${escapeHtml(p.base_url)}<br>API Key：${p.has_api_key ? '已保存（' + escapeHtml(p.api_key_masked) + '）' : '未填写'}</div>
      <div class="row">
        <button class="ghost" onclick="selectProfileByIndex(${index})">编辑</button>
        <button onclick="activateProfileByIndex(${index})">启用</button>
      </div>
    </div>`).join('') || '<p class="note">还没有模型档案。</p>';
}
function selectProfileByIndex(index) { const p = window._profiles[index]; if(p) selectProfile(p); }
function activateProfileByIndex(index) { const p = window._profiles[index]; if(p) activateProfile(p.id); }
function selectProfile(p) {
  selectedProfileId = p.id || "";
  $('profileFormTitle').textContent = '编辑模型档案';
  $('profileId').value = p.id || "";
  $('profileName').value = p.name || "";
  $('profileProvider').value = p.provider || "";
  $('profileBaseUrl').value = p.base_url || "";
  $('profileModel').value = p.model || "";
  $('profileApiKey').value = "";
  $('profileApiKey').placeholder = p.has_api_key ? '已保存，留空保持原值' : '未填写，请输入 API Key';
  $('profileTemperature').value = p.temperature || "0.65";
  $('profileFrequencyPenalty').value = p.frequency_penalty || "0.35";
  $('profileMaxTokens').value = p.max_tokens || "260";
}
function profilePayload() {
  return {
    id: $('profileId').value.trim(),
    name: $('profileName').value.trim(),
    provider: $('profileProvider').value.trim(),
    base_url: $('profileBaseUrl').value.trim(),
    model: $('profileModel').value.trim(),
    api_key: $('profileApiKey').value.trim(),
    temperature: $('profileTemperature').value.trim(),
    frequency_penalty: $('profileFrequencyPenalty').value.trim(),
    max_tokens: $('profileMaxTokens').value.trim()
  };
}
async function saveProfile() {
  const r = await api('/api/model-profiles/save', {method:'POST', body:JSON.stringify(profilePayload())});
  selectProfile(r.profile);
  await loadProfiles();
  toast('模型档案已保存');
}
async function activateProfile(id) {
  const r = await api('/api/model-profiles/activate', {method:'POST', body:JSON.stringify({id})});
  await loadProfiles(); await loadStatus(); await loadConfig();
  toast(`已启用：${r.profile.name}`);
}
async function activateSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择或保存一个模型档案');
  await activateProfile(id);
}
async function deleteSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择一个模型档案');
  if(!confirm('确认删除这个模型档案？不会删除 .env 里当前正在使用的配置。')) return;
  await api('/api/model-profiles/delete', {method:'POST', body:JSON.stringify({id})});
  newProfile(); await loadProfiles(); toast('模型档案已删除');
}
function newProfile() {
  selectedProfileId = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileId','profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
}
function quickFillDeepSeek() {
  $('profileName').value = $('profileName').value || 'DeepSeek 官方';
  $('profileProvider').value = 'DeepSeek';
  $('profileBaseUrl').value = 'https://api.deepseek.com/v1';
  $('profileModel').value = 'deepseek-chat';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
}
function quickFillOllama() {
  $('profileName').value = $('profileName').value || '本地 Ollama Qwen3 4B';
  $('profileProvider').value = 'Ollama';
  $('profileBaseUrl').value = 'http://127.0.0.1:11434/v1';
  $('profileModel').value = 'qwen3:4b-instruct';
  $('profileApiKey').value = 'ollama';
  $('profileTemperature').value = '0.60';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '180';
}
function quickFillOpenAICompatible() {
  $('profileName').value = $('profileName').value || 'OpenAI 兼容模型';
  $('profileProvider').value = 'OpenAI 兼容';
  $('profileBaseUrl').value = 'https://api.openai.com/v1';
  $('profileModel').value = 'gpt-4.1-mini';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
}
async function loadConfig() {
  const cfg = await api('/api/config');
  $('configForm').innerHTML = fields.map(([key,label,type])=>{
    const item = cfg[key] || {}; const value = item.raw || item.value || '';
    if(type==='select') return `<label>${label}<select id="${key}"><option>private</option><option>mention</option><option>smart</option><option>all</option></select></label>`;
    if(type==='checkbox') return `<label>${label}<input id="${key}" type="checkbox" ${String(value).toLowerCase()==='true'?'checked':''}></label>`;
    if(type==='password') return `<label>${label}<input id="${key}" type="password" placeholder="${item.has_secret ? '已保存，留空保持原值' : '未填写'}"></label>`;
    return `<label>${label}<input id="${key}" type="${type}" step="0.01" value="${escapeHtml(value)}"></label>`;
  }).join('');
  for (const [key,,type] of fields) if(type==='select' && cfg[key]) $(key).value = cfg[key].raw || cfg[key].value;
}
async function saveConfig() {
  const body = {};
  for (const [key,,type] of fields) {
    const el = $(key); if(!el) continue;
    body[key] = type==='checkbox' ? el.checked : el.value;
  }
  await api('/api/config', {method:'POST', body:JSON.stringify(body)});
  await loadConfig(); await loadStatus(); await loadProfiles();
  toast('高级配置已保存，新的 QQ 消息会使用新配置');
}
async function loadStickers() {
  const s = await api('/api/stickers');
  $('stickerInfo').textContent = `表情包根目录：${s.path}`;
  const folders = (s.folders||[]).filter(f=>!f.name.startsWith('_deleted'));
  $('uploadCategory').innerHTML = folders.map(f=>`<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)} (${f.count})</option>`).join('');
  $('stickerRows').innerHTML = folders.map((f,i)=>`<tr><td><button class="ghost" onclick="previewFolderByIndex(${i})">${escapeHtml(f.name)}</button></td><td>${f.count}</td><td class="mono">${escapeHtml(f.path)}</td></tr>`).join('');
  window._stickerFolders = folders;
  if (folders.length) previewFolderByIndex(0); else $('stickerPreview').innerHTML = '<p class="note">还没有表情包分类。</p>';
}
function previewFolderByIndex(index) {
  const folder = (window._stickerFolders || [])[index];
  if(!folder) return;
  window._stickerFiles = folder.files || [];
  $('stickerFolderTitle').textContent = `预览：${folder.name}`;
  $('stickerPreview').innerHTML = window._stickerFiles.map((file, fileIndex)=>`
    <div class="thumb">
      <img src="${file.url}" alt="${escapeHtml(file.name)}">
      <small title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</small>
      <button class="danger" onclick="deleteStickerByIndex(${fileIndex})">删除</button>
    </div>`).join('') || '<p class="note">这个分类暂时没有图片。</p>';
}
async function createCategory() {
  const name = $('newCategory').value.trim();
  if(!name) return toast('先输入分类名');
  await api('/api/stickers/category', {method:'POST', body:JSON.stringify({name})});
  $('newCategory').value = ''; await loadStickers(); toast('分类已创建');
}
async function uploadSticker() {
  const file = $('stickerFile').files[0];
  if(!file) return toast('先选择图片');
  const form = new FormData();
  form.append('category', $('uploadCategory').value || 'default');
  form.append('file', file);
  await api('/api/stickers/upload', {method:'POST', body:form});
  $('stickerFile').value = ''; await loadStickers(); toast('表情包已上传');
}
async function deleteStickerByIndex(index) {
  const file = (window._stickerFiles || [])[index];
  if(!file) return toast('没有找到这个文件');
  if(!confirm('删除后会移动到 _deleted 备份文件夹，确认吗？')) return;
  await api('/api/stickers/delete', {method:'POST', body:JSON.stringify({path:file.path})});
  await loadStickers(); toast('已移动到 _deleted');
}

async function loadMemory() {
  const m = await api('/api/memory');
  window._memoryItems = m.items || [];
  $('memoryInfo').textContent = `记忆文件：${m.path}，会话数：${m.conversations}`;
  renderMemoryRows();
}
function memoryMatchesFilter(item) {
  const filter = $('memoryTypeFilter')?.value || 'all';
  if(filter === 'private' && item.kind !== 'private') return false;
  if(filter === 'group' && item.kind !== 'group') return false;
  if(filter === 'member' && item.kind !== 'member') return false;
  if(filter === 'important' && !(item.memory_counts && item.memory_counts.total > 0)) return false;
  const q = ($('memorySearch')?.value || '').trim().toLowerCase();
  if(!q) return true;
  return String(item.searchable || '').toLowerCase().includes(q);
}
function renderMemoryRows() {
  const sort = $('memorySort')?.value || 'recent';
  const rows = (window._memoryItems || []).filter(memoryMatchesFilter).sort((a,b)=>{
    if(sort === 'messages') return (b.messages||0) - (a.messages||0);
    if(sort === 'memories') return ((b.memory_counts||{}).total||0) - ((a.memory_counts||{}).total||0);
    if(sort === 'affection') return Number(b.affection||0) - Number(a.affection||0);
    return Number(b.last_user_at||0) - Number(a.last_user_at||0);
  });
  $('memoryRows').innerHTML = rows.map((x)=>`
    <tr>
      <td>
        <div class="memory-name">${escapeHtml(x.display_name || x.id)}</div>
        <div class="memory-meta">${escapeHtml(x.type)} · ${escapeHtml(x.id)}<br>${escapeHtml(x.last_user_at_text || '暂无互动时间')}</div>
      </td>
      <td class="memory-summary">${escapeHtml(x.summary || '暂无可读摘要')}</td>
      <td>
        <span class="badge">${escapeHtml(x.affection_label || '普通')}</span>
        ${x.proactive_state ? `<br><span class="badge ${x.proactive_blocked?'red':'active'}" style="margin-top:6px">${escapeHtml(x.proactive_state)}</span>` : ''}
        <div class="memory-meta" style="margin-top:6px">消息 ${x.messages||0} · 记忆 ${(x.memory_counts||{}).total||0}</div>
      </td>
      <td><button class="ghost" onclick="openMemory('${escapeHtml(x.id)}')">详情 / 编辑</button></td>
    </tr>`).join('') || '<tr><td colspan="4"><div class="empty">没有匹配的记忆。</div></td></tr>';
}
async function openMemory(id) {
  if(memoryDirty && !confirm('当前记忆有未保存修改，确定切换吗？')) return;
  const d = await api('/api/memory/detail?id=' + encodeURIComponent(id));
  currentMemoryId = id;
  selectedMemory = d;
  selectedMemoryContent = JSON.parse(JSON.stringify(d.content || {}));
  memoryDirty = false;
  $('memoryModalTitle').textContent = d.display_name || id;
  $('memoryModalMeta').textContent = `${d.type || ''} · ${id}`;
  $('memoryModal').classList.add('show');
  setSaveState('未修改', false);
  renderMemoryModal();
}
function closeMemoryModal() {
  if(memoryDirty && !confirm('还有未保存修改，确定关闭吗？')) return;
  $('memoryModal').classList.remove('show');
}
function modalBackdrop(event) {
  if(event.target.id === 'memoryModal') closeMemoryModal();
}
function showMemoryPane(event, id) {
  activeMemoryPane = id;
  document.querySelectorAll('.mini-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.memory-pane').forEach(p=>p.style.display='none');
  event.target.classList.add('active'); $(id).style.display = 'block';
}
function setSaveState(text, dirty) {
  memoryDirty = dirty;
  const el = $('memorySaveState');
  el.textContent = text;
  el.className = dirty ? 'dirty' : 'saved';
}
function markMemoryDirty() {
  setSaveState('有未保存修改', true);
}
function structuredMemory() {
  selectedMemoryContent.structured_memory = selectedMemoryContent.structured_memory || {};
  for (const key of ['l1','l2','candidates']) {
    if(!Array.isArray(selectedMemoryContent.structured_memory[key])) selectedMemoryContent.structured_memory[key] = [];
  }
  return selectedMemoryContent.structured_memory;
}
function memoryEntryLayerForPane() {
  if(activeMemoryPane === 'memoryEvents') return 'l2';
  if(activeMemoryPane === 'memoryProfile' || activeMemoryPane === 'memoryStyle') return 'l1';
  return 'l1';
}
function renderMemoryModal() {
  if(!selectedMemory || !selectedMemoryContent) return;
  const counts = selectedMemory.memory_counts || {};
  $('memoryOverview').innerHTML = `
    <div class="natural-box">${escapeHtml(selectedMemory.natural || '暂无可读摘要。')}</div>
    <div class="stat-grid">
      <div class="stat"><strong>${selectedMemoryContent.message_count || 0}</strong><span class="note">消息数量</span></div>
      <div class="stat"><strong>${counts.total || 0}</strong><span class="note">结构化记忆</span></div>
      <div class="stat"><strong>${selectedMemory.history_count || 0}</strong><span class="note">历史条数</span></div>
      <div class="stat"><strong>${escapeHtml(selectedMemory.affection_label || '普通')}</strong><span class="note">亲密状态</span></div>
    </div>
    <p class="note">编辑下面的档案、事件、习惯或最近聊天后，点击底部“保存修改”。保存前会自动备份。</p>`;
  $('memoryProfile').innerHTML = renderEntryEditor('l1', ['profile_fact','interest'], '用户档案与兴趣');
  $('memoryEvents').innerHTML = renderEntryEditor('l2', ['event','schedule','important_interaction'], '事件、日程与重要互动');
  $('memoryStyle').innerHTML = renderEntryEditor('l1', ['communication_style'], '聊天习惯') + renderRulesEditor();
  $('memoryHistory').innerHTML = renderHistoryEditor();
  $('memoryRaw').innerHTML = `<p class="note">高级模式会直接保存整个会话 JSON。改错 JSON 会被拦截，不会写入。</p><textarea id="memoryRawEditor" class="json-editor" spellcheck="false">${escapeHtml(JSON.stringify(selectedMemoryContent, null, 2))}</textarea><div class="row"><button class="ghost" onclick="applyRawMemory()">应用 JSON 到编辑器</button></div>`;
}
function renderEntryEditor(layer, categories, title) {
  const memory = structuredMemory();
  const entries = (memory[layer] || []).map((entry, index)=>({entry,index})).filter(({entry})=>categories.includes(entry.category || ''));
  return `<h3>${title}</h3><div class="entry-list">${entries.map(({entry,index})=>renderEntry(layer,index,entry)).join('') || '<div class="empty">暂无内容，可以点击底部“新增当前分类”。</div>'}</div>`;
}
function renderEntry(layer, index, entry) {
  const category = entry.category || '';
  const options = Object.entries(categoryLabels).map(([key,label])=>`<option value="${key}" ${key===category?'selected':''}>${label}</option>`).join('');
  return `<div class="entry">
    <div class="entry-head">
      <strong>${escapeHtml(categoryLabels[category] || category || '未分类')}</strong>
      <button class="danger" onclick="removeMemoryEntry('${layer}',${index})">删除</button>
    </div>
    <div class="entry-grid">
      <label>分类<select onchange="updateMemoryEntry('${layer}',${index},'category',this.value)">${options}</select></label>
      <label>标题 / 键<input value="${escapeHtml(entry.key || entry.memory_key || '')}" oninput="updateMemoryEntry('${layer}',${index},'key',this.value)"></label>
      <label>置信度<input type="number" min="0" max="1" step="0.05" value="${escapeHtml(entry.confidence ?? '')}" oninput="updateMemoryEntry('${layer}',${index},'confidence',this.value,true)"></label>
      <label>状态<select onchange="updateMemoryEntry('${layer}',${index},'state',this.value)">
        <option value="active" ${entry.state !== 'sleeping'?'selected':''}>启用</option>
        <option value="sleeping" ${entry.state === 'sleeping'?'selected':''}>休眠</option>
      </select></label>
    </div>
    <label>内容<textarea oninput="updateMemoryEntry('${layer}',${index},'value',this.value)">${escapeHtml(entry.value || '')}</textarea></label>
  </div>`;
}
function renderRulesEditor() {
  const accepted = selectedMemoryContent.accepted_iteration_rules || [];
  const rejected = selectedMemoryContent.rejected_iteration_rules || [];
  const block = (items, key, label) => `<h3>${label}</h3><div class="entry-list">${items.map((rule,index)=>`
    <div class="entry">
      <div class="entry-head"><strong>${label} ${index+1}</strong><button class="danger" onclick="removeRule('${key}',${index})">删除</button></div>
      <label>规则<textarea oninput="updateRule('${key}',${index},'rule',this.value)">${escapeHtml(rule.rule || '')}</textarea></label>
      <label>原因<input value="${escapeHtml(rule.reason || '')}" oninput="updateRule('${key}',${index},'reason',this.value)"></label>
    </div>`).join('') || '<div class="empty">暂无规则。</div>'}</div><div class="row"><button class="ghost" onclick="addRule('${key}')">新增${label}</button></div>`;
  return block(accepted,'accepted_iteration_rules','已采纳纠错') + block(rejected,'rejected_iteration_rules','已驳回纠错');
}
function renderHistoryEditor() {
  const history = Array.isArray(selectedMemoryContent.history) ? selectedMemoryContent.history : [];
  const recent = history.map((entry,index)=>({entry,index})).slice(-30).reverse();
  return `<h3>最近聊天</h3><p class="note">可删除污染项，也可以修正明显错误文本。这里改的是记忆里的历史上下文，不会撤回 QQ 消息。</p>${recent.map(({entry,index})=>`
    <div class="history-item">
      <div class="entry-head">
        <strong>${entry.role === 'assistant' ? '亚托莉' : '用户'} ${entry.nickname ? ' · ' + escapeHtml(entry.nickname) : ''}</strong>
        <button class="danger" onclick="removeHistory(${index})">删除</button>
      </div>
      <textarea oninput="updateHistory(${index},this.value)">${escapeHtml(entry.text || '')}</textarea>
    </div>`).join('') || '<div class="empty">暂无聊天历史。</div>'}`;
}
function updateMemoryEntry(layer, index, key, value, numeric=false) {
  const memory = structuredMemory();
  if(!memory[layer] || !memory[layer][index]) return;
  memory[layer][index][key] = numeric && value !== '' ? Number(value) : value;
  if(key === 'key') memory[layer][index].memory_key = value;
  markMemoryDirty();
}
function removeMemoryEntry(layer, index) {
  const memory = structuredMemory();
  if(!memory[layer] || !memory[layer][index]) return;
  memory[layer].splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function addMemoryEntryFromActivePane() {
  if(!selectedMemoryContent) return;
  const layer = memoryEntryLayerForPane();
  const memory = structuredMemory();
  let category = 'profile_fact';
  if(activeMemoryPane === 'memoryEvents') category = 'event';
  if(activeMemoryPane === 'memoryStyle') category = 'communication_style';
  const now = Math.floor(Date.now() / 1000);
  memory[layer].push({
    layer: layer.toUpperCase(),
    category,
    key: category + ':新记忆',
    value: '',
    confidence: layer === 'l1' ? 0.8 : 0.7,
    activity: 1.0,
    source: 'webui',
    created_at: now,
    updated_at: now,
    state: 'active',
    associations: []
  });
  markMemoryDirty();
  renderMemoryModal();
}
function updateRule(bucket, index, key, value) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  if(!selectedMemoryContent[bucket][index]) return;
  selectedMemoryContent[bucket][index][key] = value;
  markMemoryDirty();
}
function addRule(bucket) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  selectedMemoryContent[bucket].push({at:Math.floor(Date.now()/1000), action: bucket.startsWith('accepted') ? 'accept' : 'reject', rule:'', reason:'webui 手动添加'});
  markMemoryDirty();
  renderMemoryModal();
}
function removeRule(bucket, index) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  selectedMemoryContent[bucket].splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function updateHistory(index, value) {
  if(!Array.isArray(selectedMemoryContent.history) || !selectedMemoryContent.history[index]) return;
  selectedMemoryContent.history[index].text = value;
  markMemoryDirty();
}
function removeHistory(index) {
  if(!Array.isArray(selectedMemoryContent.history)) return;
  selectedMemoryContent.history.splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function applyRawMemory() {
  try {
    selectedMemoryContent = JSON.parse($('memoryRawEditor').value);
  } catch(e) {
    return toast('JSON 格式错误：' + e.message);
  }
  markMemoryDirty();
  renderMemoryModal();
  toast('JSON 已应用，保存后生效');
}
async function saveSelectedMemory() {
  if(!currentMemoryId || !selectedMemoryContent) return toast('先打开一条记忆');
  const btn = $('memorySaveButton');
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    const r = await api('/api/memory/save', {method:'POST', body:JSON.stringify({id:currentMemoryId, content:selectedMemoryContent})});
    setSaveState('已保存，下一轮聊天生效', false);
    toast('记忆已保存，已自动备份');
    await loadMemory();
    const d = await api('/api/memory/detail?id=' + encodeURIComponent(currentMemoryId));
    selectedMemory = d;
    selectedMemoryContent = JSON.parse(JSON.stringify(d.content || {}));
    renderMemoryModal();
  } catch(e) {
    toast('保存失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '保存修改';
  }
}
async function deleteSelectedMemory() {
  if(!currentMemoryId) return toast('先打开一条记忆');
  if(!confirm('确认删除这个会话的全部记忆？删除前会自动备份。')) return;
  await api('/api/memory/delete', {method:'POST', body:JSON.stringify({id:currentMemoryId})});
  currentMemoryId = ''; selectedMemory = null; selectedMemoryContent = null; memoryDirty = false;
  $('memoryModal').classList.remove('show');
  await loadMemory(); toast('记忆已删除，已自动备份');
}
async function backupMemory() {
  await api('/api/memory/backup', {method:'POST', body:'{}'});
  toast('记忆已备份');
}
async function testChat() {
  $('testOut').textContent='亚托莉生成中...';
  const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:$('testText').value})});
  $('testOut').textContent = r.reply;
}
async function restartServices() {
  const r = await api('/api/restart', {method:'POST', body:'{}'});
  toast(r.message || r.error || '已执行');
}
loadStatus(); loadProfiles(); loadConfig();
</script>
</body>
</html>"""


def memory_summary() -> dict[str, Any]:
    data = load_memory_data()
    conversations = memory_conversations(data)
    items = []
    for key, item in sorted(
        conversations.items(),
        key=lambda pair: float((pair[1] or {}).get("last_user_at") or 0),
        reverse=True,
    ):
        if not isinstance(item, dict):
            continue
        counts = memory_counts(item)
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        searchable = " ".join(
            [
                key,
                memory_display_name(key, item),
                str(target.get("user_id") or ""),
                str(target.get("group_id") or ""),
                natural_memory_summary(item),
            ]
        )
        proactive_state, proactive_blocked = group_proactive_state(key, item)
        items.append(
            {
                "id": key,
                "kind": memory_kind(key),
                "type": memory_type_label(key),
                "display_name": memory_display_name(key, item),
                "summary": natural_memory_summary(item),
                "messages": item.get("message_count", 0),
                "last_user_at": item.get("last_user_at"),
                "last_user_at_text": format_timestamp(item.get("last_user_at")),
                "last_bot_at": item.get("last_bot_at"),
                "affection": item.get("affection_score"),
                "affection_label": affection_label(item.get("affection_score")),
                "activity": item.get("group_activity_score"),
                "activity_label": group_activity_label(item.get("group_activity_score")),
                "proactive_state": proactive_state,
                "proactive_blocked": proactive_blocked,
                "target": target,
                "history_count": len(item.get("history") or []),
                "memory_counts": counts,
                "searchable": searchable,
            }
        )
    return {"path": str(MEMORY_PATH), "conversations": len(items), "items": items}


def memory_detail(query: str) -> dict[str, Any]:
    conversation_id = parse_qs(query).get("id", [""])[0]
    data = load_memory_data()
    conversations = memory_conversations(data)
    item = conversations.get(conversation_id)
    if not isinstance(item, dict):
        return {"ok": False, "error": "memory not found"}
    return {
        "ok": True,
        "id": conversation_id,
        "kind": memory_kind(conversation_id),
        "type": memory_type_label(conversation_id),
        "display_name": memory_display_name(conversation_id, item),
        "natural": natural_memory_detail(item),
        "affection_label": affection_label(item.get("affection_score")),
        "activity_label": group_activity_label(item.get("group_activity_score")),
        "memory_counts": memory_counts(item),
        "history_count": len(item.get("history") or []),
        "content": item,
    }


def save_memory_conversation(conversation_id: str, content: dict[str, Any]) -> Path:
    data = load_memory_data()
    conversations = memory_conversations(data)
    if conversation_id not in conversations:
        raise ValueError("会话不存在")
    if not isinstance(content, dict):
        raise ValueError("记忆内容必须是 JSON 对象")
    backup = backup_memory("edit")
    conversations[conversation_id] = content
    write_memory_data(data)
    return backup


def delete_memory_conversation(conversation_id: str) -> Path:
    data = load_memory_data()
    conversations = memory_conversations(data)
    if conversation_id not in conversations:
        raise ValueError("会话不存在")
    backup = backup_memory("delete")
    conversations.pop(conversation_id, None)
    write_memory_data(data)
    return backup


def memory_kind(conversation_id: str) -> str:
    if conversation_id.startswith("private:"):
        return "private"
    if ":user:" in conversation_id:
        return "member"
    if conversation_id.startswith("group:"):
        return "group"
    return "unknown"


def memory_type_label(conversation_id: str) -> str:
    kind = memory_kind(conversation_id)
    return {
        "private": "私聊",
        "member": "群内用户",
        "group": "群聊",
    }.get(kind, "未知")


def memory_display_name(conversation_id: str, item: dict[str, Any]) -> str:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    history = item.get("history") if isinstance(item.get("history"), list) else []
    nickname = latest_nickname(history)
    user_id = str(
        target.get("user_id")
        or parse_memory_id_piece(conversation_id, "private")
        or parse_memory_id_piece(conversation_id, "user")
        or ""
    )
    group_id = str(target.get("group_id") or parse_memory_id_piece(conversation_id, "group") or "")
    kind = memory_kind(conversation_id)
    if kind == "private":
        return f"{nickname}（QQ {user_id}）" if nickname else f"QQ {user_id or conversation_id.removeprefix('private:')}"
    if kind == "member":
        user_piece = user_id or parse_memory_id_piece(conversation_id, "user")
        group_piece = group_id or parse_memory_id_piece(conversation_id, "group")
        return (
            f"{nickname}（群 {group_piece} / QQ {user_piece}）"
            if nickname
            else f"群 {group_piece} 的 QQ {user_piece}"
        )
    if kind == "group":
        return f"群 {group_id or conversation_id.removeprefix('group:')}"
    return nickname or conversation_id


def latest_nickname(history: list[Any]) -> str:
    for entry in reversed(history[-300:]):
        if not isinstance(entry, dict):
            continue
        nickname = clean_plain(str(entry.get("nickname") or ""))
        if nickname:
            return nickname[:40]
    return ""


def natural_memory_summary(item: dict[str, Any]) -> str:
    lines = [line for line in natural_memory_detail(item).splitlines() if line.strip()]
    return "；".join(lines[:3])[:220] or "暂无可读摘要，可能只有原始聊天统计。"


def natural_memory_detail(item: dict[str, Any]) -> str:
    lines: list[str] = []
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l1 = [m for m in structured.get("l1", []) if isinstance(m, dict)]
    l2 = [m for m in structured.get("l2", []) if isinstance(m, dict)]
    candidates = [m for m in structured.get("candidates", []) if isinstance(m, dict)]
    rules = item.get("accepted_iteration_rules") if isinstance(item.get("accepted_iteration_rules"), list) else []
    topics = item.get("topic_words") if isinstance(item.get("topic_words"), list) else []
    history = item.get("history") if isinstance(item.get("history"), list) else []

    profile_lines = natural_memory_values(
        [m for m in l1 if str(m.get("category") or "") in {"profile_fact", "interest"}],
        limit=6,
    )
    if profile_lines:
        lines.append("用户信息：" + "；".join(profile_lines))

    style_lines = natural_memory_values(
        [m for m in l1 if str(m.get("category") or "") == "communication_style"],
        limit=4,
    )
    if style_lines:
        lines.append("聊天习惯：" + "；".join(style_lines))

    event_lines = natural_memory_values(l2, limit=6)
    if event_lines:
        lines.append("最近重要事件：" + "；".join(event_lines))

    candidate_lines = natural_memory_values(candidates, limit=3)
    if candidate_lines:
        lines.append("待确认偏好：" + "；".join(candidate_lines))

    clean_topics = [shorten_plain(str(x), 18) for x in topics if useful_plain_text(str(x))][:8]
    if clean_topics:
        lines.append("常聊话题：" + "、".join(clean_topics))

    clean_rules = [
        shorten_plain(str(rule.get("rule") or ""), 42)
        for rule in rules
        if isinstance(rule, dict) and useful_plain_text(str(rule.get("rule") or ""))
    ][:4]
    if clean_rules:
        lines.append("用户明确要求：" + "；".join(clean_rules))

    recent = []
    for entry in history[-10:]:
        if not isinstance(entry, dict):
            continue
        role = "用户" if entry.get("role") == "user" else "亚托莉"
        text = clean_plain(str(entry.get("text") or ""))
        if text:
            recent.append(f"{role}：{shorten_plain(text, 40)}")
    if recent:
        lines.append("最近聊天：" + " / ".join(recent[-4:]))

    if not lines:
        lines.append("暂无可读摘要。可以打开详情查看或编辑原始 JSON。")
    return "\n".join(lines)


def natural_memory_values(memories: list[dict[str, Any]], limit: int = 5) -> list[str]:
    result: list[str] = []
    for memory in memories:
        value = clean_plain(str(memory.get("value") or memory.get("key") or ""))
        category = str(memory.get("category") or "").strip()
        if not useful_plain_text(value):
            continue
        label = memory_category_label(category)
        result.append(f"{label}{shorten_plain(value, 42)}" if label else shorten_plain(value, 42))
        if len(result) >= limit:
            break
    return result


def memory_category_label(category: str) -> str:
    return {
        "interest": "兴趣：",
        "profile_fact": "资料：",
        "communication_style": "说话习惯：",
        "schedule": "日程：",
        "event": "事件：",
        "important_interaction": "互动：",
    }.get(category, "")


def memory_counts(item: dict[str, Any]) -> dict[str, int]:
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l1 = [m for m in structured.get("l1", []) if isinstance(m, dict)]
    l2 = [m for m in structured.get("l2", []) if isinstance(m, dict)]
    candidates = [m for m in structured.get("candidates", []) if isinstance(m, dict)]
    return {
        "l1": len(l1),
        "l2": len(l2),
        "candidates": len(candidates),
        "total": len(l1) + len(l2) + len(candidates),
    }


def format_timestamp(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def affection_label(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "普通"
    if score >= 84:
        return "非常亲近"
    if score >= 68:
        return "亲近"
    if score >= 42:
        return "自然"
    if score >= 24:
        return "克制"
    return "保持距离"


def group_activity_label(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "普通"
    if score >= 72:
        return "热闹"
    if score >= 38:
        return "普通"
    return "冷清"


def group_proactive_state(conversation_id: str, item: dict[str, Any]) -> tuple[str, bool]:
    if memory_kind(conversation_id) != "group":
        return "", False
    max_days = configured_group_silence_days()
    last_user_at = as_float(item.get("last_user_at"))
    if not last_user_at:
        return "未建立主动发言目标", True
    elapsed_days = max(0.0, (time.time() - last_user_at) / 86400)
    if max_days <= 0:
        return "主动发言未按天数限制", False
    if elapsed_days > max_days:
        return f"已静默 {elapsed_days:.1f} 天，停止主动发言", True
    return f"{elapsed_days:.1f} 天内有消息，可低频主动", False


def configured_group_silence_days() -> int:
    raw = read_env().get("GROUP_PROACTIVE_MAX_SILENCE_DAYS", "").strip()
    try:
        return max(0, int(raw)) if raw else 3
    except ValueError:
        return 3


def useful_plain_text(text: str) -> bool:
    text = clean_plain(text)
    if not text or len(text) < 2:
        return False
    if re.fullmatch(r"[\W_0-9]+", text):
        return False
    return True


def clean_plain(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or looks_like_bad_text(text):
        return ""
    return text


def looks_like_bad_text(text: str) -> bool:
    if "\ufffd" in text:
        return True
    if re.search(r"(锟|閿|�){2,}", text):
        return True
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_count < 6:
        return False
    mojibake_hits = len(re.findall(r"[缁嬩焦娴ｇ姵妲搁崥妤冩畱閻劍鍩涢幋鎴滅瑝]", text))
    return mojibake_hits / max(chinese_count, 1) > 0.65


def shorten_plain(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
