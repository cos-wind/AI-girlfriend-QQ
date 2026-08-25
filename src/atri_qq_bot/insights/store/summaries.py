from __future__ import annotations

from .support import InsightsStoreMixin


class SummariesMixin(InsightsStoreMixin):
    def group_messages(self, group_id: str, start: str, end: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT group_id,user_id,nickname,content,message_type,media_json,created_at
                FROM group_messages WHERE group_id=? AND created_at>=? AND created_at<?
                ORDER BY created_at LIMIT ?""",
                (str(group_id), str(start), str(end), max(1, min(20000, int(limit)))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["media"] = _loads(item.pop("media_json", "[]"), [])
            result.append(item)
        return result

    def create_summary(
        self,
        group_id: str,
        start: str,
        end: str,
        trigger_type: str,
        period_type: str = "custom",
        period_key: str = "",
        period_label: str = "",
    ) -> str:
        summary_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """INSERT INTO group_summaries
                (id,group_id,period_start,period_end,trigger_type,period_type,period_key,period_label,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    summary_id, str(group_id), str(start), str(end), str(trigger_type),
                    str(period_type or "custom"), str(period_key or ""), str(period_label or ""), utc_now(),
                ),
            )
        return summary_id

    def mark_summary_running(self, summary_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE group_summaries SET status='running', error='' WHERE id=?", (summary_id,))

    def complete_summary(
        self,
        summary_id: str,
        *,
        title: str,
        message_count: int,
        topics: list[dict[str, Any]],
        key_points: list[str],
        statistics: dict[str, Any],
        content: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE group_summaries SET status='completed', title=?, message_count=?,
                topics_json=?, key_points_json=?, statistics_json=?, content=?, error='', completed_at=?
                WHERE id=?""",
                (
                    str(title)[:300], int(message_count), _json(topics), _json(key_points),
                    _json(statistics), str(content)[:100000], utc_now(), summary_id,
                ),
            )

    def fail_summary(self, summary_id: str, error: str, message_count: int = 0) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE group_summaries SET status='failed', error=?, message_count=?,
                completed_at=? WHERE id=?""",
                (str(error)[:3000], int(message_count), utc_now(), summary_id),
            )

    def list_summaries(self, group_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        where = " WHERE group_id=?" if group_id else ""
        params: list[Any] = [group_id] if group_id else []
        params.append(max(1, min(500, int(limit))))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM group_summaries{where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._summary_row(row, detail=False) for row in rows]

    def summary_detail(self, summary_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM group_summaries WHERE id=?", (summary_id,)).fetchone()
        return self._summary_row(row, detail=True) if row else None

    @staticmethod
    def _summary_row(row: sqlite3.Row, *, detail: bool) -> dict[str, Any]:
        item = dict(row)
        item["topics"] = _loads(item.pop("topics_json", "[]"), [])
        item["key_points"] = _loads(item.pop("key_points_json", "[]"), [])
        item["statistics"] = _loads(item.pop("statistics_json", "{}"), {})
        if not detail:
            item["content"] = str(item.get("content") or "")[:500]
        return item

    def scheduled_summary_exists(
        self, group_id: str, period_type: str, period_key: str, end: str | None = None
    ) -> bool:
        with self._connect() as db:
            if end is None:
                row = db.execute(
                    """SELECT 1 FROM group_summaries WHERE group_id=? AND period_type=?
                    AND period_key=? AND trigger_type='scheduled' LIMIT 1""",
                    (str(group_id), str(period_type), str(period_key)),
                ).fetchone()
            else:
                # 兼容旧调度器调用方式（start, end）。
                row = db.execute(
                    """SELECT 1 FROM group_summaries WHERE group_id=? AND period_start=?
                    AND period_end=? AND trigger_type='scheduled' LIMIT 1""",
                    (str(group_id), str(period_type), str(period_key)),
                ).fetchone()
        return row is not None
