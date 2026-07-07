from __future__ import annotations

import asyncio
import contextlib
import json
import mimetypes
import shutil
import time
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from atri_qq_bot.config import BotConfig, load_config
from atri_qq_bot.persona import AtriReplyEngine
from atri_qq_bot.runtime import PROJECT_ROOT, STICKER_DELETED_DIR, STICKER_ROOT
from atri_qq_bot.runtime.control import restart_background_services, runtime_status
from .config_admin import config_payload, update_env
from .model_profiles import (
    MODEL_PRESETS,
    activate_model_profile,
    delete_model_profile,
    model_profiles_payload,
    public_model_profile,
    upsert_model_profile,
)
from .memory_admin import (
    backup_memory,
    delete_memory_conversation,
    memory_detail,
    memory_summary,
    save_memory_conversation,
)
from .page import render_index
from .sticker_admin import (
    IMAGE_EXTENSIONS,
    looks_like_image_bytes,
    resolve_under,
    safe_filename,
    sanitize_category,
    sticker_file_payload,
    sticker_summary,
    unique_path,
)
from .upload_parser import multipart_file, multipart_text, parse_multipart_form

MAX_UPLOAD_BYTES = 8_000_000

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

        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

        category = sanitize_category(multipart_text(form, "category", "default"))
        if not category:
            return self._send_error(HTTPStatus.BAD_REQUEST, "分类名不合法")
        file_item = multipart_file(form, "file")
        if file_item is None or not file_item.filename:
            return self._send_error(HTTPStatus.BAD_REQUEST, "请选择图片文件")

        filename = safe_filename(str(file_item.filename))
        suffix = Path(filename).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            return self._send_error(HTTPStatus.BAD_REQUEST, "只支持 jpg/png/gif/webp")
        data = file_item.data
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
        return runtime_status(self.webui_state.config)

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
