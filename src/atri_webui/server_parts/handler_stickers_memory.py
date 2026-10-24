from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerStickersMemoryMixin(WebUIHandlerMixin):
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
        # 只读检视模式下不写记忆：写路径永远落在"正在运行的那个账号"上，
        # 否则"切到 X 看数据"会变成"改到 X 的数据"。
        if self._refuse_when_read_only("保存记忆"):
            return
        payload = self._read_json()
        conversation_id = str((payload or {}).get("id") or "")
        content = (payload or {}).get("content")
        if not conversation_id or not isinstance(content, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "参数不完整")
        try:
            backup = self.webui_state.running_memory_admin().save_conversation(
                conversation_id, content
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "backup": str(backup)})

    def _handle_memory_relationship(self) -> None:
        if self._refuse_when_read_only("修改关系设置"):
            return
        payload = self._read_json()
        conversation_id = str((payload or {}).get("id") or "")
        if not conversation_id:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少会话 id")
        try:
            backup, relationship = self.webui_state.running_memory_admin().update_relationship(
                conversation_id,
                (payload or {}).get("affection_score"),
                (payload or {}).get("proactive_override"),
                (payload or {}).get("group_activity_score"),
                (payload or {}).get("trust_tier"),
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {"ok": True, "backup": str(backup), "relationship": relationship}
        )

    def _handle_memory_delete(self) -> None:
        if self._refuse_when_read_only("删除记忆"):
            return
        payload = self._read_json()
        conversation_id = str((payload or {}).get("id") or "")
        if not conversation_id:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少会话 id")
        try:
            backup = self.webui_state.running_memory_admin().delete_conversation(conversation_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "backup": str(backup)})


