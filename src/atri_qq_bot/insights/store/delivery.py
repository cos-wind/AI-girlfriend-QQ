from __future__ import annotations

from .support import InsightsStoreMixin


class DeliveryMixin(InsightsStoreMixin):
    def record_delivery(
        self,
        *,
        event_id: str,
        conversation_id: str = "",
        group_id: str = "",
        message_type: str = "",
        message_kind: str = "text",
        model_type: str = "chat",
        model_name: str = "",
        status: str = "success",
        error: str = "",
        created_at: str | None = None,
    ) -> None:
        """记录一次 OneBot 消息发送尝试，供 WebUI 统计成功/失败。"""
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO message_delivery_events
                (event_id, conversation_id, group_id, message_type, message_kind,
                 model_type, model_name, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(event_id or "")[:160],
                    str(conversation_id or "")[:160],
                    str(group_id or "")[:80],
                    str(message_type or "")[:30],
                    str(message_kind or "text")[:30],
                    str(model_type or "chat")[:20],
                    str(model_name or "")[:160],
                    "success" if str(status) == "success" else "failed",
                    str(error or "")[:500],
                    str(created_at or utc_now()),
                ),
            )

    @staticmethod
    def _parse_log_time(value: Any) -> tuple[str, float] | None:
        """解析 ATRI 日志时间，返回 SQLite 可比较文本和 Unix 时间戳。"""
        text = str(value or "").strip()
        if not text:
            return None
        candidate = text.replace("Z", "+00:00")
        parsed: datetime | None = None
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            # ATRI 日志使用本地时间；转成带本地时区的时间戳用于窗口过滤。
            parsed = parsed.astimezone()
        else:
            parsed = parsed.astimezone()
        # 保留时区，SQLite 的 datetime() 才能和 UTC 的窗口边界准确比较。
        normalized = parsed.isoformat(timespec="seconds")
        return normalized, parsed.timestamp()

    @staticmethod
    def _log_event_id(prefix: str, raw_line: str) -> str:
        digest = hashlib.sha256(raw_line.encode("utf-8", errors="replace")).hexdigest()
        return f"log:{prefix}:{digest}"

    @staticmethod
    def _is_visual_reply(item: dict[str, Any]) -> bool:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("user_text", "material_read_level", "reply_focus_source", "reply_focus_text")
        ).lower()
        markers = ("图片", "图像", "截图", "照片", "表情包", "动画表情", "视觉", "image", "video")
        return any(marker in text for marker in markers)

    def sync_recent_delivery_logs(self, days: int = 2) -> int:
        """把最近日志中的实际发送结果幂等回填到消息投递统计表。

        回复日志是主来源；语音日志仅补充回复日志之外的语音发送结果，
        合成失败、视觉模型分析成功等非发送事件不会被计入。
        """
        safe_days = max(1, min(30, int(days)))
        cutoff = datetime.now().astimezone().timestamp() - safe_days * 86400
        rows: list[tuple[Any, ...]] = []

        def read_jsonl(path: Path, prefix: str) -> list[tuple[dict[str, Any], str]]:
            if not path.exists():
                return []
            result: list[tuple[dict[str, Any], str]] = []
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for raw in handle:
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            value = json.loads(line)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if not isinstance(value, dict):
                            continue
                        parsed = self._parse_log_time(value.get("time"))
                        if parsed and parsed[1] >= cutoff:
                            result.append((value, self._log_event_id(prefix, line)))
            except OSError:
                return []
            return result

        reply_records = read_jsonl(self.log_root / "logs" / "reply-events.jsonl", "reply")
        for item, event_id in reply_records:
            parsed = self._parse_log_time(item.get("time"))
            if not parsed:
                continue
            raw_status = str(item.get("status") or "").lower()
            if raw_status not in {"delivered", "failed", "delivery_failed", "send_failed"}:
                continue
            model_type = "voice" if str(item.get("voice_mode") or "").strip() else (
                "vision" if self._is_visual_reply(item) else "chat"
            )
            status = "success" if raw_status == "delivered" else "failed"
            rows.append((
                event_id,
                str(item.get("conversation_id") or ""),
                str(item.get("group_id") or ""),
                str(item.get("message_type") or ""),
                "voice" if model_type == "voice" else ("vision" if model_type == "vision" else "text"),
                model_type,
                "",
                status,
                str(item.get("failure_reason") or ""),
                parsed[0],
            ))

        # 语音事件包括说唱/主动语音等不一定有 reply-events 记录的发送。
        voice_records = read_jsonl(self.log_root / "logs" / "voice-events.log", "voice")
        for item, event_id in voice_records:
            raw_status = str(item.get("status") or "").lower()
            if raw_status not in {"delivered", "delivery_failed", "send_failed", "failed"}:
                continue
            parsed = self._parse_log_time(item.get("time"))
            if not parsed:
                continue
            conversation_id = str(item.get("conversation_id") or "")
            if not conversation_id:
                message_type = str(item.get("message_type") or "")
                user_id = str(item.get("user_id") or "")
                group_id = str(item.get("group_id") or "")
                conversation_id = f"{message_type}:{group_id or user_id}".strip(":")
            rows.append((
                event_id,
                conversation_id,
                str(item.get("group_id") or ""),
                str(item.get("message_type") or ""),
                "voice",
                "voice",
                str(item.get("model") or ""),
                "success" if raw_status == "delivered" else "failed",
                str(item.get("error") or ""),
                parsed[0],
            ))

        if not rows:
            return 0
        with self._connect() as db:
            before = int(db.execute("SELECT COUNT(*) FROM message_delivery_events").fetchone()[0] or 0)
            db.executemany(
                """INSERT OR IGNORE INTO message_delivery_events
                (event_id, conversation_id, group_id, message_type, message_kind,
                 model_type, model_name, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            after = int(db.execute("SELECT COUNT(*) FROM message_delivery_events").fetchone()[0] or 0)
        return max(0, after - before)

    def delivery_dashboard(self, days: int = 30, model_type: str = "") -> dict[str, Any]:
        safe_days = max(1, min(3650, int(days)))
        synced = self.sync_recent_delivery_logs(min(2, safe_days)) if self._sync_logs_enabled else 0
        modifier = f"-{safe_days} days"
        clause = " AND model_type=?" if model_type in {"chat", "vision", "voice"} else ""
        params: tuple[Any, ...] = (modifier, model_type) if clause else (modifier,)
        with self._connect() as db:
            total = db.execute(
                f"""SELECT COUNT(*) FROM message_delivery_events
                WHERE datetime(created_at)>=datetime('now', ?){clause}""",
                params,
            ).fetchone()[0]
            rows = db.execute(
                f"""SELECT model_type,
                    COUNT(*) AS total,
                    SUM(status='success') AS success,
                    SUM(status='failed') AS failed
                FROM message_delivery_events
                WHERE datetime(created_at)>=datetime('now', ?){clause}
                GROUP BY model_type ORDER BY model_type""",
                params,
            ).fetchall()
            counts = db.execute(
                f"""SELECT SUM(status='success') AS success, SUM(status='failed') AS failed
                FROM message_delivery_events
                WHERE datetime(created_at)>=datetime('now', ?){clause}""",
                params,
            ).fetchone()
        return {
            "total": int(total or 0),
            "success": int((counts["success"] if counts else 0) or 0),
            "failed": int((counts["failed"] if counts else 0) or 0),
            "by_model": [dict(row) for row in rows],
            "synced": synced,
        }
