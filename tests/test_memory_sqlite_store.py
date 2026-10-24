"""记忆 SQLite 存储的测试（阶段 6a）。

核心断言是**往返逐字段相等**，包括源数据里那些刁钻的形状：

* 条目**没有 `id` 字段**（实测 7997 个条目里 5339 个如此）
* 同层存在**重复 `entry_id`**（实测 2 个会话如此）——用 entry_id 当主键会丢数据
* 条目**没有 `layer` 字段**（candidates 就是这种）
* `structured_memory` **缺少某一层**、记录**缺少 `history` 键**
* 未知字段（今天的代码读不懂，但不能在迁移中丢掉）

这些都是靠真实数据（1302 条会话）跑往返时抓出来的，不是设想出来的。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atri_qq_bot.memory.sqlite_store import (
    MemorySqliteStore,
    classify_conversation,
    conversation_to_rows,
    rows_to_conversation,
)


def _record(**overrides):
    """一条覆盖了各种刁钻形状的记忆记录。"""
    record = {
        "message_count": 42,
        "last_user_at": 1700000000.5,
        "last_bot_at": 1700000100.25,
        "affection_score": 40.462,
        "affection_initialized": True,
        "target": {"message_type": "private", "user_id": 10001},
        "topic_words": ["咖啡", "学习"],
        "feature_counts": {"question": 3},
        "structured_memory": {
            "l1": [
                # 有 id、有 layer（原值是大写）
                {
                    "id": "l1:interest:咖啡",
                    "layer": "L1",
                    "category": "interest",
                    "key": "兴趣:咖啡",
                    "memory_key": "interest:咖啡",
                    "value": "咖啡",
                    "confidence": 0.9,
                    "evidence_count": 4,
                    "source_type": "explicit",
                    "created_at": 1780458580.6,
                    "locked": True,
                    "visibility": "private",
                    "sources": [{"at": 1782961872.4, "text": "喜欢咖啡", "type": "explicit"}],
                },
                # 同层重复 id —— 用 entry_id 当主键会丢掉这一条
                {
                    "id": "l1:interest:咖啡",
                    "layer": "L1",
                    "category": "interest",
                    "memory_key": "interest:咖啡",
                    "value": "重复 id 的第二条",
                    "confidence": 0.5,
                },
            ],
            "l2": [
                {
                    "layer": "L2",
                    "category": "important_interaction",
                    "key": "medium:vulnerable:难受",
                    "value": "难受",
                    "activity": 0.0,
                    "confidence": 0.7,
                    "state": "sleeping",
                    "sentiment": "vulnerable",
                    "importance": "medium",
                    "affection_snapshot": 45.65,
                }
            ],
            "candidates": [
                # 没有 id、也没有 layer 字段
                {
                    "category": "interest",
                    "key": "兴趣:原神",
                    "value": "原神",
                    "confidence": 0.6,
                    "message_type": "group",
                }
            ],
            # 没有 l3 这一层
        },
        "history": [
            {"at": 1783677875.89, "role": "user", "text": "第一条", "actor_id": "10001"},
            {"at": 1783677876.89, "role": "bot", "text": "第二条"},
            {"at": 1783677877.89, "role": "user", "text": "第三条", "nickname": "四氯化碳"},
        ],
        # 今天代码读不懂的字段，迁移里不能丢
        "some_future_field": {"nested": [1, 2, 3]},
    }
    record.update(overrides)
    return record


# ---- 会话 key 解析 ------------------------------------------------------


@pytest.mark.parametrize(
    "conversation_id,expected",
    [
        ("private:10001", ("private", "10001", None)),
        ("group:20001", ("group", None, "20001")),
        ("group:20001:user:10001", ("group_member", "10001", "20001")),
        ("webui:test", ("", None, None)),
        ("", ("", None, None)),
        ("private:", ("", None, None)),
    ],
)
def test_classify_conversation(conversation_id: str, expected: tuple) -> None:
    assert classify_conversation(conversation_id) == expected


# ---- 纯函数往返（不碰数据库）-------------------------------------------


def test_pure_round_trip_is_field_for_field_equal() -> None:
    original = _record()

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert restored == original


def test_duplicate_entry_ids_in_the_same_layer_are_both_kept() -> None:
    """源数据里有同层重复 id。真实身份是 (层, 位置)，不是 id。"""
    original = _record()

    rows = conversation_to_rows("private:10001", original)
    l1_rows = [row for row in rows["entries"] if row["layer"] == "l1"]
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert len(l1_rows) == 2
    assert len(restored["structured_memory"]["l1"]) == 2
    assert restored == original


def test_entries_without_id_are_preserved() -> None:
    """candidates 的条目没有 id，也没有 layer 字段——还原后同样不该有。"""
    original = _record()

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    candidate = restored["structured_memory"]["candidates"][0]
    assert candidate["value"] == "原神"
    assert "id" not in candidate
    assert "layer" not in candidate


def test_original_layer_casing_is_restored() -> None:
    """源数据里 layer 是大写 "L1"，而 structured_memory 的键是小写 l1。"""
    original = _record()

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert restored["structured_memory"]["l1"][0]["layer"] == "L1"
    assert restored["structured_memory"]["l2"][0]["layer"] == "L2"


def test_missing_layer_key_is_not_invented() -> None:
    """原记录没有 l3 这一层，还原时不能凭空补一个空列表。"""
    original = _record()

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert "l3" not in restored["structured_memory"]


def test_missing_history_key_is_not_invented() -> None:
    original = _record()
    del original["history"]

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert "history" not in restored


def test_unknown_top_level_field_survives() -> None:
    original = _record()

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert restored["some_future_field"] == {"nested": [1, 2, 3]}


def test_zero_valued_scalars_survive() -> None:
    """message_count=0 这类值以前会在还原时被漏掉。"""
    original = _record(message_count=0, affection_score=0.0)

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert restored["message_count"] == 0
    assert restored["affection_score"] == 0.0
    assert restored == original


def test_extra_structured_keys_survive() -> None:
    original = _record()
    original["structured_memory"]["future_layer"] = {"whatever": True}

    rows = conversation_to_rows("private:10001", original)
    restored = rows_to_conversation(
        rows["conversation"], rows["entries"], rows["history"]
    )

    assert restored["structured_memory"]["future_layer"] == {"whatever": True}
    assert restored == original


# ---- 数据库往返 ---------------------------------------------------------


def test_database_round_trip_is_field_for_field_equal(tmp_path) -> None:
    original = _record()
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")

    store.write_conversation("private:10001", original)
    restored = store.read_conversation("private:10001")

    assert restored == original


def test_database_keeps_both_duplicate_id_entries(tmp_path) -> None:
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")

    store.write_conversation("private:10001", _record())

    record = store.read_conversation("private:10001")
    assert len(record["structured_memory"]["l1"]) == 2


def test_row_counts_match_the_source(tmp_path) -> None:
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")

    store.write_conversation("private:10001", _record())

    stats = store.stats()
    assert stats["conversations"] == 1
    # l1 两条 + l2 一条 + candidates 一条
    assert stats["entries"] == 4
    assert stats["history"] == 3


def test_write_replaces_instead_of_appending(tmp_path) -> None:
    """删掉的条目必须真的没了——这是整体替换而不是增量追加。"""
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    store.write_conversation("private:10001", _record())

    smaller = _record()
    smaller["structured_memory"]["l1"] = smaller["structured_memory"]["l1"][:1]
    smaller["history"] = smaller["history"][:1]
    store.write_conversation("private:10001", smaller)

    stats = store.stats()
    assert stats["entries"] == 3
    assert stats["history"] == 1


def test_write_is_idempotent(tmp_path) -> None:
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    original = _record()

    store.write_conversation("private:10001", original)
    store.write_conversation("private:10001", original)

    assert store.stats()["entries"] == 4
    assert store.read_conversation("private:10001") == original


def test_read_missing_conversation_returns_none(tmp_path) -> None:
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")

    assert store.read_conversation("private:99999") is None


def test_multiple_conversations_are_isolated(tmp_path) -> None:
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    store.write_conversation("private:10001", _record(message_count=1))
    store.write_conversation("group:20001", _record(message_count=2))

    assert store.count() == 2
    assert store.read_conversation("private:10001")["message_count"] == 1
    assert store.read_conversation("group:20001")["message_count"] == 2
    assert store.conversation_ids() == ["group:20001", "private:10001"]


def test_read_all_returns_the_same_shape_as_users_json(tmp_path) -> None:
    """还原出来的形状必须和 users.json 的 conversations 一致，调用方才好替换。"""
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    original = _record()
    store.write_conversation("private:10001", original)

    restored = store.read_all()

    assert list(restored) == ["private:10001"]
    assert restored["private:10001"] == original


def test_history_returns_recent_entries_in_order(tmp_path) -> None:
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    store.write_conversation("private:10001", _record())

    recent = store.history("private:10001", limit=2)

    # 取最近 2 条，但按时间正序返回。
    assert [item["text"] for item in recent] == ["第二条", "第三条"]


def test_fts_can_be_rebuilt(tmp_path) -> None:
    """JSON 是可编辑事实源，检索索引随时可重建——与项目既有立场一致。"""
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    store.write_conversation("private:10001", _record())

    assert store.rebuild_fts() == 3


def test_existing_database_is_reopened_cleanly(tmp_path) -> None:
    path = tmp_path / "memory.sqlite3"
    original = _record()
    MemorySqliteStore(path).write_conversation("private:10001", original)

    reopened = MemorySqliteStore(path)

    assert reopened.read_conversation("private:10001") == original


# ---- 与真实数据一致的说明性测试 ----------------------------------------


def test_a_record_with_no_id_and_no_layer_classifies_correctly(tmp_path) -> None:
    """最朴素的候选条目：既没有 id 也没有 layer，仍要能稳定存取。"""
    minimal = {
        "structured_memory": {
            "candidates": [{"category": "interest", "value": "原神", "confidence": 0.6}]
        }
    }
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")

    store.write_conversation("private:10001", minimal)

    assert store.read_conversation("private:10001") == minimal


def test_layout_marker_is_not_leaked_into_the_restored_record(tmp_path) -> None:
    """内部保留键（__layout__ / __structured_extra__）不能出现在还原结果里。"""
    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    store.write_conversation("private:10001", _record())

    restored = store.read_conversation("private:10001")

    assert "__layout__" not in restored
    assert "__structured_extra__" not in restored
    assert "__layout__" not in restored["structured_memory"]
    assert "__structured_extra__" not in restored["structured_memory"]


# ---- 真实数据回归（本地有 data-dev 时才跑）------------------------------

REAL_SOURCE = (
    Path(__file__).resolve().parents[1] / "data-dev" / "data" / "memory" / "users.json"
)


@pytest.mark.skipif(
    not REAL_SOURCE.is_file(),
    reason="需要本地 data-dev/data/memory/users.json（WAL 安全快照的副本）",
)
def test_all_real_conversations_round_trip(tmp_path) -> None:
    """把真实的 1300+ 条会话全部往返一遍。

    这条测试的价值在于**真实数据的形状比人想得到的更刁钻**——它是怎么发现
    "条目没有 id"、"同层重复 id"、"缺少某一层"这些情况的。合成夹具容易漏掉这些。
    """
    document = json.loads(REAL_SOURCE.read_text(encoding="utf-8"))
    conversations = document["conversations"]
    assert len(conversations) > 1000

    store = MemorySqliteStore(tmp_path / "memory.sqlite3")
    for conversation_id, record in conversations.items():
        if isinstance(record, dict):
            store.write_conversation(conversation_id, record)

    mismatched = [
        conversation_id
        for conversation_id, record in conversations.items()
        if isinstance(record, dict) and store.read_conversation(conversation_id) != record
    ]

    assert mismatched == []
    assert store.count() == sum(
        1 for record in conversations.values() if isinstance(record, dict)
    )
