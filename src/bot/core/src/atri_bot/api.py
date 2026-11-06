from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hmac
import json
import logging
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from pathlib import Path

from .identity import platform_turn
from .turn_ledger import TurnLedger

LOGGER = logging.getLogger("atri.core_api")
_LOOP: asyncio.AbstractEventLoop | None = None
MAX_BODY_BYTES = 12_000_000


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Bind the core event loop, with or without an attached QQ transport."""

    global _LOOP
    _LOOP = loop


class CoreApiError(RuntimeError):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = int(status)


class CoreApiState:
    """Small, deep seam around the existing reply engine.

    HTTP worker threads never touch engine state directly.  Requests are
    marshalled back to the main asyncio loop. The engine owns its reply lock;
    this API lock additionally protects durable platform generation receipts.
    """

    def __init__(self, config: Any, runtime: Any) -> None:
        self.config = config
        self.runtime = runtime
        self.chat_lock = asyncio.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "chat": True,
            "vision": bool(getattr(self.config, "toolbox_vision_enabled", False)),
            "asr": bool(getattr(self.config, "voice_asr_enabled", False)),
            "tts": bool(getattr(self.config, "voice_tts_enabled", False)),
            "singing": True,
            "streaming_events": False,
        }

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        origin = payload.get('origin')
        event = None
        ledger = None
        if origin is not None:
            if not str(getattr(self.config, 'core_api_key', '') or '').strip():
                raise CoreApiError('平台接入需要配置 CORE_API_KEY', HTTPStatus.FORBIDDEN)
            try:
                event = platform_turn(origin, str(payload.get('text') or ''), str(payload.get('user_name') or '平台用户'))
            except ValueError as exc:
                raise CoreApiError(str(exc)) from exc
            # Identity and observation state come from normalized routing, never
            # arbitrary profile/owner IDs supplied by the platform payload.
            payload = dict(payload, conversation_id=event.request.conversation_id,
                           profile_id=event.request.profile_id, observed=False)
            ledger = TurnLedger(Path(self.config.memory_path).with_suffix('.platform-turns.sqlite3'))
        async with self.chat_lock:
            # Validate and analyze attachments before claiming generation; a
            # malformed attachment can be corrected without consuming a turn.
            return await self._chat_once(payload, event=event, ledger=ledger)

    async def _chat_once(self, payload, *, event=None, ledger=None):
        text = str(payload.get("text") or "").strip()
        if not text:
            raise CoreApiError("text 不能为空")
        if len(text) > 12_000:
            raise CoreApiError("text 过长")

        attachments = payload.get("attachments") or []
        if not isinstance(attachments, list) or len(attachments) > 3:
            raise CoreApiError("attachments 必须是最多 3 项的数组")

        user_id = str(payload.get("user_id") or "api-user").strip()[:160]
        user_name = str(payload.get("user_name") or "API 用户").strip()[:160]
        conversation_id = str(
            payload.get("conversation_id") or f"private:{user_id}"
        ).strip()[:240]
        profile_id = str(payload.get("profile_id") or conversation_id).strip()[:240]
        observed = bool(payload.get("observed", False))
        tool_context = await self._build_tool_context(attachments, text)

        if ledger is not None:
            try:
                cached = ledger.claim(event.event_key, payload)
            except ValueError as exc:
                raise CoreApiError(str(exc), HTTPStatus.CONFLICT) from exc
            if cached is not None:
                return cached

        engine = getattr(self.runtime, "reply_engine", None)
        reply_method = getattr(engine, "reply", None)
        if not callable(reply_method):
            raise CoreApiError("ATRI 回复引擎不可用", HTTPStatus.SERVICE_UNAVAILABLE)

        try:
            reply = await reply_method(
                conversation_id,
                text,
                user_name,
                profile_id,
                observed,
                tool_context,
            )
        except Exception as exc:  # pragma: no cover - provider dependent
            LOGGER.exception("core API chat failed")
            raise CoreApiError(
                f"ATRI 回复失败：{type(exc).__name__}",
                HTTPStatus.BAD_GATEWAY,
            ) from exc

        reply_text = str(reply or "").strip()
        if not reply_text:
            raise CoreApiError("ATRI 返回空回复", HTTPStatus.BAD_GATEWAY)
        result = {
            "ok": True,
            "version": "v1",
            "conversation_id": conversation_id,
            "profile_id": profile_id,
            "reply": reply_text,
            "emotion": "neutral",
            "motion": "idle",
            "source": "atri-core",
            "vision": _vision_summary(tool_context),
        }
        if ledger is not None:
            ledger.complete(event.event_key, result)
        return result

    async def _build_tool_context(
        self,
        attachments: list[Any],
        user_question: str,
    ) -> Any | None:
        if not attachments:
            return None
        tools = getattr(self.runtime, "tools", None)
        analyze_upload = getattr(tools, "analyze_image_upload", None)
        contexts = []
        for index, attachment in enumerate(attachments):
            if not isinstance(attachment, dict):
                raise CoreApiError(f"attachments[{index}] 必须是对象")
            kind = str(attachment.get("type") or "image").lower()
            if kind != "image":
                raise CoreApiError("当前只支持 type=image 的视觉附件", HTTPStatus.NOT_IMPLEMENTED)
            encoded = str(attachment.get("data_base64") or "").strip()
            if not encoded:
                raise CoreApiError(f"attachments[{index}] 缺少 data_base64")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise CoreApiError(f"attachments[{index}] 不是有效 base64") from exc
            if not callable(analyze_upload):
                raise CoreApiError("视觉分析能力不可用", HTTPStatus.SERVICE_UNAVAILABLE)
            source = str(attachment.get("name") or f"api:image:{index}")[:180]
            try:
                contexts.append(
                    await analyze_upload(data, source, user_question=user_question)
                )
            except CoreApiError:
                raise
            except Exception as exc:  # pragma: no cover - provider dependent
                raise CoreApiError(
                    f"视觉分析失败：{type(exc).__name__}",
                    HTTPStatus.BAD_GATEWAY,
                ) from exc
        # The current reply engine accepts one ToolAnalysisResult.  Multiple
        # images are therefore exposed as a single merged evidence object.
        return _merge_visual_contexts(contexts)


class CoreApiHandler(BaseHTTPRequestHandler):
    state: CoreApiState

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path == "/api/v1/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "atri-core",
                    "version": "v1",
                    "capabilities": self.state.capabilities(),
                }
            )
            return
        if not self._authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, "ATRI Core API 鉴权失败")
            return
        if self.path == "/api/v1/capabilities":
            self._send_json(
                {
                    "ok": True,
                    "version": "v1",
                    "capabilities": self.state.capabilities(),
                }
            )
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path != "/api/v1/chat":
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self._authorized():
            # Consume a bounded request body before closing the connection.
            # On Windows, unread incoming bytes can reset the socket and hide
            # the 401 response from an HTTP client. Never parse this body or
            # invoke the core, and bound the wait for an incomplete upload.
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if 0 < length <= MAX_BODY_BYTES:
                self.connection.settimeout(1.0)
                with contextlib.suppress(OSError):
                    self.rfile.read(length)
            self._send_error(HTTPStatus.UNAUTHORIZED, "ATRI Core API 鉴权失败")
            return
        try:
            payload = self._read_json()
            result = _run_on_main_loop(self.state.chat(payload), self.state.config)
        except CoreApiError as exc:
            self._send_error(exc.status, str(exc))
            return
        except (TimeoutError, asyncio.TimeoutError):
            self._send_error(HTTPStatus.GATEWAY_TIMEOUT, "ATRI API 请求超时")
            return
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            LOGGER.exception("core API request failed")
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self._send_json(result)

    def _authorized(self) -> bool:
        expected = str(getattr(self.state.config, "core_api_key", "") or "").strip()
        if not expected:
            return True
        supplied = str(self.headers.get("X-ATRI-API-Key", "") or "").strip()
        if not supplied:
            authorization = str(self.headers.get("Authorization", "") or "")
            if authorization.lower().startswith("bearer "):
                supplied = authorization[7:].strip()
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise CoreApiError("Content-Length 无效") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise CoreApiError("请求体为空或过大")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoreApiError("请求体必须是 UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise CoreApiError("JSON 请求体必须是对象")
        return payload

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(
            {"ok": False, "error": str(message), "status": int(status)},
            status,
        )


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _run_on_main_loop(coro: Any, config: Any) -> Any:
    if _LOOP is None or _LOOP.is_closed():
        coro.close()
        raise CoreApiError("ATRI 主事件循环不可用", HTTPStatus.SERVICE_UNAVAILABLE)
    timeout = max(1.0, float(getattr(config, "core_api_timeout_seconds", 120.0)))
    future = asyncio.run_coroutine_threadsafe(coro, _LOOP)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        raise


def _merge_visual_contexts(contexts: list[Any]) -> Any | None:
    if not contexts:
        return None
    if len(contexts) == 1:
        return contexts[0]
    first = contexts[0]
    try:
        return replace(
            first,
            sources=_dedupe(
                item for context in contexts for item in getattr(context, "sources", [])
            ),
            findings=_dedupe(
                item for context in contexts for item in getattr(context, "findings", [])
            ),
            limitations=_dedupe(
                item
                for context in contexts
                for item in getattr(context, "limitations", [])
            ),
            visual_data=None,
            visual_source="api:images",
        )
    except (TypeError, ValueError):
        return first


def _dedupe(items: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _vision_summary(context: Any | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "status": str(getattr(context, "visual_status", "") or ""),
        "kind": str(getattr(context, "visual_kind", "") or ""),
        "findings": list(getattr(context, "findings", []) or [])[:12],
        "limitations": list(getattr(context, "limitations", []) or [])[:8],
        "read_level": str(getattr(context, "read_level", "") or ""),
    }


async def start_core_api(config: Any, runtime: Any) -> Any | None:
    if not bool(getattr(config, "core_api_enabled", True)):
        return None
    host = str(getattr(config, "core_api_host", "127.0.0.1") or "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        host = "127.0.0.1"
    port = int(getattr(config, "core_api_port", 8795) or 8795)
    state = CoreApiState(config, runtime)

    class Handler(CoreApiHandler):
        pass

    Handler.state = state
    try:
        httpd = LocalThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        LOGGER.error("core API unavailable at http://%s:%s: %s", host, port, exc)
        return None
    task = asyncio.create_task(asyncio.to_thread(httpd.serve_forever))
    httpd._atri_core_task = task  # type: ignore[attr-defined]
    httpd._atri_core_state = state  # type: ignore[attr-defined]
    LOGGER.info("Core API listening on http://%s:%s", host, port)
    return httpd


async def stop_core_api(httpd: Any | None) -> None:
    if httpd is None:
        return
    await asyncio.to_thread(httpd.shutdown)
    httpd.server_close()
    task = getattr(httpd, "_atri_core_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
