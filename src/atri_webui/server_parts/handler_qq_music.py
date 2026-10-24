"""QQ 成品歌曲清单与文件导入。"""

from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerQQMusicMixin(WebUIHandlerMixin):
    def _songs_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "root": str(MUSIC_ROOT),
            "songs": [
                {"title": song.title, "name": song.path.name, "size": song.path.stat().st_size}
                for song in song_catalog()
            ],
        }

    def _handle_song_upload(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_COMPLETE_MUSIC_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "完整音乐最大 180MB")
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""), self.rfile.read(content_length)
            )
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("请选择完整歌曲文件")
            if len(file_item.data) > MAX_COMPLETE_MUSIC_UPLOAD_BYTES:
                raise ValueError("完整音乐最大 180MB")
            path = save_song(str(file_item.filename), file_item.data)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "path": str(path), "name": path.name})
