from __future__ import annotations

from .support import QZoneMixin


class QZoneStoreMixin(QZoneMixin):
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path("data") / "qzone_automation.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS qzone_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS qzone_content_pool (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    model_profile_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    generated_at REAL,
                    scheduled_at REAL,
                    edited_at REAL,
                    published_at REAL,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS qzone_comment_pool (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    model_profile_id TEXT NOT NULL DEFAULT '',
                    source_tid TEXT NOT NULL DEFAULT '',
                    source_user_id TEXT NOT NULL DEFAULT '',
                    source_content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    generated_at REAL,
                    edited_at REAL,
                    used_at REAL,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS qzone_targets (
                    user_id TEXT PRIMARY KEY,
                    nickname TEXT NOT NULL DEFAULT '',
                    enabled_like INTEGER NOT NULL DEFAULT 1,
                    enabled_comment INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qzone_automation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    tid TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qzone_scheduler_lease (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    owner TEXT NOT NULL DEFAULT '',
                    expires_at REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS qzone_post_slots (
                    slot_key TEXT PRIMARY KEY,
                    claim_token TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claimed_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    published_at REAL,
                    tid TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_qzone_logs_created ON qzone_automation_logs(created_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_qzone_logs_success_tid
                  ON qzone_automation_logs(action, tid) WHERE status='success' AND tid <> '';
                """
            )
            # 兼容第一版已经创建的内容池数据库。
            for statement in (
                "ALTER TABLE qzone_content_pool ADD COLUMN prompt TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE qzone_content_pool ADD COLUMN model_profile_id TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE qzone_content_pool ADD COLUMN generated_at REAL",
                "ALTER TABLE qzone_content_pool ADD COLUMN scheduled_at REAL",
                "ALTER TABLE qzone_content_pool ADD COLUMN edited_at REAL",
                "ALTER TABLE qzone_comment_pool ADD COLUMN source_tid TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE qzone_comment_pool ADD COLUMN source_user_id TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE qzone_comment_pool ADD COLUMN source_content TEXT NOT NULL DEFAULT ''",
            ):
                try:
                    db.execute(statement)
                except sqlite3.OperationalError:
                    pass
            for key, value in DEFAULT_SETTINGS.items():
                db.execute(
                    "INSERT OR IGNORE INTO qzone_settings(key, value_json) VALUES(?, ?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            migrated = db.execute("SELECT 1 FROM qzone_settings WHERE key='comment_pool_v2_migrated'").fetchone()
            if migrated is None:
                db.execute("INSERT INTO qzone_settings(key, value_json) VALUES('comment_use_pool', 'true') ON CONFLICT(key) DO UPDATE SET value_json='true'")
                db.execute("INSERT INTO qzone_settings(key, value_json) VALUES('comment_pool_v2_migrated', 'true')")
            policy_migrated = db.execute("SELECT 1 FROM qzone_settings WHERE key='per_user_policy_v3_migrated'").fetchone()
            if policy_migrated is None:
                # Per-person switches are opt-in. Existing rows are reset once
                # so the new UI cannot silently start liking/commenting.
                db.execute("UPDATE qzone_targets SET enabled_like=0, enabled_comment=0")
                db.execute("INSERT INTO qzone_settings(key, value_json) VALUES('per_user_policy_v3_migrated', 'true')")
            diversity_migrated = db.execute("SELECT 1 FROM qzone_settings WHERE key='post_diversity_v5_migrated'").fetchone()
            if diversity_migrated is None:
                topic_row = db.execute("SELECT value_json FROM qzone_settings WHERE key='topic_rotation'").fetchone()
                try:
                    current_topics = json.loads(str(topic_row["value_json"] if topic_row else "[]"))
                except json.JSONDecodeError:
                    current_topics = []
                if not current_topics or current_topics == LEGACY_TOPIC_ROTATION:
                    db.execute(
                        "UPDATE qzone_settings SET value_json=? WHERE key='topic_rotation'",
                        (json.dumps(DEFAULT_TOPIC_ROTATION, ensure_ascii=False),),
                    )
                # Old generated drafts may contain facts admitted by the former
                # unfiltered Bing-Web path. Preserve manual drafts, but never
                # publish those generated drafts under the new policy.
                db.execute(
                    "UPDATE qzone_content_pool SET status='rejected',last_error='fact_source_policy_updated' "
                    "WHERE status='pending' AND generated_at IS NOT NULL"
                )
                db.execute("INSERT INTO qzone_settings(key,value_json) VALUES('post_diversity_v5_migrated','true')")

    def settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT key, value_json FROM qzone_settings").fetchall()
        result = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                key = str(row["key"])
                if key in DEFAULT_SETTINGS:
                    result[key] = json.loads(str(row["value_json"]))
            except json.JSONDecodeError:
                continue
        if not str(result.get("post_prompt") or "").strip():
            result["post_prompt"] = str(DEFAULT_SETTINGS["post_prompt"])
        return result

    def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        old_signature = str(current.get("schedule_signature") or "") or _schedule_signature(current)
        current.update({key: value for key, value in values.items() if key in DEFAULT_SETTINGS})
        if not str(current.get("post_prompt") or "").strip():
            current["post_prompt"] = str(DEFAULT_SETTINGS["post_prompt"])
        new_signature = _schedule_signature(current)
        # A timing edit is an explicit request to rebuild the schedule. Other
        # saves (like toggling a user interaction target) must preserve it.
        timing_keys = {"period_days", "posts_per_period", "post_start_hour", "post_end_hour", "timezone"}
        if old_signature and old_signature != new_signature and timing_keys.intersection(values):
            current["next_post_at"] = 0.0
            current["schedule_slots"] = []
            current["schedule_period_start"] = ""
        current["schedule_signature"] = new_signature
        with self._lock, self._connect() as db:
            for key, value in current.items():
                db.execute(
                    "INSERT INTO qzone_settings(key, value_json) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
        return current

    def acquire_scheduler_lease(self, owner: str, *, ttl: float = 90.0) -> bool:
        """Acquire a short SQLite lease so stale/duplicate app processes cannot post twice."""
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner, expires_at FROM qzone_scheduler_lease WHERE id=1").fetchone()
            if row and str(row["owner"] or "") and float(row["expires_at"] or 0) > now:
                return False
            db.execute(
                "INSERT INTO qzone_scheduler_lease(id,owner,expires_at) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at",
                (str(owner), now + max(30.0, float(ttl))),
            )
        return True

    def release_scheduler_lease(self, owner: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM qzone_scheduler_lease WHERE id=1 AND owner=?", (str(owner),))

    def claim_post_slot(self, slot_key: str, *, ttl: float = 1800.0) -> str:
        """Atomically reserve one automatic publication slot across processes."""
        now = time.time()
        token = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status, expires_at FROM qzone_post_slots WHERE slot_key=?",
                (str(slot_key),),
            ).fetchone()
            if row:
                status = str(row["status"] or "")
                # Once an external request may have started, automatic retry is
                # unsafe: a timeout can mean the post succeeded but its reply
                # was lost. A later period receives a different slot key.
                if status in {"sending", "published", "uncertain"}:
                    return ""
                if float(row["expires_at"] or 0) > now:
                    return ""
            db.execute(
                "INSERT INTO qzone_post_slots(slot_key,claim_token,status,claimed_at,expires_at,published_at,tid) "
                "VALUES(?,?,'claimed',?,?,NULL,'') "
                "ON CONFLICT(slot_key) DO UPDATE SET claim_token=excluded.claim_token,status='claimed',"
                "claimed_at=excluded.claimed_at,expires_at=excluded.expires_at,published_at=NULL,tid=''",
                (str(slot_key), token, now, now + max(300.0, float(ttl))),
            )
        return token

    def begin_post_send(self, slot_key: str, claim_token: str) -> bool:
        """Make a claim non-retriable immediately before the external side effect."""
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE qzone_post_slots SET status='sending',expires_at=? "
                "WHERE slot_key=? AND claim_token=? AND status='claimed'",
                (time.time() + 86400.0, str(slot_key), str(claim_token)),
            )
        return int(cursor.rowcount or 0) == 1

    def complete_post_slot(self, slot_key: str, claim_token: str, tid: str = "") -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE qzone_post_slots SET status='published',published_at=?,expires_at=?,tid=? "
                "WHERE slot_key=? AND claim_token=? AND status='sending'",
                (now, now + 86400.0, str(tid), str(slot_key), str(claim_token)),
            )

    def finish_automatic_post(
        self,
        slot_key: str,
        claim_token: str,
        *,
        tid: str,
        content: str,
        content_id: int | None,
    ) -> None:
        """Persist the external success, pool state, and quota log atomically."""
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE qzone_post_slots SET status='published',published_at=?,expires_at=?,tid=? "
                "WHERE slot_key=? AND claim_token=? AND status='sending'",
                (now, now + 86400.0, str(tid), str(slot_key), str(claim_token)),
            )
            if int(cursor.rowcount or 0) != 1:
                raise RuntimeError("自动动态发布槽位状态已失效")
            if content_id is not None:
                db.execute(
                    "UPDATE qzone_content_pool SET status='published',published_at=?,last_error='' WHERE id=?",
                    (now, int(content_id)),
                )
            db.execute(
                "INSERT OR IGNORE INTO qzone_automation_logs(action,user_id,tid,content,status,error,created_at) "
                "VALUES('post','',?,?,'success','',?)",
                (str(tid), str(content), now),
            )

    def mark_post_slot_uncertain(self, slot_key: str, claim_token: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE qzone_post_slots SET status='uncertain',expires_at=? "
                "WHERE slot_key=? AND claim_token=? AND status='sending'",
                (time.time() + 86400.0, str(slot_key), str(claim_token)),
            )

    def release_post_slot(self, slot_key: str, claim_token: str) -> None:
        """Release only before send_msg begins, when retry is known to be safe."""
        with self._lock, self._connect() as db:
            db.execute(
                "DELETE FROM qzone_post_slots WHERE slot_key=? AND claim_token=? AND status='claimed'",
                (str(slot_key), str(claim_token)),
            )

    def content_list(self, include_published: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM qzone_content_pool"
        args: tuple[Any, ...] = ()
        if not include_published:
            query += " WHERE status='pending'"
        query += " ORDER BY id DESC"
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query, args).fetchall()]

    def content_add(self, content: str, *, prompt: str = "", model_profile_id: str = "", generated_at: float | None = None, scheduled_at: float | None = None) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text or len(text) > 1000:
            raise ValueError("动态内容不能为空且最多 1000 字")
        now = time.time()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "INSERT INTO qzone_content_pool(content,prompt,model_profile_id,status,created_at,generated_at,scheduled_at) VALUES(?,?,?,'pending',?,?,?)",
                (text, str(prompt or "").strip()[:2000], str(model_profile_id or "").strip()[:120], now, generated_at, scheduled_at),
            )
            return {"id": int(cursor.lastrowid), "content": text, "prompt": str(prompt or ""), "model_profile_id": str(model_profile_id or ""), "status": "pending", "created_at": now, "generated_at": generated_at, "scheduled_at": scheduled_at}

    def content_update(self, content_id: int, content: str, status: str | None = None, *, prompt: str | None = None, model_profile_id: str | None = None, scheduled_at: float | None = None) -> None:
        text = str(content or "").strip()
        if not text or len(text) > 1000:
            raise ValueError("动态内容不能为空且最多 1000 字")
        allowed = {"pending", "published", "rejected"}
        with self._lock, self._connect() as db:
            fields = ["content=?", "edited_at=?"]
            args: list[Any] = [text, time.time()]
            if prompt is not None:
                fields.append("prompt=?"); args.append(str(prompt).strip()[:2000])
            if model_profile_id is not None:
                fields.append("model_profile_id=?"); args.append(str(model_profile_id).strip()[:120])
            if scheduled_at is not None:
                fields.append("scheduled_at=?"); args.append(float(scheduled_at))
            args.append(int(content_id))
            if status in allowed:
                fields.append("status=?"); args.insert(-1, status)
                db.execute(f"UPDATE qzone_content_pool SET {','.join(fields)} WHERE id=?", tuple(args))
            else:
                db.execute(f"UPDATE qzone_content_pool SET {','.join(fields)} WHERE id=?", tuple(args))

    def content_delete(self, content_id: int) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM qzone_content_pool WHERE id=?", (int(content_id),))

    def content_get(self, content_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM qzone_content_pool WHERE id=?", (int(content_id),)).fetchone()
        return dict(row) if row else None

    def comment_list(self, include_used: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM qzone_comment_pool"
        if not include_used:
            query += " WHERE status='pending'"
        query += " ORDER BY id DESC"
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query).fetchall()]

    def comment_get(self, comment_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM qzone_comment_pool WHERE id=?", (int(comment_id),)).fetchone()
        return dict(row) if row else None

    def comment_next(self, *, tid: str = "", user_id: str = "") -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            if tid:
                row = db.execute("SELECT * FROM qzone_comment_pool WHERE status='pending' AND source_tid=? AND (source_user_id=? OR source_user_id='') ORDER BY id LIMIT 1", (str(tid), str(user_id))).fetchone()
            else:
                row = db.execute("SELECT * FROM qzone_comment_pool WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None

    def comment_add(self, content: str, *, prompt: str = "", model_profile_id: str = "", source_tid: str = "", source_user_id: str = "", source_content: str = "", generated_at: float | None = None) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text or len(text) > 200:
            raise ValueError("评论内容不能为空且最多 200 字")
        now = time.time()
        with self._lock, self._connect() as db:
            cursor = db.execute("INSERT INTO qzone_comment_pool(content,prompt,model_profile_id,source_tid,source_user_id,source_content,status,created_at,generated_at) VALUES(?,?,?,?,?,?,'pending',?,?)", (text, str(prompt or "").strip()[:2000], str(model_profile_id or "").strip()[:120], str(source_tid or "").strip()[:200], str(source_user_id or "").strip()[:40], str(source_content or "").strip()[:2000], now, generated_at))
        return {"id": int(cursor.lastrowid), "content": text, "prompt": str(prompt or ""), "model_profile_id": str(model_profile_id or ""), "source_tid": str(source_tid or ""), "source_user_id": str(source_user_id or ""), "source_content": str(source_content or ""), "status": "pending", "created_at": now, "generated_at": generated_at}

    def comment_update(self, comment_id: int, content: str, status: str | None = None, *, prompt: str | None = None, model_profile_id: str | None = None, source_tid: str | None = None, source_user_id: str | None = None, source_content: str | None = None) -> None:
        text = str(content or "").strip()
        if not text or len(text) > 200:
            raise ValueError("评论内容不能为空且最多 200 字")
        if status not in {None, "pending", "used"}:
            raise ValueError("评论状态无效")
        fields = ["content=?", "edited_at=?"]; args: list[Any] = [text, time.time()]
        if prompt is not None: fields.append("prompt=?"); args.append(str(prompt).strip()[:2000])
        if model_profile_id is not None: fields.append("model_profile_id=?"); args.append(str(model_profile_id).strip()[:120])
        if source_tid is not None: fields.append("source_tid=?"); args.append(str(source_tid).strip()[:200])
        if source_user_id is not None: fields.append("source_user_id=?"); args.append(str(source_user_id).strip()[:40])
        if source_content is not None: fields.append("source_content=?"); args.append(str(source_content).strip()[:2000])
        if status is not None: fields.append("status=?"); args.append(status)
        args.append(int(comment_id))
        with self._lock, self._connect() as db:
            db.execute(f"UPDATE qzone_comment_pool SET {','.join(fields)} WHERE id=?", tuple(args))

    def comment_delete(self, comment_id: int) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM qzone_comment_pool WHERE id=?", (int(comment_id),))

    def mark_comment_used(self, comment_id: int) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE qzone_comment_pool SET status='used', used_at=?, last_error='' WHERE id=?", (time.time(), int(comment_id)))

    def next_content(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM qzone_content_pool WHERE status='pending' ORDER BY id LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def mark_content_published(self, content_id: int) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE qzone_content_pool SET status='published', published_at=?, last_error='' WHERE id=?",
                (time.time(), int(content_id)),
            )

    def mark_content_error(self, content_id: int, error: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE qzone_content_pool SET last_error=? WHERE id=?",
                (str(error)[:500], int(content_id)),
            )

    def mark_content_rejected(self, content_id: int, error: str = "quality_gate") -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE qzone_content_pool SET status='rejected', last_error=? WHERE id=?",
                (str(error)[:500], int(content_id)),
            )

    def targets(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM qzone_targets ORDER BY nickname,user_id")]

    def save_targets(self, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM qzone_targets")
            for target in targets:
                user_id = str(target.get("user_id") or "").strip()
                if not user_id.isdigit():
                    continue
                db.execute(
                    "INSERT INTO qzone_targets(user_id,nickname,enabled_like,enabled_comment,updated_at) VALUES(?,?,?,?,?)",
                    (user_id, str(target.get("nickname") or f"QQ {user_id}"), int(bool(target.get("enabled_like", False))), int(bool(target.get("enabled_comment", False))), now),
                )
        return self.targets()

    def log(self, action: str, *, user_id: str = "", tid: str = "", content: str = "", status: str = "success", error: str = "") -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO qzone_automation_logs(action,user_id,tid,content,status,error,created_at) VALUES(?,?,?,?,?,?,?)",
                (action, str(user_id), str(tid), str(content), status, str(error)[:500], time.time()),
            )

    def already_logged(self, action: str, tid: str) -> bool:
        with self._lock, self._connect() as db:
            return db.execute(
                "SELECT 1 FROM qzone_automation_logs WHERE action=? AND tid=? AND status='success' LIMIT 1",
                (action, str(tid)),
            ).fetchone() is not None

    def logs(self, limit: int = 100, action: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        with self._lock, self._connect() as db:
            if action:
                rows = db.execute("SELECT * FROM qzone_automation_logs WHERE action=? ORDER BY created_at DESC LIMIT ?", (action, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM qzone_automation_logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def today_counts(self) -> dict[str, int]:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT action, COUNT(*) count FROM qzone_automation_logs WHERE status='success' AND created_at>=? GROUP BY action",
                (start,),
            ).fetchall()
        result = {"post": 0, "like": 0, "comment": 0}
        result.update({str(row["action"]): int(row["count"]) for row in rows})
        return result

    def count_success_since(self, action: str, since: float) -> int:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM qzone_automation_logs WHERE action=? AND status='success' AND created_at>=?",
                (str(action), float(since)),
            ).fetchone()
        return int(row["count"] if row else 0)

    def count_consumed_post_slots(self, period_key: str) -> int:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM qzone_post_slots "
                "WHERE slot_key LIKE ? AND status IN ('sending','published','uncertain')",
                (f"{str(period_key)}:%",),
            ).fetchone()
        return int(row["count"] if row else 0)

