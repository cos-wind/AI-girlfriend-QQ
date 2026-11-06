"""Durable generation receipts. Interrupted work is never replayed blindly."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3


class TurnLedger:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT)')
                yield db
        finally:
            db.close()

    def claim(self, key: str, payload: dict):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint, result FROM turns WHERE id=?', (key,)).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError('同一平台事件的内容已变化')
                if row[1] is None:
                    raise ValueError('该事件仍在处理或结果未确认，请检查记录，不会自动重复生成')
                return json.loads(row[1])
            db.execute('INSERT INTO turns VALUES (?,?,NULL)', (key, digest))
        return None

    def complete(self, key: str, result: dict):
        with self._db() as db:
            db.execute('UPDATE turns SET result=? WHERE id=?', (json.dumps(result, ensure_ascii=False), key))
