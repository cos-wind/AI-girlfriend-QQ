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
from urllib.parse import parse_qs, quote, urlparse

from atri_qq_bot.config import BotConfig, load_config
from atri_qq_bot.persona import AtriReplyEngine
from atri_qq_bot.proactive import load_proactive_policy, save_proactive_policy
from atri_qq_bot.runtime import PROJECT_ROOT, STICKER_DELETED_DIR, STICKER_ROOT
from atri_qq_bot.voice import (
    VoicePromptContext,
    VoiceRequest,
    load_voice_behavior,
    save_voice_behavior,
)
from atri_qq_bot.runtime.control import restart_background_services, runtime_status
from .config_admin import config_payload, update_env
from .call_page import render_voice_call
from .model_profiles import (
    MODEL_PRESETS,
    activate_model_profile,
    delete_model_profile,
    local_models_payload,
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
    update_memory_relationship,
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
from .voice_admin import (
    asr_lexicon_text,
    resolve_voice_audio,
    save_asr_lexicon_text,
    save_reference_audio,
    save_test_audio,
    save_tts_pronunciation_text,
    save_voice_profile,
    tts_pronunciation_text,
    voice_candidates_payload,
    voice_profiles_payload,
)

MAX_UPLOAD_BYTES = 8_000_000
MAX_VOICE_UPLOAD_BYTES = 30_000_000

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
            if hasattr(self.server, "voice"):
                self.server.voice.update_config(new_config)
            if hasattr(self.server, "proactive_planner"):
                self.server.proactive_planner.update_owner_qqs(new_config.owner_qqs)
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
        if parsed.path == "/voice-call":
            token = parse_qs(parsed.query).get("token", [""])[0]
            session = self.webui_state.server.voice_calls.get(token)
            if session is None:
                return self._send_html(
                    "<!doctype html><meta charset='utf-8'><title>邀请无效</title>"
                    "<p style='font:16px sans-serif;padding:32px'>通话邀请已失效或已结束。</p>"
                )
            return self._send_html(render_voice_call(token, session.topic))
        if parsed.path == "/api/status":
            return self._send_json(self._status())
        if parsed.path == "/api/config":
            return self._send_json(config_payload(self.webui_state.config))
        if parsed.path == "/api/proactive":
            return self._send_json(self.webui_state.server.proactive_status())
        if parsed.path == "/api/model-presets":
            return self._send_json({"presets": MODEL_PRESETS})
        if parsed.path == "/api/model-profiles":
            return self._send_json(model_profiles_payload(self.webui_state.config))
        if parsed.path == "/api/local-models":
            return self._send_json(local_models_payload())
        if parsed.path == "/api/voice":
            return self._send_json(self._voice_payload())
        if parsed.path == "/api/voice/behavior":
            return self._send_json({"ok": True, "behavior": load_voice_behavior()})
        if parsed.path == "/api/voice/audio":
            return self._send_voice_audio(parsed.query)
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
        if parsed.path == "/api/proactive/save":
            return self._handle_proactive_save()
        if parsed.path == "/api/proactive/preview":
            return self._handle_proactive_preview()
        if parsed.path == "/api/model-profiles/save":
            return self._handle_model_profile_save()
        if parsed.path == "/api/model-profiles/delete":
            return self._handle_model_profile_delete()
        if parsed.path == "/api/model-profiles/activate":
            return self._handle_model_profile_activate()
        if parsed.path == "/api/test-chat":
            return self._handle_test_chat()
        if parsed.path == "/api/voice/save":
            return self._handle_voice_save()
        if parsed.path == "/api/voice/reference":
            return self._handle_voice_reference()
        if parsed.path == "/api/voice/preview":
            return self._handle_voice_preview()
        if parsed.path == "/api/voice/test-asr":
            return self._handle_voice_test_asr()
        if parsed.path == "/api/voice-call/turn":
            return self._handle_voice_call_turn()
        if parsed.path == "/api/voice-call/close":
            return self._handle_voice_call_close()
        if parsed.path == "/api/voice-call/test-invite":
            return self._handle_voice_call_test_invite()
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
        if parsed.path == "/api/memory/relationship":
            return self._handle_memory_relationship()
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

    def _handle_proactive_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            policy = save_proactive_policy(payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "policy": policy})

    def _handle_proactive_preview(self) -> None:
        payload = self._read_json()
        event_type = str((payload or {}).get("event_type") or "check_in")
        policy = load_proactive_policy()
        allowed = set(policy.get("content_weights") or {}) | set(
            policy.get("group_content_weights") or {}
        )
        if event_type not in allowed:
            return self._send_error(HTTPStatus.BAD_REQUEST, "未知的主动消息类型")
        raw_user_id = (payload or {}).get("user_id")
        raw_target_id = (payload or {}).get("target_id") or raw_user_id
        scope = str((payload or {}).get("scope") or "private")
        if scope not in {"private", "group"}:
            return self._send_error(HTTPStatus.BAD_REQUEST, "未知的预览范围")
        try:
            target_id = int(raw_target_id) if raw_target_id else None
            result = run_coro(
                self.webui_state.server.preview_proactive(event_type, target_id, scope)
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, **result})

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
            result = run_coro(test_chat(self.webui_state.config, text))
        except Exception as exc:
            return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        self._send_json({"ok": True, **result})

    def _voice_payload(self) -> dict[str, Any]:
        try:
            health = run_coro(self.webui_state.server.voice.client.health())
        except Exception as exc:
            health = {"ok": False, "error": str(exc), "ready": False}
        return {
            "ok": True,
            "config": config_payload(self.webui_state.config),
            "service": health,
            "profiles": voice_profiles_payload(),
            "candidates": voice_candidates_payload(),
            "asr_lexicon_text": asr_lexicon_text(),
            "tts_pronunciation_text": tts_pronunciation_text(),
            "behavior": load_voice_behavior(),
        }

    def _handle_voice_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            config_changes = payload.get("config")
            if isinstance(config_changes, dict):
                update_env(config_changes)
                config = run_coro(self.webui_state.reload_config())
            else:
                config = self.webui_state.config
            profile_payload = payload.get("profile")
            profile = (
                save_voice_profile(profile_payload)
                if isinstance(profile_payload, dict)
                else None
            )
            if "asr_lexicon_text" in payload:
                save_asr_lexicon_text(str(payload.get("asr_lexicon_text") or ""))
            if "tts_pronunciation_text" in payload:
                save_tts_pronunciation_text(
                    str(payload.get("tts_pronunciation_text") or "")
                )
            behavior_payload = payload.get("behavior")
            if isinstance(behavior_payload, dict):
                save_voice_behavior(behavior_payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {
                "ok": True,
                "config": config_payload(config),
                "profile": profile.public_dict() if profile else None,
            }
        )

    def _handle_voice_call_turn(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_VOICE_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "通话音频最大 30MB")
        audio_path: Path | None = None
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            token = multipart_text(form, "token", "").strip()
            session = self.webui_state.server.voice_calls.get(token)
            if session is None:
                raise ValueError("通话邀请已失效或已结束")
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("没有收到通话音频")
            language = multipart_text(form, "language", "auto").strip().lower()
            if language not in {"auto", "zh", "en", "ja"}:
                language = "auto"
            audio_path = save_test_audio(str(file_item.filename), file_item.data)
            started_at = time.perf_counter()
            transcript = run_coro(
                self.webui_state.server.voice.client.transcribe(audio_path, language)
            )
            reply = run_coro(
                self.webui_state.server.reply_engine.reply(
                    session.conversation_id,
                    transcript.text,
                    profile_id=session.conversation_id,
                    observed=False,
                    tool_context=VoicePromptContext(
                        transcript,
                        prefer_voice_reply=True,
                    ),
                )
            )
            voice_request = self.webui_state.server.reply_engine.consume_voice_request(
                session.conversation_id
            )
            consume_call = getattr(
                self.webui_state.server.reply_engine,
                "consume_call_request",
                None,
            )
            if callable(consume_call):
                consume_call(session.conversation_id)
            spoken_text = str(voice_request.text if voice_request else reply).strip()
            if not spoken_text:
                spoken_text = "我在听，再和我说一点吧。"
            max_chars = max(20, int(self.webui_state.config.voice_max_chars))
            spoken_text = spoken_text[:max_chars].strip()
            synthesis_request = VoiceRequest(
                text=spoken_text,
                emotion=voice_request.emotion if voice_request else "gentle",
                intensity=voice_request.intensity if voice_request else 0.55,
                language=voice_request.language if voice_request else "auto",
                reason="voice_reply",
            )
            synthesis = run_coro(
                self.webui_state.server.voice.synthesize(
                    session.conversation_id,
                    synthesis_request,
                    enforce_cooldown=False,
                )
            )
            self.webui_state.server.reply_engine.record_bot_reply(
                session.conversation_id,
                spoken_text,
                profile_id=session.conversation_id,
            )
            self.webui_state.server.voice_calls.mark_turn(token)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        finally:
            if audio_path is not None:
                with contextlib.suppress(OSError):
                    audio_path.unlink()
        self._send_json(
            {
                "ok": True,
                "transcript": transcript.text,
                "reply": spoken_text,
                "audio_url": f"/api/voice/audio?path={quote(str(synthesis.audio_path))}",
                "elapsed_ms": elapsed_ms,
            }
        )

    def _handle_voice_call_close(self) -> None:
        payload = self._read_json()
        token = str((payload or {}).get("token") or "").strip()
        if token:
            self.webui_state.server.voice_calls.close(token)
        self._send_json({"ok": True})

    def _handle_voice_call_test_invite(self) -> None:
        policy = load_voice_behavior()
        if not policy["calls_enabled"]:
            return self._send_error(HTTPStatus.BAD_REQUEST, "请先启用并保存浏览器通话")
        if not bool(self.webui_state.config.voice_tts_enabled):
            return self._send_error(HTTPStatus.BAD_REQUEST, "请先启用语音合成")
        owner_qqs = tuple(getattr(self.webui_state.config, "owner_qqs", ()) or ())
        if not owner_qqs:
            return self._send_error(HTTPStatus.BAD_REQUEST, "没有配置主人 QQ，无法建立测试会话")
        session = self.webui_state.server.voice_calls.create(
            f"private:{int(owner_qqs[0])}",
            "WebUI 通话链路测试",
            int(policy["call_expiry_minutes"]),
            int(policy["call_max_minutes"]),
        )
        call_url = (
            f"{str(policy['call_base_url']).rstrip('/')}/voice-call?token={session.token}"
        )
        self._send_json({"ok": True, "call_url": call_url, "session": session.public_dict()})

    def _handle_voice_reference(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_VOICE_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "参考音频最大 30MB")
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            profile_id = multipart_text(form, "profile_id", "atri")
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("请选择参考音频")
            if len(file_item.data) > MAX_VOICE_UPLOAD_BYTES:
                raise ValueError("参考音频最大 30MB")
            profile = save_reference_audio(
                profile_id,
                str(file_item.filename),
                file_item.data,
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "profile": profile.public_dict()})

    def _handle_voice_preview(self) -> None:
        payload = self._read_json()
        try:
            request = VoiceRequest.from_tool_arguments(
                payload if isinstance(payload, dict) else {},
                max_chars=int(self.webui_state.config.voice_max_chars),
            )
            profile_id = str((payload or {}).get("profile") or "atri")
            behavior = load_voice_behavior()
            started_at = time.perf_counter()
            result = run_coro(
                self.webui_state.server.voice.client.synthesize(
                    request,
                    profile_id,
                    prefer_original=bool(behavior.get("original_clip_enabled", True)),
                    quality_gate=bool(behavior.get("quality_gate_enabled", True)),
                    quality_max_error_rate=float(
                        behavior.get("quality_max_error_rate", 0.22)
                    ),
                    quality_retries=int(behavior.get("quality_retries", 1) or 0),
                )
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {
                "ok": True,
                "audio_url": f"/api/voice/audio?path={quote(str(result.audio_path))}",
                "audio_path": str(result.audio_path),
                "duration_seconds": result.duration_seconds,
                "source": result.source,
                "quality": result.quality,
                "elapsed_ms": elapsed_ms,
            }
        )

    def _handle_voice_test_asr(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_VOICE_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "测试音频最大 30MB")
        audio_path: Path | None = None
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("请选择测试音频")
            if len(file_item.data) > MAX_VOICE_UPLOAD_BYTES:
                raise ValueError("测试音频最大 30MB")
            language = multipart_text(form, "language", "auto").strip().lower()
            if language not in {"auto", "zh", "en", "ja"}:
                raise ValueError("识别语言只支持自动、中文、英文或日文")
            audio_path = save_test_audio(str(file_item.filename), file_item.data)
            started_at = time.perf_counter()
            result = run_coro(
                self.webui_state.server.voice.client.transcribe(audio_path, language)
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        finally:
            if audio_path is not None:
                with contextlib.suppress(OSError):
                    audio_path.unlink()
        self._send_json(
            {
                "ok": True,
                "text": result.text,
                "language": result.language,
                "emotion": result.emotion,
                "confidence": result.confidence,
                "elapsed_ms": elapsed_ms,
            }
        )

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

    def _handle_memory_relationship(self) -> None:
        payload = self._read_json()
        conversation_id = str((payload or {}).get("id") or "")
        if not conversation_id:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少会话 id")
        try:
            backup, relationship = update_memory_relationship(
                conversation_id,
                (payload or {}).get("affection_score"),
                (payload or {}).get("proactive_override"),
                (payload or {}).get("group_activity_score"),
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {"ok": True, "backup": str(backup), "relationship": relationship}
        )

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

    def _send_voice_audio(self, query: str) -> None:
        raw_path = parse_qs(query).get("path", [""])[0]
        path = resolve_voice_audio(raw_path)
        if path is None:
            return self._send_error(HTTPStatus.NOT_FOUND, "audio not found")
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
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


async def test_chat(config: BotConfig, text: str) -> dict[str, Any]:
    engine = AtriReplyEngine(
        replace(config, idle_proactive_enabled=False, group_proactive_enabled=False)
    )
    try:
        reply = await engine._reply_with_guarded_api("webui:test", text, "主人")
        reply = engine._finalize_reply("webui:test", text, reply)
        if not reply:
            raise RuntimeError("模型返回了空回复")
        return {"reply": reply, "used_ai": True, "error": ""}
    except Exception as exc:
        return {
            "reply": engine._fallback_reply("webui:test", text),
            "used_ai": False,
            "error": str(exc),
        }
