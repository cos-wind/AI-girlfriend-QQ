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
            db.execute(
                """UPDATE group_summaries SET status='running', error='', progress_percent=5,
                progress_stage='准备生成', progress_detail='正在准备本次总结任务', progress_updated_at=? WHERE id=?""",
                (utc_now(), summary_id),
            )

    def update_summary_progress(
        self, summary_id: str, percent: int, stage: str, detail: str = ""
    ) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE group_summaries SET progress_percent=?, progress_stage=?,
                progress_detail=?, progress_updated_at=? WHERE id=? AND status='running'""",
                (max(0, min(99, int(percent))), str(stage)[:80], str(detail)[:500], utc_now(), summary_id),
            )

    def recover_interrupted_summaries(self) -> int:
        """将进程退出时遗留的任务标记为可见失败，避免页面永久“生成中”。"""
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE group_summaries SET status='failed', progress_stage='已中断',
                progress_detail='ATRI 重启前任务未完成，请重新生成。',
                error=CASE WHEN error='' THEN 'ATRI 重启前任务未完成，请重新生成。' ELSE error END,
                completed_at=?, progress_updated_at=? WHERE status IN ('queued','running')""",
                (utc_now(), utc_now()),
            )
        return int(cursor.rowcount or 0)

    def save_summary_report(
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
                """UPDATE group_summaries SET title=?, message_count=?, topics_json=?,
                key_points_json=?, statistics_json=?, content=?, error='' WHERE id=?""",
                (
                    str(title)[:300], int(message_count), _json(topics), _json(key_points),
                    _json(statistics), str(content)[:100000], summary_id,
                ),
            )

    def finish_summary(self, summary_id: str) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE group_summaries SET status='completed', error='', progress_percent=100,
                progress_stage='已完成', progress_detail='日报已生成', completed_at=?, progress_updated_at=? WHERE id=?""",
                (utc_now(), utc_now(), summary_id),
            )

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
        self.save_summary_report(
            summary_id, title=title, message_count=message_count, topics=topics,
            key_points=key_points, statistics=statistics, content=content,
        )
        self.finish_summary(summary_id)

    def fail_summary(self, summary_id: str, error: str, message_count: int = 0) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE group_summaries SET status='failed', error=?, message_count=?,
                progress_stage='失败', progress_detail=?, completed_at=?, progress_updated_at=? WHERE id=?""",
                (str(error)[:3000], int(message_count), str(error)[:500], utc_now(), utc_now(), summary_id),
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
        # 兼容进度字段上线前已生成的报告：它们没有阶段信息，但完成/失败状态
        # 仍应在时间轴上正确呈现，而不是显示默认“已排队”。
        if not str(item.get("progress_stage") or "").strip() or (
            str(item.get("progress_stage")) == "已排队" and str(item.get("status")) != "queued"
        ):
            item["progress_stage"] = "已完成" if item.get("status") == "completed" else (
                "失败" if item.get("status") == "failed" else str(item.get("status") or "已排队")
            )
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
