from __future__ import annotations

import json

import atri_qq_bot.memory as memory_module
from atri_qq_bot.memory import UserMemoryStore
from atri_webui.memory_admin import MemoryAdmin


def test_memory_writes_traits_events_and_session_context_to_separate_layers(tmp_path) -> None:
    memory_path = tmp_path / "users.json"
    store = UserMemoryStore(memory_path)

    store.observe_user("private:10001", "我喜欢咖啡", now=1000)
    store.observe_user("private:10001", "我喜欢咖啡", now=1001)
    store.observe_user("private:10001", "我平时晚上学习", now=1002)
    store.observe_user("private:10001", "我平时晚上学习", now=1003)
    store.observe_user("private:10001", "明天有考试", now=1004)
    store.observe_user("private:10001", "现在正在讨论记忆系统", now=1005)
    store.observe_user("private:10001", "谢谢你", now=1006)
    store.observe_user("private:10001", "哈哈", now=1007)

    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    structured = saved["conversations"]["private:10001"]["structured_memory"]

    assert any(entry["value"] == "咖啡" for entry in structured["l1"])
    assert any(entry["value"] == "晚上学习" for entry in structured["l1"])
    assert any("考试" in entry["value"] for entry in structured["l2"])
    assert not any(entry.get("value") == "谢谢你" for entry in structured["l2"])
    assert any(entry["value"] == "现在正在讨论记忆系统" for entry in structured["l3"])
    assert not any(entry.get("value") == "哈哈" for entry in structured["l1"] + structured["l2"] + structured["l3"])

    detail = MemoryAdmin(memory_path, tmp_path / "backups").detail("id=private%3A10001")
    assert any(entry["value"] == "咖啡" for entry in detail["layers"]["l1"])
    assert any("考试" in entry["value"] for entry in detail["layers"]["l2"])
    assert any(entry["text"] == "现在正在讨论记忆系统" for entry in detail["layers"]["l3"])
    assert "哈哈" not in detail["natural"]


def test_memory_save_failure_does_not_break_message_path(tmp_path, monkeypatch) -> None:
    memory_path = tmp_path / "users.json"
    store = UserMemoryStore(memory_path)
    original_dump = memory_module.json.dump
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise MemoryError("simulated memory pressure")
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(memory_module.json, "dump", fail_once)
    # 保存失败不能让消息处理函数抛出异常。
    store.observe_user("private:10001", "这条消息仍然应该得到回复", now=1000)

    assert not memory_path.exists()
    assert store._save_failure_count == 1

    # 模拟内存恢复；退避结束后仍可继续正常落盘。
    store._save_retry_after = 0.0
    store.observe_user("private:10001", "记忆应该继续保存", now=1001)
    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    assert saved["conversations"]["private:10001"]["message_count"] == 2
