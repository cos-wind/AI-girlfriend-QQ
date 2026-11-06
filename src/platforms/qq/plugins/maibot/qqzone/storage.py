from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class QQZoneRepository:
    """插件私有 SQLite 存储；每次操作使用短连接，兼容 asyncio.to_thread。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS feed_cache (
                    owner_uin TEXT NOT NULL,
                    tid TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    PRIMARY KEY (owner_uin, tid)
                );
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    owner_uin TEXT NOT NULL DEFAULT '',
                    tid TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'webui',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    mood TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    context_excerpt TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    tid TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    published_at REAL
                );
                CREATE TABLE IF NOT EXISTS plugin_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_action_log_created_at ON action_log(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_action_log_action_status ON action_log(action, status, created_at);
                """
            )

    def cache_feeds(self, feeds: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            for feed in feeds:
                owner = str(feed.get("user_id") or "")
                tid = str(feed.get("tid") or "")
                if not tid:
                    continue
                db.execute(
                    """
                    INSERT INTO feed_cache(owner_uin, tid, payload_json, fetched_at)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(owner_uin, tid) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        fetched_at=excluded.fetched_at
                    """,
                    (owner, tid, json.dumps(feed, ensure_ascii=False), now),
                )

    def find_feed(self, user_id: str, tid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM feed_cache WHERE owner_uin=? AND tid=?",
                (str(user_id), str(tid)),
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def record_action(
        self,
        action: str,
        *,
        owner_uin: str = "",
        tid: str = "",
        content: str = "",
        source: str = "webui",
        status: str = "success",
        error: str = "",
    ) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO action_log(action, owner_uin, tid, content, source, status, error, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (action, owner_uin, tid, content, source, status, error, time.time()),
            )
            return int(cursor.lastrowid)

    def recent_actions(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM action_log ORDER BY created_at DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_success_today(self, action: str) -> int:
        local = time.localtime()
        start = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM action_log WHERE action=? AND status='success' AND created_at>=?",
                (action, start),
            ).fetchone()
        return int(row["count"] if row else 0)

    def has_successful_action(self, action: str, tid: str) -> bool:
        """Return whether an action was already completed for this feed."""
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM action_log WHERE action=? AND tid=? AND status='success' LIMIT 1",
                (str(action), str(tid)),
            ).fetchone()
        return row is not None

    def create_draft(self, content: str, mood: str, topic: str, context_excerpt: str) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO drafts(content, mood, topic, context_excerpt, status, created_at)
                VALUES(?, ?, ?, ?, 'draft', ?)
                """,
                (content, mood, topic, context_excerpt, time.time()),
            )
            return int(cursor.lastrowid)

    def get_draft(self, draft_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (int(draft_id),)).fetchone()
        return dict(row) if row else None

    def mark_draft_published(self, draft_id: int, tid: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE drafts SET status='published', tid=?, published_at=? WHERE id=?",
                (str(tid), time.time(), int(draft_id)),
            )

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO plugin_state(key, value, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, time.time()),
            )

    def get_state(self, key: str, default: str = "") -> str:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT value FROM plugin_state WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default
