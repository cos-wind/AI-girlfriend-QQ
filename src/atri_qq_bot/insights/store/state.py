from __future__ import annotations

from pathlib import Path

from .support import InsightsStoreMixin


class StateMixin(InsightsStoreMixin):
    def __init__(self, path: str | Path, log_root: str | Path | None = None) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 日志目录默认为项目根目录；测试和迁移工具可传入独立目录。
        from atri_runtime import user_root
        self.log_root = Path(log_root).expanduser().resolve() if log_root else user_root()
        # 仅主程序的 data/insights 数据库自动回填；测试临时库不会意外吸收工作区日志。
        self._sync_logs_enabled = log_root is not None or self.path.parent.name.lower() == "insights"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=8.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=8000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    group_id TEXT NOT NULL DEFAULT '',
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'system',
                    model_type TEXT NOT NULL DEFAULT 'chat',
                    model_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    semantic_similarity REAL,
                    overall_score REAL,
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    judge_model TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_evaluations_created ON evaluations(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_evaluations_status ON evaluations(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_evaluations_conversation ON evaluations(conversation_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS evaluation_scores (
                    evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
                    dimension TEXT NOT NULL,
                    score REAL,
                    reason TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (evaluation_id, dimension)
                );
                CREATE INDEX IF NOT EXISTS idx_scores_dimension ON evaluation_scores(dimension, score);

                CREATE TABLE IF NOT EXISTS group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_key TEXT NOT NULL UNIQUE,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    nickname TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'text',
                    media_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_group_messages_range ON group_messages(group_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_group_messages_user ON group_messages(group_id, user_id, created_at);

                CREATE TABLE IF NOT EXISTS group_summaries (
                    id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    period_type TEXT NOT NULL DEFAULT 'custom',
                    period_key TEXT NOT NULL DEFAULT '',
                    period_label TEXT NOT NULL DEFAULT '',
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    progress_stage TEXT NOT NULL DEFAULT '已排队',
                    progress_detail TEXT NOT NULL DEFAULT '',
                    progress_updated_at TEXT NOT NULL DEFAULT '',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    topics_json TEXT NOT NULL DEFAULT '[]',
                    key_points_json TEXT NOT NULL DEFAULT '[]',
                    statistics_json TEXT NOT NULL DEFAULT '{}',
                    content TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_summaries_group ON group_summaries(group_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_summaries_status ON group_summaries(status, created_at);
                CREATE TABLE IF NOT EXISTS group_names (
                    group_id TEXT PRIMARY KEY,
                    group_name TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS group_summary_schedules (
                    group_id TEXT PRIMARY KEY,
                    daily_enabled INTEGER NOT NULL DEFAULT 0,
                    daily_time TEXT NOT NULL DEFAULT '00:10',
                    daily_next_at TEXT NOT NULL DEFAULT '',
                    daily_last_sent_at TEXT NOT NULL DEFAULT '',
                    weekly_enabled INTEGER NOT NULL DEFAULT 0,
                    weekly_time TEXT NOT NULL DEFAULT '00:10',
                    weekly_next_at TEXT NOT NULL DEFAULT '',
                    weekly_last_sent_at TEXT NOT NULL DEFAULT '',
                    monthly_enabled INTEGER NOT NULL DEFAULT 0,
                    monthly_time TEXT NOT NULL DEFAULT '00:10',
                    monthly_next_at TEXT NOT NULL DEFAULT '',
                    monthly_last_sent_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summary_schedule_daily ON group_summary_schedules(daily_enabled, daily_time);
                CREATE INDEX IF NOT EXISTS idx_summary_schedule_weekly ON group_summary_schedules(weekly_enabled, weekly_time);
                CREATE INDEX IF NOT EXISTS idx_summary_schedule_monthly ON group_summary_schedules(monthly_enabled, monthly_time);
                CREATE TABLE IF NOT EXISTS message_delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    message_type TEXT NOT NULL DEFAULT '',
                    message_kind TEXT NOT NULL DEFAULT 'text',
                    model_type TEXT NOT NULL DEFAULT 'chat',
                    model_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_delivery_created ON message_delivery_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_delivery_model ON message_delivery_events(model_type, status, created_at DESC);
                """
            )
            # 旧版本数据库没有周期字段；逐列迁移，避免破坏已有总结记录。
            schedule_columns = {
                str(row[1])
                for row in db.execute("PRAGMA table_info(group_summary_schedules)").fetchall()
            }
            for column in (
                "daily_next_at", "daily_last_sent_at", "weekly_next_at", "weekly_last_sent_at",
                "monthly_next_at", "monthly_last_sent_at",
            ):
                if column not in schedule_columns:
                    db.execute(
                        f"ALTER TABLE group_summary_schedules ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )
            db.execute("CREATE INDEX IF NOT EXISTS idx_summary_schedule_daily_next ON group_summary_schedules(daily_enabled, daily_next_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_summary_schedule_weekly_next ON group_summary_schedules(weekly_enabled, weekly_next_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_summary_schedule_monthly_next ON group_summary_schedules(monthly_enabled, monthly_next_at)")
            summary_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(group_summaries)").fetchall()}
            for column, definition in (
                ("period_type", "TEXT NOT NULL DEFAULT 'custom'"),
                ("period_key", "TEXT NOT NULL DEFAULT ''"),
                ("period_label", "TEXT NOT NULL DEFAULT ''"),
                ("progress_percent", "INTEGER NOT NULL DEFAULT 0"),
                ("progress_stage", "TEXT NOT NULL DEFAULT '已排队'"),
                ("progress_detail", "TEXT NOT NULL DEFAULT ''"),
                ("progress_updated_at", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in summary_columns:
                    db.execute(f"ALTER TABLE group_summaries ADD COLUMN {column} {definition}")
            # 兼容功能上线前已经存在的 SQLite 文件。
            columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(evaluations)").fetchall()}
            if "source" not in columns:
                db.execute("ALTER TABLE evaluations ADD COLUMN source TEXT NOT NULL DEFAULT 'system'")
            if "model_type" not in columns:
                db.execute("ALTER TABLE evaluations ADD COLUMN model_type TEXT NOT NULL DEFAULT 'chat'")
            if "model_name" not in columns:
                db.execute("ALTER TABLE evaluations ADD COLUMN model_name TEXT NOT NULL DEFAULT ''")
            message_columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(group_messages)").fetchall()}
            if "media_json" not in message_columns:
                db.execute("ALTER TABLE group_messages ADD COLUMN media_json TEXT NOT NULL DEFAULT '[]'")
            db.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_model_type ON evaluations(model_type, created_at DESC)")
            # 日志回填会重复执行，事件 ID 必须幂等。清理极旧版本可能产生的重复行后再建唯一索引。
            db.execute(
                """DELETE FROM message_delivery_events
                WHERE id NOT IN (SELECT MIN(id) FROM message_delivery_events GROUP BY event_id)"""
            )
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_event_unique ON message_delivery_events(event_id)")
