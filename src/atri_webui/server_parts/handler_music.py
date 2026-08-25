from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerMusicMixin(WebUIHandlerMixin):
    def _handle_singing_jobs(self) -> None:
        try:
            payload = _music_bridge_request("/api/jobs")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _handle_music_projects(self) -> None:
        try:
            payload = _music_bridge_request("/api/projects")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _handle_music_capabilities(self) -> None:
        try:
            payload = _music_bridge_request("/api/capabilities")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _handle_music_sources(self) -> None:
        try:
            payload = _music_bridge_request("/api/sources")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _handle_music_project(self, query: str) -> None:
        try:
            project_id = _valid_singing_job_id(
                parse_qs(query).get("id", [""])[0]
            )
            payload = _music_bridge_request(f"/api/projects/{project_id}")
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _handle_music_project_audio(self, query: str) -> None:
        try:
            params = parse_qs(query)
            project_id = _valid_singing_job_id(params.get("id", [""])[0])
            artifact = _valid_music_artifact_name(params.get("name", [""])[0])
            headers = {"Accept": "audio/*"}
            requested_range = self.headers.get("Range", "").strip()
            if requested_range:
                headers["Range"] = requested_range
            request = Request(
                f"{MUSIC_SERVICE_URL}/api/projects/{project_id}/artifacts/{artifact}",
                headers=headers,
                method="GET",
            )
            response = urlopen(request, timeout=30)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except HTTPError as exc:
            return self._send_error(HTTPStatus(exc.code), "歌曲音频不可用")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        with response:
            self.send_response(getattr(response, "status", HTTPStatus.OK))
            for name in (
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Accept-Ranges",
                "Content-Disposition",
            ):
                value = response.headers.get(name)
                if value:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)

    def _handle_music_project_waveform(self, query: str) -> None:
        try:
            params = parse_qs(query)
            project_id = _valid_singing_job_id(params.get("id", [""])[0])
            artifact = _valid_music_artifact_name(params.get("name", [""])[0])
            payload = _music_bridge_request(
                f"/api/projects/{project_id}/waveforms/{artifact}",
                timeout=30,
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _handle_music_project_log(self, query: str) -> None:
        try:
            params = parse_qs(query)
            project_id = _valid_singing_job_id(params.get("id", [""])[0])
            stage = _valid_music_stage(params.get("stage", [""])[0])
            payload = _music_bridge_request(f"/api/projects/{project_id}/logs/{stage}")
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(payload)

    def _delivery_songs_payload(self) -> dict[str, Any]:
        """仅展示原曲和已发布片段；不调用 AI_music 或加载音频内容。"""
        COMPLETE_MUSIC_ROOT.mkdir(parents=True, exist_ok=True)
        DELIVERY_MUSIC_ROOT.mkdir(parents=True, exist_ok=True)
        complete_files = [
            {"name": path.name, "path": str(path), "size": path.stat().st_size}
            for path in complete_song_files()
        ]
        songs = []
        for song in delivery_song_catalog():
            songs.append(
                {
                    "title": song.title,
                    "path": str(song.directory),
                    "segments": [
                        {
                            "index": segment.index,
                            "name": segment.path.name,
                            "path": str(segment.path),
                            "start_seconds": segment.start_seconds,
                            "end_seconds": segment.end_seconds,
                            "duration_seconds": segment.duration_seconds,
                            "label": segment.label,
                            "url": f"/api/music/delivery-audio?path={quote(str(segment.path))}",
                        }
                        for segment in song.segments
                    ],
                }
            )
        return {
            "ok": True,
            "complete_root": str(COMPLETE_MUSIC_ROOT),
            "delivery_root": str(DELIVERY_MUSIC_ROOT),
            "complete_files": complete_files,
            "songs": songs,
        }

    def _handle_delivery_music_source_upload(self) -> None:
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
            path = save_complete_song(str(file_item.filename), file_item.data)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "path": str(path), "name": path.name})

    def _handle_delivery_music_segment(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            source = Path(str(payload.get("source_path") or "")).expanduser().resolve()
            title = str(payload.get("title") or source.stem)
            target_seconds = float(payload.get("target_seconds") or 30.0)
            replace_existing = payload.get("replace_existing", False)
            if isinstance(replace_existing, str):
                replace_existing = replace_existing.strip().lower() in {"1", "true", "yes", "on"}
            # 这一操作只在用户点击后运行，且分段工具延迟加载重依赖；避免占用回复链路。
            song = export_delivery_segments(
                source,
                title,
                target_seconds=target_seconds,
                replace_existing=bool(replace_existing),
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except subprocess.TimeoutExpired:
            return self._send_error(HTTPStatus.GATEWAY_TIMEOUT, "歌曲分段超时，原文件未发布")
        except subprocess.CalledProcessError as exc:
            return self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"歌曲片段导出失败（ffmpeg 退出码 {exc.returncode}）；旧片段未被覆盖",
            )
        except Exception as exc:
            LOGGER.exception("完整音乐分段失败")
            return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"歌曲分段失败：{exc}")
        self._send_json(
            {
                "ok": True,
                "title": song.title,
                "segments": len(song.segments),
                "path": str(song.directory),
                "replace_existing": bool(replace_existing),
            },
            status=HTTPStatus.CREATED,
        )

    def _handle_music_project_create(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            result = _music_bridge_request("/api/projects", "POST", payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result, status=HTTPStatus.CREATED)

    def _handle_music_project_stems(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        request_limit = MAX_MUSIC_STEM_UPLOAD_BYTES * 3 + 600_000
        if content_length <= 0 or content_length > request_limit:
            return self._send_error(
                HTTPStatus.BAD_REQUEST,
                "分离音频请求过大，单条主唱/和声/伴奏文件上限为 150MB",
            )
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            project_id = _valid_singing_job_id(multipart_text(form, "id"))
            target_dir = MUSIC_IMPORT_ROOT / project_id
            target_dir.mkdir(parents=True, exist_ok=True)
            paths: dict[str, str] = {}
            for field, label, required in (
                ("vocal", "主唱", True),
                ("instrumental", "伴奏", True),
                ("harmony", "和声", False),
            ):
                file_item = multipart_file(form, field)
                if file_item is None or not file_item.filename:
                    if required:
                        raise ValueError(f"请选择{label}音频文件")
                    continue
                if len(file_item.data) > MAX_MUSIC_STEM_UPLOAD_BYTES:
                    raise ValueError(f"{label}音频超过 150MB 上限")
                filename = safe_filename(str(file_item.filename))
                suffix = Path(filename).suffix.lower()
                if suffix not in AUDIO_EXTENSIONS:
                    raise ValueError(f"{label}仅支持 WAV、FLAC、MP3、OGG、M4A、AAC")
                target = unique_path(target_dir / f"{field}-{filename}")
                target.write_bytes(file_item.data)
                paths[f"{field}_path"] = str(target.resolve())
            result = _music_bridge_request(
                f"/api/projects/{project_id}/stems",
                "POST",
                paths,
                timeout=300,
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)


