from __future__ import annotations

from http import HTTPStatus

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerResponseMixin(WebUIHandlerMixin):
    def _status(self) -> dict[str, Any]:
        return runtime_status(self.webui_state.config)

    def _developer_payload(self) -> dict[str, Any]:
        """开发面板只提供本机诊断信息，Token 不写入项目日志。"""
        return {
            "ok": True,
            "status": self._status(),
            "log_file": str(LOG_DIR / f"project-{datetime.now().astimezone():%Y-%m-%d}.log"),
            "log_levels": ["all", "debug", "info", "warning", "error"],
            "refresh_seconds": 3,
        }

    def _logs_payload(self, query: str) -> dict[str, Any]:
        params = parse_qs(query)
        level = str(params.get("level", ["all"])[0]).lower()
        limit = int(str(params.get("limit", ["240"])[0]) or 240)
        return {"ok": True, "level": level, "lines": read_project_logs(level, limit)}

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

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_download(self, body: bytes, filename: str, content_type: str) -> None:
        safe_name = "".join(char for char in filename if char.isalnum() or char in {"-", "_", "."})
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
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
