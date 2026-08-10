"""SQLite FTS5 检索仓库。

JSON 仍是用户可编辑的记忆事实源；本仓库只是可再生索引。SQLite 是 Python
标准库，FTS5 随当前 Python 的 SQLite 提供，因此不会额外启动数据库服务。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RetrievedEntry:
    """一次召回的最小数据契约，供 Planner 而非上层业务模块消费。"""

    entry_id: str
    scope: str
    source: str
    layer: str
    title: str
    content: str
    importance: float
    updated_at: float
    score: float
    metadata: dict[str, Any]


class SemanticMemoryRepository:
    """短事务、WAL 模式的本地全文索引。

    每次操作都新建连接，避免 SQLite 连接跨 WebUI/OneBot 线程复用。所有写入
    都很小；索引不可用时抛出普通异常，调用方负责降级而不是阻断回复。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS semantic_entries (
                        entry_id TEXT PRIMARY KEY,
                        scope TEXT NOT NULL,
                        source TEXT NOT NULL,
                        layer TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        importance REAL NOT NULL DEFAULT 0.5,
                        updated_at REAL NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_semantic_entries_scope
                        ON semantic_entries(scope, source, updated_at DESC);
                    CREATE VIRTUAL TABLE IF NOT EXISTS semantic_entries_fts
                    USING fts5(
                        entry_id UNINDEXED,
                        scope UNINDEXED,
                        terms,
                        tokenize='unicode61'
                    );
                    CREATE TABLE IF NOT EXISTS semantic_embeddings (
                        entry_id TEXT PRIMARY KEY REFERENCES semantic_entries(entry_id) ON DELETE CASCADE,
                        model TEXT NOT NULL,
                        dimensions INTEGER NOT NULL,
                        vector BLOB NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_model
                        ON semantic_embeddings(model, updated_at DESC);
                    """
                )
            self._schema_ready = True

    def replace_scope_source(
        self,
        scope: str,
        source: str,
        entries: Iterable[dict[str, Any]],
    ) -> int:
        """以一小批最新档案替换某会话的索引，保证编辑/删除即时生效。"""

        self.ensure_schema()
        rows = [self._normalise_entry(scope, source, item) for item in entries]
        with self._connect() as conn:
            old_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT entry_id FROM semantic_entries WHERE scope = ? AND source = ?",
                    (scope, source),
                )
            ]
            if old_ids:
                conn.executemany(
                    "DELETE FROM semantic_entries_fts WHERE entry_id = ?",
                    ((entry_id,) for entry_id in old_ids),
                )
                conn.executemany(
                    "DELETE FROM semantic_embeddings WHERE entry_id = ?",
                    ((entry_id,) for entry_id in old_ids),
                )
            conn.execute(
                "DELETE FROM semantic_entries WHERE scope = ? AND source = ?",
                (scope, source),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO semantic_entries(
                        entry_id, scope, source, layer, title, content,
                        importance, updated_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [row[:9] for row in rows],
                )
                conn.executemany(
                    "INSERT INTO semantic_entries_fts(entry_id, scope, terms) VALUES (?, ?, ?)",
                    ((row[0], row[1], row[9]) for row in rows),
                )
        return len(rows)

    def search(self, scope: str, query: str, limit: int = 5) -> list[RetrievedEntry]:
        """在单一 scope 内检索，scope 是防止私聊记忆泄漏的硬边界。"""

        self.ensure_schema()
        match_query = _fts_query(query)
        if not match_query:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.entry_id, e.scope, e.source, e.layer, e.title, e.content,
                       e.importance, e.updated_at, e.metadata_json,
                       bm25(semantic_entries_fts) AS rank
                FROM semantic_entries_fts
                JOIN semantic_entries AS e ON e.entry_id = semantic_entries_fts.entry_id
                WHERE semantic_entries_fts MATCH ? AND semantic_entries_fts.scope = ?
                ORDER BY rank ASC, e.importance DESC, e.updated_at DESC
                LIMIT ?
                """,
                (match_query, scope, max(1, min(12, int(limit)))),
            ).fetchall()
        result: list[RetrievedEntry] = []
        for row in rows:
            try:
                metadata = json.loads(row[8])
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            result.append(
                RetrievedEntry(
                    entry_id=str(row[0]), scope=str(row[1]), source=str(row[2]),
                    layer=str(row[3]), title=str(row[4]), content=str(row[5]),
                    importance=float(row[6]), updated_at=float(row[7]),
                    # FTS5 的 bm25 越小越相关；转换成易合并的正向得分。
                    score=max(0.0, -float(row[9])) + float(row[6]),
                    metadata=metadata if isinstance(metadata, dict) else {},
                )
            )
        return result

    def embedding_candidates(self, model: str, limit: int = 20) -> list[tuple[str, str]]:
        """返回尚未由指定模型编码的条目，供低优先级维护脚本分批处理。"""

        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.entry_id, e.title || '：' || e.content
                FROM semantic_entries AS e
                LEFT JOIN semantic_embeddings AS v
                    ON v.entry_id = e.entry_id AND v.model = ?
                WHERE v.entry_id IS NULL
                ORDER BY e.importance DESC, e.updated_at DESC
                LIMIT ?
                """,
                (model, max(1, min(200, int(limit)))),
            ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def save_embedding(self, entry_id: str, model: str, values: list[float]) -> None:
        """写入 float32 BLOB；不依赖试验期 sqlite-vec 扩展。"""

        if not values:
            return
        self.ensure_schema()
        vector = struct.pack(f"<{len(values)}f", *[float(value) for value in values])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO semantic_embeddings(entry_id, model, dimensions, vector, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                    model=excluded.model, dimensions=excluded.dimensions,
                    vector=excluded.vector, updated_at=excluded.updated_at
                """,
                (entry_id, model, len(values), vector, time.time()),
            )

    def embedding_count(self, model: str | None = None) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            if model:
                row = conn.execute(
                    "SELECT COUNT(*) FROM semantic_embeddings WHERE model = ?", (model,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM semantic_embeddings").fetchone()
        return int(row[0]) if row else 0

    def vector_search(
        self, scope: str, model: str, query: list[float], limit: int = 5
    ) -> list[RetrievedEntry]:
        """小规模精确余弦检索。

        当前记忆索引是几十到数千条级别，精确扫描比引入常驻向量数据库更稳；
        若未来规模显著增长，Planner 接口无需改动即可替换为 sqlite-vec/HNSW。
        """

        if not query:
            return []
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.entry_id, e.scope, e.source, e.layer, e.title, e.content,
                       e.importance, e.updated_at, e.metadata_json, v.vector, v.dimensions
                FROM semantic_embeddings AS v
                JOIN semantic_entries AS e ON e.entry_id = v.entry_id
                WHERE e.scope = ? AND v.model = ?
                """,
                (scope, model),
            ).fetchall()
        ranked: list[RetrievedEntry] = []
        for row in rows:
            dimensions = int(row[10])
            if dimensions != len(query) or len(row[9]) != dimensions * 4:
                continue
            values = list(struct.unpack(f"<{dimensions}f", row[9]))
            score = _cosine(query, values)
            if score <= 0:
                continue
            try:
                metadata = json.loads(row[8])
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            ranked.append(
                RetrievedEntry(
                    entry_id=str(row[0]), scope=str(row[1]), source=str(row[2]),
                    layer=str(row[3]), title=str(row[4]), content=str(row[5]),
                    importance=float(row[6]), updated_at=float(row[7]), score=score,
                    metadata=metadata if isinstance(metadata, dict) else {},
                )
            )
        return sorted(ranked, key=lambda item: (item.score, item.importance, item.updated_at), reverse=True)[:limit]

    def status(self) -> dict[str, Any]:
        """供 WebUI 轻量展示；不初始化数据库，也不会改变运行状态。"""

        if not self.path.exists():
            return {"ready": False, "path": str(self.path), "entries": 0}
        try:
            with self._connect() as conn:
                count = int(conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()[0])
                sources = {
                    str(source): int(total)
                    for source, total in conn.execute(
                        "SELECT source, COUNT(*) FROM semantic_entries GROUP BY source"
                    )
                }
            return {"ready": True, "path": str(self.path), "entries": count, "sources": sources}
        except sqlite3.Error as exc:
            return {"ready": False, "path": str(self.path), "entries": 0, "error": str(exc)}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=0.35)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=350")
        return conn

    @staticmethod
    def _normalise_entry(scope: str, source: str, entry: dict[str, Any]) -> tuple[Any, ...]:
        title = _compact(entry.get("title") or entry.get("key") or entry.get("layer") or "记忆")
        content = _compact(entry.get("content") or entry.get("value") or "")
        layer = _compact(entry.get("layer") or "memory")
        updated_at = _as_float(entry.get("updated_at"), time.time())
        importance = max(0.0, min(1.0, _as_float(entry.get("importance"), 0.5)))
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        identity = json.dumps([scope, source, layer, title, content], ensure_ascii=False)
        entry_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        terms = _search_terms(" ".join((title, content, _category_hints(layer, metadata))))
        return (
            entry_id, scope, source, layer, title, content, importance, updated_at,
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), terms,
        )


def _search_terms(text: str) -> str:
    """为 unicode61 补上中文二元词，避免连续中文被当成一个超长 token。"""

    compact = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", str(text or "").lower())
    latin = re.findall(r"[a-z0-9]{2,}", compact)
    grams = [compact[index : index + 2] for index in range(max(0, len(compact) - 1))]
    return " ".join(dict.fromkeys([*latin, *grams]))


def _fts_query(text: str) -> str:
    terms = _search_terms(text).split()
    # 多个二元词用 OR：用户短问题和原作专名都不会因一个缺失词变成零召回。
    return " OR ".join('"' + term.replace('"', "") + '"' for term in terms[:18] if term)


def _category_hints(layer: str, metadata: dict[str, Any]) -> str:
    category = str(metadata.get("category") or "")
    value = f"{layer} {category}".lower()
    if any(part in value for part in ("interest", "preference", "兴趣", "偏好", "喜欢")):
        return "喜欢 兴趣 偏好 推荐 吃喝 吃点 吃什么 喝点 喝什么 游戏 动画 音游"
    if any(part in value for part in ("event", "schedule", "事件", "日程")):
        return "今天 明天 日程 提醒 生日 考试 会议"
    if any(part in value for part in ("style", "communication", "习惯", "回复")):
        return "怎么说 回复 语气 简短 详细 聊天"
    return ""


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:1200]


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
