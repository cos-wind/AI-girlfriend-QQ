from __future__ import annotations

import json
import time
from types import SimpleNamespace

from atri_qq_bot.memory import UserMemoryStore
from atri_webui.memory_admin import MemoryAdmin


def _memory_config() -> SimpleNamespace:
    # 测试规则提取与回写时关闭模型，避免测试进程加载本地大模型；正式配置
    # 通过 .env 的 MEMORY_EXTRACTION_LLM_ENABLED 控制模型增强。
    return SimpleNamespace(
        memory_extraction_enabled=True,
        memory_extraction_llm_enabled=False,
    )


def _wait_for(path, predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if predicate(data):
                return data
        time.sleep(0.02)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    assert predicate(data), data
    return data


def test_background_extractor_writes_private_l1_l2_l3_without_blocking(tmp_path) -> None:
    path = tmp_path / "users.json"
    store = UserMemoryStore(path, _memory_config())

    started = time.perf_counter()
    store.observe_user("private:10001", "我叫小明，我喜欢咖啡，明天有考试", now=1000)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    saved = _wait_for(
        path,
        lambda data: bool(
            data.get("conversations", {})
            .get("private:10001", {})
            .get("structured_memory", {})
            .get("l1")
        ),
    )
    memory = saved["conversations"]["private:10001"]["structured_memory"]
    assert any(entry.get("value") == "小明" for entry in memory["l1"])
    assert any(entry.get("value") == "咖啡" for entry in memory["l1"])
    assert any("考试" in str(entry.get("value")) for entry in memory["l2"])
    assert any(entry.get("value") == "我叫小明，我喜欢咖啡，明天有考试" for entry in memory["l3"])


def test_group_extractor_keeps_group_scope_and_member_profile_separate(tmp_path) -> None:
    path = tmp_path / "users.json"
    store = UserMemoryStore(path, _memory_config())

    store.observe_group_message(
        20001,
        30001,
        "我喜欢咖啡，明天有考试",
        nickname="小明",
        now=1000,
        addressed_to_bot=True,
    )
    saved = _wait_for(
        path,
        lambda data: all(
            bool(
                data.get("conversations", {})
                .get(conversation_id, {})
                .get("structured_memory", {})
                .get("l1")
            )
            for conversation_id in (
                "group:20001",
                "group:20001:user:30001",
                "private:30001",
            )
        ),
    )
    conversations = saved["conversations"]
    group_memory = conversations["group:20001"]["structured_memory"]
    member_memory = conversations["group:20001:user:30001"]["structured_memory"]
    person_memory = conversations["private:30001"]["structured_memory"]

    assert group_memory["l3"]
    assert member_memory["l3"]
    assert person_memory["l3"]
    assert any(entry.get("category") == "event" for entry in group_memory["l2"])
    assert any("群体" in str(entry.get("key")) for entry in group_memory["l1"])
    # 群成员的公开信息可以汇入统一人物档案，但不会把其他成员的 L3 混入。
    detail = MemoryAdmin(path, tmp_path / "backups").detail("id=person%3A30001")
    assert detail["ok"] is True
    assert detail["layers"]["l3"]
    assert detail["memory_counts"]["l1"] >= 1
    assert detail["memory_counts"]["l2"] >= 1


def test_webui_edit_wins_over_queued_old_extraction(tmp_path) -> None:
    path = tmp_path / "users.json"
    store = UserMemoryStore(path, _memory_config())
    store.observe_user("private:10001", "我喜欢喝奶茶", now=1000)
    store.observe_user("private:10001", "我真的喜欢喝奶茶", now=1010)

    MemoryAdmin(path, tmp_path / "backups").save_conversation(
        "person:10001",
        {
            "structured_memory": {
                "l1": [{"category": "interest", "key": "兴趣:咖啡", "value": "咖啡"}],
                "l2": [],
                "candidates": [],
            }
        },
    )
    store.observe_user("private:10001", "今天只是打个招呼", now=1020)

    saved = _wait_for(
        path,
        lambda data: (
            "咖啡"
            in json.dumps(
                data.get("conversations", {})
                .get("private:10001", {})
                .get("structured_memory", {}),
                ensure_ascii=False,
            )
            and "喜欢的食物:奶茶"
            not in json.dumps(
                data.get("conversations", {})
                .get("private:10001", {})
                .get("structured_memory", {}),
                ensure_ascii=False,
            )
        ),
    )
    serialized = json.dumps(
        saved["conversations"]["private:10001"]["structured_memory"],
        ensure_ascii=False,
    )
    assert "咖啡" in serialized
    assert "喜欢的食物:奶茶" not in serialized


def test_l3_window_survives_store_recreation(tmp_path) -> None:
    path = tmp_path / "users.json"
    first = UserMemoryStore(path, _memory_config())
    for index in range(3):
        first.observe_user("private:10001", f"这是一条上下文消息{index}", now=1000 + index)

    second = UserMemoryStore(path, _memory_config())
    second.observe_user("private:10001", "重启后的新消息", now=1010)
    saved = json.loads(path.read_text(encoding="utf-8"))
    values = [
        entry.get("value")
        for entry in saved["conversations"]["private:10001"]["structured_memory"]["l3"]
    ]
    assert values[-2:] == ["这是一条上下文消息2", "重启后的新消息"]
