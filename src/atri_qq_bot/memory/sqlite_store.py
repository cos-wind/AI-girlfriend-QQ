"""记忆的 SQLite 存储：把 ``users.json`` 的单文件全量重写换成行级 upsert。

## 为什么要换

现状（``memory/state.py``）：

* ``_save()`` 每条消息把**整个** 12.27MB 记忆树重新 ``json.dump``（还带 ``indent=2``）。
* ``_reload_if_changed()`` 每次 WebUI 改动记忆就让消息进程**全文重新解析** 12.27MB。
* 跨进程靠 mtime/ctime/size/inode 轮询同步，而不是事务。

即 **O(全库) per message**。换成 SQLite 后是行级 upsert + WAL，跨进程就是普通事务。

## 无损是硬要求

这个模块的第一目标是**往返逐字段相等**，不是"看起来对"。两个为此而生的设计：

1. **``seq`` 列**：``l1``/``l2``/``l3``/``candidates`` 是列表，``history`` 是有序数组，
   顺序本身就是信息。只按 ``at``/``created_at`` 排序会在时间戳相同时打乱顺序，
   所以额外存一个显式序号并按它还原。
2. **``entry_json`` 兜底**：``memory_entries`` 只建模了已知字段，未知字段原样存进
   ``entry_json``；``structured_memory`` 里非 ``l1/l2/l3/candidates`` 的键存进会话的
   ``__structured_extra__``。这样"今天没读懂的字段"不会在迁移中丢掉。

配 ``tools/dev/migrate_memory_json.py`` 做逐会话往返校验，任何一条不一致就整体中止。
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

LAYERS = ("l1", "l2", "l3", "candidates")

# structured_memory 里除了四个列表之外的键，统一塞进这个保留键。
STRUCTURED_EXTRA_KEY = "__structured_extra__"

# 记录"原记录里到底有哪些键"。
# 必要性：``l3`` / ``history`` **缺失**与"显式为空列表"看起来一样，但只有前者能通过
# 相等性检查。无条件补出四层与 history 会让 421 条会话对不上（实测）。
_LAYOUT_KEY = "__layout__"

# 只有这两项会拆成行；其余字段**原样**进 state_json。
# 列（message_count / last_user_at / …）是为了查询与排序而做的**派生副本**，
# state_json 才是事实源。这样还原就是"state_json + 行"，不会出现
# "某个标量为 0/None 时被漏掉"这类还原错误。
_ROW_BACKED_FIELDS = frozenset({"structured_memory", "history"})

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS conversations (
      account_id      TEXT NOT NULL DEFAULT '',
      conversation_id TEXT NOT NULL,
      kind            TEXT NOT NULL DEFAULT '',
      user_id         TEXT,
      group_id        TEXT,
      message_count   INTEGER NOT NULL DEFAULT 0,
      last_user_at    REAL,
      last_bot_at     REAL,
      state_json      TEXT NOT NULL DEFAULT '{}',
      updated_at      REAL NOT NULL DEFAULT 0,
      PRIMARY KEY (account_id, conversation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_entries (
      account_id      TEXT NOT NULL DEFAULT '',
      conversation_id TEXT NOT NULL,
      entry_id        TEXT NOT NULL,
      layer           TEXT NOT NULL,
      seq             INTEGER NOT NULL DEFAULT 0,
      category        TEXT NOT NULL DEFAULT '',
      memory_key      TEXT NOT NULL DEFAULT '',
      value           TEXT NOT NULL DEFAULT '',
      confidence      REAL NOT NULL DEFAULT 0,
      importance      TEXT,
      sentiment       TEXT,
      state           TEXT,
      activity        REAL,
      evidence_count  INTEGER NOT NULL DEFAULT 0,
      source          TEXT,
      source_type     TEXT,
      locked          INTEGER NOT NULL DEFAULT 0,
      visibility      TEXT NOT NULL DEFAULT 'private',
      created_at      REAL,
      updated_at      REAL,
      last_mentioned_at REAL,
      entry_json      TEXT NOT NULL DEFAULT '{}',
      -- 主键是 (层, 位置) 而不是 entry_id：实测源数据里 7997 个条目有 5339 个
      -- **没有 id 字段**，而且有 2 个会话存在同层重复 id。用 entry_id 当主键会
      -- 直接丢掉那 2 条。列表位置才是源数据真正的身份。
      PRIMARY KEY (account_id, conversation_id, layer, seq)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_evidence (
      account_id      TEXT NOT NULL DEFAULT '',
      conversation_id TEXT NOT NULL,
      entry_id        TEXT NOT NULL,
      seq             INTEGER NOT NULL DEFAULT 0,
      at              REAL,
      text            TEXT,
      type            TEXT,
      source_conversation TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS history (
      account_id      TEXT NOT NULL DEFAULT '',
      conversation_id TEXT NOT NULL,
      seq             INTEGER NOT NULL,
      at              REAL NOT NULL DEFAULT 0,
      role            TEXT NOT NULL DEFAULT '',
      text            TEXT NOT NULL DEFAULT '',
      actor_id        TEXT,
      nickname        TEXT,
      source_conversation TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_entries_entry_id ON memory_entries(account_id, entry_id)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_entry ON memory_evidence(account_id, conversation_id, entry_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_history_conv ON history(account_id, conversation_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_history_at ON history(account_id, conversation_id, at DESC)",
    "CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)",
    # 全文检索：与项目现有的 semantic_memory FTS5 用法一致，不引入向量库。
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
      text, content='history', content_rowid='rowid'
    )
    """,
)


# ---- 纯函数：JSON 记录 ↔ 行 -------------------------------------------------


def classify_conversation(conversation_id: str) -> tuple[str, str | None, str | None]:
    """从会话 key 解析出 (kind, user_id, group_id)。

    三种格式：``private:10001``、``group:20001``、``group:20001:user:10001``。
    解析不出来时返回 ``("", None, None)``——迁移不能因为一条怪 key 就整体失败。
    """
    parts = str(conversation_id or "").split(":")
    if len(parts) == 2 and parts[0] == "private" and parts[1]:
        return "private", parts[1], None
    if len(parts) == 4 and parts[0] == "group" and parts[1] and parts[2] == "user" and parts[3]:
        return "group_member", parts[3], parts[1]
    if len(parts) == 2 and parts[0] == "group" and parts[1]:
        return "group", None, parts[1]
    return "", None, None


def _entry_known_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """取出建模成列的字段。

    **不含 ``layer``**：条目所在的列表（l1/l2/l3/candidates）才是它的层，而且
    ``candidates`` 的条目根本没有 ``layer`` 字段。原条目里的 ``layer`` 值（大写
    ``"L1"``）会原样落进 entry_json，还原时再写回去。
    """
    return {
        "entry_id": str(entry.get("id") or entry.get("memory_key") or ""),
        "category": str(entry.get("category") or ""),
        "memory_key": str(entry.get("memory_key") or ""),
        "value": str(entry.get("value") or entry.get("text") or ""),
        "confidence": float(entry.get("confidence") or 0.0),
        "importance": _optional_text(entry.get("importance")),
        "sentiment": _optional_text(entry.get("sentiment")),
        "state": _optional_text(entry.get("state")),
        "activity": _optional_float(entry.get("activity")),
        "evidence_count": int(entry.get("evidence_count") or 0),
        "source": _optional_text(entry.get("source")),
        "source_type": _optional_text(entry.get("source_type")),
        "locked": 1 if entry.get("locked") else 0,
        "visibility": str(entry.get("visibility") or "private"),
        "created_at": _optional_float(entry.get("created_at")),
        "updated_at": _optional_float(entry.get("updated_at")),
        "last_mentioned_at": _optional_float(entry.get("last_mentioned_at")),
    }


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# 会被写成列的键。entry_json 里保存**完整原条目**，列只是派生索引。
_ENTRY_COLUMN_FIELDS = frozenset(_entry_known_fields({}).keys())


def conversation_to_rows(
    conversation_id: str,
    record: dict[str, Any],
    *,
    account_id: str = "",
) -> dict[str, Any]:
    """把一条会话记录拆成可写库的行。

    返回 ``{"conversation": row, "entries": [...], "evidence": [...], "history": [...]}``。
    """
    kind, user_id, group_id = classify_conversation(conversation_id)

    # state_json 逐字保存"除了结构化记忆与历史之外"的全部字段——
    # 包括未知字段与 target / message_count 这类标量。列只是查询用的派生副本。
    state = {
        key: value
        for key, value in record.items()
        if key not in _ROW_BACKED_FIELDS
    }

    structured = record.get("structured_memory")
    if isinstance(structured, dict):
        state[_LAYOUT_KEY] = {
            "keys": list(structured.keys()),
            "history": "history" in record,
        }
    else:
        state[_LAYOUT_KEY] = {"keys": [], "history": "history" in record}

    entries: list[dict[str, Any]] = []
    if isinstance(structured, dict):
        extra_structured = {
            key: value for key, value in structured.items() if key not in LAYERS
        }
        if extra_structured:
            state[STRUCTURED_EXTRA_KEY] = extra_structured
        for layer in LAYERS:
            items = structured.get(layer)
            if not isinstance(items, list):
                continue
            for seq, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                known = _entry_known_fields(item)
                if not known["entry_id"]:
                    # 没有 id 的条目需要一个确定性主键；占位符只用于主键，
                    # 不会出现在还原结果里（还原读的是 entry_json）。
                    known["entry_id"] = f"__no_id__:{layer}:{seq}"
                entries.append(
                    {
                        "conversation_id": conversation_id,
                        "layer": layer,
                        "seq": seq,
                        **known,
                        # 完整原条目逐字保存 —— 无损是结构性保证，不靠逐字段推敲。
                        "entry_json": json.dumps(item, ensure_ascii=False),
                    }
                )

    history = record.get("history")
    history_rows: list[dict[str, Any]] = []
    if isinstance(history, list):
        for seq, item in enumerate(history):
            if not isinstance(item, dict):
                continue
            history_rows.append(
                {
                    "conversation_id": conversation_id,
                    "seq": seq,
                    "at": float(item.get("at") or 0.0),
                    "role": str(item.get("role") or ""),
                    "text": str(item.get("text") or ""),
                    "actor_id": _optional_text(item.get("actor_id")),
                    "nickname": _optional_text(item.get("nickname")),
                    "source_conversation": _optional_text(item.get("source_conversation")),
                }
            )

    target = record.get("target")
    return {
        "conversation": {
            "conversation_id": conversation_id,
            "kind": kind,
            "user_id": user_id or _target_user(target),
            "group_id": group_id,
            "message_count": int(record.get("message_count") or 0),
            "last_user_at": _optional_float(record.get("last_user_at")),
            "last_bot_at": _optional_float(record.get("last_bot_at")),
            "state_json": json.dumps(state, ensure_ascii=False),
            "updated_at": float(
                _optional_float(record.get("last_user_at"))
                or _optional_float(record.get("last_bot_at"))
                or 0.0
            ),
        },
        "entries": entries,
        "evidence": [],
        "history": history_rows,
    }


def _target_user(target: Any) -> str | None:
    if not isinstance(target, dict):
        return None
    value = target.get("user_id")
    return str(value) if value not in (None, "") else None


def rows_to_conversation(
    conversation_row: dict[str, Any],
    entry_rows: list[dict[str, Any]],
    history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """把行还原成原始 JSON 记录。**必须与 ``conversation_to_rows`` 的输入逐字段相等。**"""
    state = json.loads(conversation_row["state_json"] or "{}")
    record: dict[str, Any] = dict(state)
    extra_structured = record.pop(STRUCTURED_EXTRA_KEY, None)
    layout = record.pop(_LAYOUT_KEY, None)

    grouped: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    for row in sorted(entry_rows, key=lambda item: (item["layer"], item["seq"])):
        layer = row["layer"]
        if layer not in grouped:
            # 未知 layer 不能丢：放进 extra，随 structured_memory 一起还原。
            extra_structured = extra_structured or {}
            extra_structured.setdefault("__unknown_layers__", {})[layer] = True
            continue
        grouped[layer].append(json.loads(row["entry_json"] or "{}"))

    if layout is None:
        # 老数据没有布局记录：退回"四层齐全"的保守还原。
        keys = list(LAYERS)
        had_history = True
    else:
        keys = list(layout.get("keys") or [])
        had_history = bool(layout.get("history"))

    structured: dict[str, Any] = {}
    for key in keys:
        if key in grouped:
            structured[key] = grouped[key]
        elif extra_structured and key in extra_structured:
            structured[key] = extra_structured[key]
    # 未知 layer 兜底：即便布局里没记，也不能丢。
    for key, value in (extra_structured or {}).items():
        structured.setdefault(key, value)
    # 原记录**没有** structured_memory 键时不要凭空造一个空壳。
    if structured or keys:
        record["structured_memory"] = structured

    if had_history:
        record["history"] = [
            _history_item(row)
            for row in sorted(history_rows, key=lambda item: item["seq"])
        ]

    # message_count / last_user_at / last_bot_at 已经在 state_json 里（它是事实源），
    # 这里不再补——之前那样补会在值为 0/None 时把它们丢掉。
    return record


def _history_item(row: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"at": row["at"], "role": row["role"], "text": row["text"]}
    for column in ("actor_id", "nickname", "source_conversation"):
        if row[column] is not None:
            item[column] = row[column]
    return item


class MemorySqliteStore:
    """记忆的 SQLite 存储。stdlib ``sqlite3`` + WAL，与项目其它 4 个库写法一致。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current < SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # ---- 写 -------------------------------------------------------------

    def write_conversation(
        self,
        conversation_id: str,
        record: dict[str, Any],
        *,
        account_id: str = "",
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """整体替换一条会话（会话状态 + 条目 + 历史）。"""
        rows = conversation_to_rows(conversation_id, record, account_id=account_id)
        if connection is not None:
            self._write_rows(connection, account_id, rows)
            return
        with self._connect() as own:
            self._write_rows(own, account_id, rows)

    def _write_rows(
        self, connection: sqlite3.Connection, account_id: str, rows: dict[str, Any]
    ) -> None:
        conversation = rows["conversation"]
        connection.execute(
            "INSERT INTO conversations(account_id,conversation_id,kind,user_id,group_id,"
            "message_count,last_user_at,last_bot_at,state_json,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id,conversation_id) DO UPDATE SET "
            "kind=excluded.kind,user_id=excluded.user_id,group_id=excluded.group_id,"
            "message_count=excluded.message_count,last_user_at=excluded.last_user_at,"
            "last_bot_at=excluded.last_bot_at,state_json=excluded.state_json,"
            "updated_at=excluded.updated_at",
            (
                account_id,
                conversation["conversation_id"],
                conversation["kind"],
                conversation["user_id"],
                conversation["group_id"],
                conversation["message_count"],
                conversation["last_user_at"],
                conversation["last_bot_at"],
                conversation["state_json"],
                conversation["updated_at"],
            ),
        )

        # 条目与历史整体替换：先删后插，保证"删掉的条目真的没了"。
        connection.execute(
            "DELETE FROM memory_entries WHERE account_id=? AND conversation_id=?",
            (account_id, conversation["conversation_id"]),
        )
        connection.execute(
            "DELETE FROM memory_evidence WHERE account_id=? AND conversation_id=?",
            (account_id, conversation["conversation_id"]),
        )
        connection.execute(
            "DELETE FROM history WHERE account_id=? AND conversation_id=?",
            (account_id, conversation["conversation_id"]),
        )

        for entry in rows["entries"]:
            connection.execute(
                "INSERT INTO memory_entries(account_id,conversation_id,entry_id,layer,seq,"
                "category,memory_key,value,confidence,importance,sentiment,state,activity,"
                "evidence_count,source,source_type,locked,visibility,created_at,updated_at,"
                "last_mentioned_at,entry_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    entry["conversation_id"],
                    entry["entry_id"],
                    entry["layer"],
                    entry["seq"],
                    entry["category"],
                    entry["memory_key"],
                    entry["value"],
                    entry["confidence"],
                    entry["importance"],
                    entry["sentiment"],
                    entry["state"],
                    entry["activity"],
                    entry["evidence_count"],
                    entry["source"],
                    entry["source_type"],
                    entry["locked"],
                    entry["visibility"],
                    entry["created_at"],
                    entry["updated_at"],
                    entry["last_mentioned_at"],
                    json.dumps(entry["extra"], ensure_ascii=False)
                    if "extra" in entry
                    else entry["entry_json"],
                ),
            )

        for row in rows["history"]:
            connection.execute(
                "INSERT INTO history(account_id,conversation_id,seq,at,role,text,actor_id,"
                "nickname,source_conversation) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    row["conversation_id"],
                    row["seq"],
                    row["at"],
                    row["role"],
                    row["text"],
                    row["actor_id"],
                    row["nickname"],
                    row["source_conversation"],
                ),
            )

    def set_meta(self, key: str, value: Any, *, connection: sqlite3.Connection | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        if connection is not None:
            connection.execute(
                "INSERT INTO memory_meta(key,value_json) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (str(key), payload),
            )
            return
        with self._connect() as own:
            own.execute(
                "INSERT INTO memory_meta(key,value_json) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (str(key), payload),
            )

    # ---- 读 -------------------------------------------------------------

    def conversation_ids(self, *, account_id: str = "") -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT conversation_id FROM conversations WHERE account_id=? "
                "ORDER BY conversation_id",
                (account_id,),
            ).fetchall()
        return [str(row["conversation_id"]) for row in rows]

    def count(self, *, account_id: str = "") -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM conversations WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0]
            )

    def read_conversation(
        self, conversation_id: str, *, account_id: str = ""
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._read_conversation(connection, conversation_id, account_id)

    def _read_conversation(
        self, connection: sqlite3.Connection, conversation_id: str, account_id: str
    ) -> dict[str, Any] | None:
        conversation = connection.execute(
            "SELECT * FROM conversations WHERE account_id=? AND conversation_id=?",
            (account_id, conversation_id),
        ).fetchone()
        if conversation is None:
            return None
        entries = connection.execute(
            "SELECT * FROM memory_entries WHERE account_id=? AND conversation_id=? "
            "ORDER BY layer, seq",
            (account_id, conversation_id),
        ).fetchall()
        history = connection.execute(
            "SELECT * FROM history WHERE account_id=? AND conversation_id=? ORDER BY seq",
            (account_id, conversation_id),
        ).fetchall()
        return rows_to_conversation(
            dict(conversation),
            [dict(row) for row in entries],
            [dict(row) for row in history],
        )

    def read_all(self, *, account_id: str = "") -> dict[str, dict[str, Any]]:
        """还原整棵记忆树（形状与 ``users.json`` 的 ``conversations`` 一致）。"""
        result: dict[str, dict[str, Any]] = {}
        with self._connect() as connection:
            for conversation_id in self.conversation_ids(account_id=account_id):
                record = self._read_conversation(connection, conversation_id, account_id)
                if record is not None:
                    result[conversation_id] = record
        return result

    def history(self, conversation_id: str, *, account_id: str = "", limit: int = 80) -> list[dict[str, Any]]:
        """取最近 ``limit`` 条历史，按时间正序返回。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM history WHERE account_id=? AND conversation_id=? "
                "ORDER BY seq DESC LIMIT ?",
                (account_id, conversation_id, max(1, int(limit))),
            ).fetchall()
        ordered = sorted((dict(row) for row in rows), key=lambda item: item["seq"])
        return [
            {
                "at": row["at"],
                "role": row["role"],
                "text": row["text"],
                **(
                    {"actor_id": row["actor_id"]}
                    if row["actor_id"] is not None
                    else {}
                ),
                **({"nickname": row["nickname"]} if row["nickname"] is not None else {}),
                **(
                    {"source_conversation": row["source_conversation"]}
                    if row["source_conversation"] is not None
                    else {}
                ),
            }
            for row in ordered
        ]

    # ---- 维护 -----------------------------------------------------------

    def stats(self, *, account_id: str = "") -> dict[str, int]:
        with self._connect() as connection:
            def one(sql: str) -> int:
                return int(connection.execute(sql, (account_id,)).fetchone()[0])

            return {
                "conversations": one(
                    "SELECT COUNT(*) FROM conversations WHERE account_id=?"
                ),
                "entries": one(
                    "SELECT COUNT(*) FROM memory_entries WHERE account_id=?"
                ),
                "history": one("SELECT COUNT(*) FROM history WHERE account_id=?"),
            }

    def rebuild_fts(self) -> int:
        """重建全文索引。JSON 是可编辑事实源，索引随时可重建——和项目既有立场一致。"""
        with self._connect() as connection:
            connection.execute("INSERT INTO history_fts(history_fts) VALUES('rebuild')")
            return int(
                connection.execute("SELECT COUNT(*) FROM history_fts").fetchone()[0]
            )


__all__ = [
    "LAYERS",
    "MemorySqliteStore",
    "SCHEMA_VERSION",
    "STRUCTURED_EXTRA_KEY",
    "classify_conversation",
    "conversation_to_rows",
    "rows_to_conversation",
]
