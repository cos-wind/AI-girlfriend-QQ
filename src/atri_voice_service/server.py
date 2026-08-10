from __future__ import annotations

import asyncio
import atexit
import ctypes
import json
import os
import threading
from collections.abc import Coroutine
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .app import SpeechApplication
from .config import VoiceServiceConfig


MAX_REQUEST_BYTES = 1_000_000
_VOICE_MUTEX_HANDLE: int | None = None


def _acquire_single_instance() -> bool:
    """防止不同 Python 环境同时加载一套语音模型，避免内存被重复占用。"""
    if os.name != "nt":
        return True
    global _VOICE_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Global\\AtriVoiceService")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _VOICE_MUTEX_HANDLE = handle

    def release() -> None:
        global _VOICE_MUTEX_HANDLE
        if _VOICE_MUTEX_HANDLE is None:
            return
        try:
            kernel32.ReleaseMutex(_VOICE_MUTEX_HANDLE)
            kernel32.CloseHandle(_VOICE_MUTEX_HANDLE)
        finally:
            _VOICE_MUTEX_HANDLE = None

    atexit.register(release)
    return True


def _singing_job_id(path: str) -> str:
    prefix = "/v1/singing/jobs/"
    if not path.startswith(prefix):
        return ""
    value = path.removeprefix(prefix).strip("/")
    return value if value and "/" not in value else ""


class VoiceHttpServer(ThreadingHTTPServer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.event_loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(
            target=self.event_loop.run_forever,
            name="atri-voice-async",
            daemon=True,
        )
        self.loop_thread.start()
        self.background_futures: set[Any] = set()
        super().__init__(*args, **kwargs)

    def run_async(self, coroutine: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
        future = asyncio.run_coroutine_threadsafe(coroutine, self.event_loop)
        return future.result()

    def run_background(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(coroutine, self.event_loop)
        self.background_futures.add(future)
        future.add_done_callback(self.background_futures.discard)

    def server_close(self) -> None:
        super().server_close()
        for future in tuple(self.background_futures):
            future.cancel()
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        self.loop_thread.join(timeout=3)
        self.event_loop.close()


def create_server(config: VoiceServiceConfig | None = None) -> VoiceHttpServer:
    resolved = config or VoiceServiceConfig.from_env()
    app = SpeechApplication(resolved)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path.rstrip("/")
            if path == "/health":
                self._json(200, app.health())
                return
            if path == "/v1/singing/jobs":
                self._json(200, self.server.run_async(app.list_singing_jobs()))
                return
            job_id = _singing_job_id(path)
            if job_id:
                try:
                    result = self.server.run_async(app.get_singing_job(job_id))
                except KeyError as exc:
                    self._json(404, {"ok": False, "error": str(exc)})
                    return
                self._json(200, {"ok": True, **result})
                return
            self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            try:
                payload = self._request_json()
                path = urlsplit(self.path).path.rstrip("/")
                if path == "/v1/transcribe":
                    result = self.server.run_async(app.transcribe(payload))
                elif path == "/v1/synthesize":
                    result = self.server.run_async(app.synthesize(payload))
                elif path == "/v1/singing/jobs":
                    result = self.server.run_async(app.create_singing_job(payload))
                    result = {"ok": True, **result}
                elif path.endswith("/cancel") and _singing_job_id(path.removesuffix("/cancel")):
                    job_id = _singing_job_id(path.removesuffix("/cancel"))
                    result = self.server.run_async(app.cancel_singing_job(job_id))
                    result = {"ok": True, **result}
                else:
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                self._json(200, result)
            except Exception as exc:
                error_payload: dict[str, Any] = {
                    "ok": False,
                    "error": str(exc),
                }
                quality = getattr(exc, "quality_report", None)
                if isinstance(quality, dict):
                    error_payload["quality"] = quality
                self._json(400, error_payload)

        def _request_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0") or 0)
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("请求体大小无效")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            return payload

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = VoiceHttpServer((resolved.host, resolved.port), Handler)
    server.run_background(app.warmup_asr())
    return server


def main() -> None:
    if not _acquire_single_instance():
        print("[voice] Another ATRI voice service is already running.")
        return
    config = VoiceServiceConfig.from_env()
    server = create_server(config)
    print(f"[voice] Listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
