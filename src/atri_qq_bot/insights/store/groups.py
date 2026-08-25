from __future__ import annotations

from .support import InsightsStoreMixin


class GroupsMixin(InsightsStoreMixin):
    def add_group_message(
        self,
        *,
        message_key: str,
        group_id: str,
        user_id: str,
        nickname: str,
        content: str,
        message_type: str,
        created_at: str,
        media: list[dict[str, Any]] | None = None,
    ) -> bool:
        if not group_id or not content.strip():
            return False
        with self._connect() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO group_messages
                (message_key, group_id, user_id, nickname, content, message_type, media_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(message_key), str(group_id), str(user_id), str(nickname)[:200],
                    str(content)[:8000], str(message_type)[:40], _json(media or [])[:12000], str(created_at),
                ),
            )
        return cursor.rowcount > 0

    def group_ids(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT g.group_id, COALESCE(n.group_name, '') AS group_name,
                COUNT(*) AS messages, MAX(g.created_at) AS last_message_at
                FROM group_messages g LEFT JOIN group_names n ON n.group_id=g.group_id
                GROUP BY g.group_id, n.group_name ORDER BY last_message_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def set_group_name(self, group_id: str, group_name: str) -> None:
        group_id = str(group_id or "").strip()
        group_name = str(group_name or "").strip()[:200]
        if not group_id or not group_name:
            return
        with self._connect() as db:
            db.execute(
                """INSERT INTO group_names(group_id,group_name,updated_at) VALUES(?,?,?)
                ON CONFLICT(group_id) DO UPDATE SET group_name=excluded.group_name, updated_at=excluded.updated_at""",
                (group_id, group_name, utc_now()),
            )

    def group_name_map(self) -> dict[str, str]:
        with self._connect() as db:
            rows = db.execute("SELECT group_id, group_name FROM group_names WHERE group_name!=''").fetchall()
        return {str(row["group_id"]): str(row["group_name"]) for row in rows}

    def known_users(self, limit: int = 500) -> list[dict[str, Any]]:
        """返回已归档群消息中的 QQ 用户，供 WebUI 白名单选择。

        只读现有归档数据，不额外请求 QQ；用户也可以在 WebUI 中手动添加
        尚未发言或尚未被归档的 QQ 号。
        """
        safe_limit = max(1, min(2000, int(limit)))
        with self._connect() as db:
            rows = db.execute(
                """SELECT user_id, MAX(nickname) AS name, COUNT(*) AS messages,
                MAX(created_at) AS last_message_at
                FROM group_messages WHERE user_id!=''
                GROUP BY user_id ORDER BY last_message_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [
            {
                "user_id": str(row["user_id"]),
                "name": str(row["name"] or ""),
                "messages": int(row["messages"] or 0),
                "last_message_at": str(row["last_message_at"] or ""),
            }
            for row in rows
        ]

    def group_summary_schedules(self) -> list[dict[str, Any]]:
        """返回全部已归档群聊的独立日报/周报/月报计划。"""
        with self._connect() as db:
            rows = db.execute(
                """WITH groups AS (
                    SELECT group_id, COUNT(*) AS messages, MAX(created_at) AS last_message_at
                    FROM group_messages GROUP BY group_id
                    UNION ALL
                    SELECT n.group_id, 0 AS messages, '' AS last_message_at
                    FROM group_names n
                    WHERE NOT EXISTS (SELECT 1 FROM group_messages g0 WHERE g0.group_id=n.group_id)
                )
                SELECT g.group_id, COALESCE(n.group_name, '') AS group_name,
                g.messages, g.last_message_at,
                COALESCE(s.daily_enabled, 0) AS daily_enabled,
                COALESCE(s.daily_time, '00:10') AS daily_time,
                COALESCE(s.daily_next_at, '') AS daily_next_at,
                COALESCE(s.daily_last_sent_at, '') AS daily_last_sent_at,
                COALESCE(s.weekly_enabled, 0) AS weekly_enabled,
                COALESCE(s.weekly_time, '00:10') AS weekly_time,
                COALESCE(s.weekly_next_at, '') AS weekly_next_at,
                COALESCE(s.weekly_last_sent_at, '') AS weekly_last_sent_at,
                COALESCE(s.monthly_enabled, 0) AS monthly_enabled,
                COALESCE(s.monthly_time, '00:10') AS monthly_time,
                COALESCE(s.monthly_next_at, '') AS monthly_next_at,
                COALESCE(s.monthly_last_sent_at, '') AS monthly_last_sent_at,
                s.updated_at AS schedule_updated_at
                FROM groups g
                LEFT JOIN group_names n ON n.group_id=g.group_id
                LEFT JOIN group_summary_schedules s ON s.group_id=g.group_id
                GROUP BY g.group_id, n.group_name, g.messages, g.last_message_at,
                s.daily_enabled, s.daily_time, s.weekly_enabled, s.weekly_time,
                s.monthly_enabled, s.monthly_time, s.updated_at
                ORDER BY last_message_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def save_group_summary_schedule(
        self,
        group_id: str,
        *,
        daily_enabled: bool,
        daily_time: str,
        weekly_enabled: bool,
        weekly_time: str,
        monthly_enabled: bool,
        monthly_time: str,
        daily_next_at: str = "",
        weekly_next_at: str = "",
        monthly_next_at: str = "",
    ) -> None:
        """保存单个群聊的三种报告计划；时间由 WebUI 传入 HH:MM。"""
        group_id = str(group_id or "").strip()
        if not group_id:
            raise ValueError("群号不能为空")
        with self._connect() as db:
            db.execute(
                """INSERT INTO group_summary_schedules
                (group_id,daily_enabled,daily_time,daily_next_at,daily_last_sent_at,
                 weekly_enabled,weekly_time,weekly_next_at,weekly_last_sent_at,
                 monthly_enabled,monthly_time,monthly_next_at,monthly_last_sent_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(group_id) DO UPDATE SET
                daily_enabled=excluded.daily_enabled,daily_time=excluded.daily_time,
                daily_next_at=excluded.daily_next_at,
                weekly_enabled=excluded.weekly_enabled,weekly_time=excluded.weekly_time,
                weekly_next_at=excluded.weekly_next_at,
                monthly_enabled=excluded.monthly_enabled,monthly_time=excluded.monthly_time,
                monthly_next_at=excluded.monthly_next_at,
                updated_at=excluded.updated_at""",
                (
                    group_id, int(bool(daily_enabled)), str(daily_time), str(daily_next_at or ""), "",
                    int(bool(weekly_enabled)), str(weekly_time), str(weekly_next_at or ""), "",
                    int(bool(monthly_enabled)), str(monthly_time), str(monthly_next_at or ""), "", utc_now(),
                ),
            )

    def due_group_summary_schedules(self, now_text: str) -> list[dict[str, Any]]:
        """查询下一次执行时间已到的计划，每个群的每个周期独立返回。"""
        with self._connect() as db:
            rows = db.execute(
                """SELECT group_id, 'daily' AS period_type FROM group_summary_schedules
                WHERE daily_enabled=1 AND daily_next_at!='' AND daily_next_at<=?
                UNION ALL
                SELECT group_id, 'weekly' AS period_type FROM group_summary_schedules
                WHERE weekly_enabled=1 AND weekly_next_at!='' AND weekly_next_at<=?
                UNION ALL
                SELECT group_id, 'monthly' AS period_type FROM group_summary_schedules
                WHERE monthly_enabled=1 AND monthly_next_at!='' AND monthly_next_at<=?""",
                (str(now_text), str(now_text), str(now_text)),
            ).fetchall()
        return [dict(row) for row in rows]

    def advance_group_summary_schedule(
        self, group_id: str, period_type: str, next_at: str
    ) -> None:
        """领取一次到期计划并写入下一次时间，避免服务重启或长任务重复提交。"""
        column = {
            "daily": "daily_next_at",
            "weekly": "weekly_next_at",
            "monthly": "monthly_next_at",
        }.get(str(period_type or "").lower())
        if not column:
            raise ValueError("无效的总结周期")
        with self._connect() as db:
            db.execute(
                f"UPDATE group_summary_schedules SET {column}=?, updated_at=? WHERE group_id=?",
                (str(next_at), utc_now(), str(group_id)),
            )

    def mark_group_summary_schedule_sent(
        self, group_id: str, period_type: str, sent_at: str
    ) -> None:
        """记录最近一次成功自动发送时间，供 WebUI 详情展示。"""
        column = {
            "daily": "daily_last_sent_at",
            "weekly": "weekly_last_sent_at",
            "monthly": "monthly_last_sent_at",
        }.get(str(period_type or "").lower())
        if not column:
            raise ValueError("无效的总结周期")
        interval_days = {"daily": 1, "weekly": 7, "monthly": 30}[str(period_type).lower()]
        sent_text = str(sent_at)
        try:
            next_text = (
                datetime.fromisoformat(sent_text) + timedelta(days=interval_days)
            ).isoformat(timespec="minutes")
        except ValueError:
            next_text = sent_text
        next_column = f"{str(period_type).lower()}_next_at"
        with self._connect() as db:
            db.execute(
                f"UPDATE group_summary_schedules SET {column}=?, {next_column}=?, updated_at=? WHERE group_id=?",
                (sent_text, next_text, utc_now(), str(group_id)),
            )
