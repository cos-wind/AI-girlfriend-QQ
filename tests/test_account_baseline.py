"""账号系统开发前的行为快照（characterization tests）。

这些测试断言的是**今天**的行为，唯一用途是：引入账号维度之后逐条验证"没改坏"。
它们刻意不评判设计好坏，只把现状钉死。

判读方式：

* 全绿 → 账号改动没有改变既有行为。
* 变红 → 账号改动确实改变了行为。**这不一定是 bug**，但必须是有意的，
  并且修正断言时要能说清"为什么改、影响谁"。

覆盖范围（账号系统将要触碰的接缝）：

1. 记忆文档的顶层结构与 schema 版本号
2. 会话 key 的三种格式（私聊 / 群聊 / 群内成员）
3. 各格式会话记录的字段集合——账号化之后这里会多出 ``account_id``，
   届时本测试就是那个"必须显式确认的变更点"
4. 机器人账号身份的唯一来源：``.env`` 的 ``BOT_QQ``
5. 全局数据路径常量（今天不区分账号）
6. 评测库路径不允许运行中热切换（项目现有的"要重启"约定）
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from atri_qq_bot.config import load_config
from atri_qq_bot.insights.config import InsightsConfig
from atri_qq_bot.insights.runtime import InsightsRuntime
from atri_qq_bot.memory import UserMemoryStore
from atri_qq_bot.runtime import paths


PRIVATE_KEY = "private:10001"
GROUP_KEY = "group:20001"
GROUP_MEMBER_KEY = "group:20001:user:10001"

# 实测得到的字段集合（.scratch 里的探针脚本量出来的真实值，不是猜的）。
# 私聊与群聊的字段集合今天并不相同——私聊多出每日好感增量与空闲衰减记账，
# 群聊则多出 last_group_activity_at。这个差异本身就是需要钉住的现状。
PRIVATE_RECORD_FIELDS = {
    "affection_delta_date",
    "affection_initialized",
    "affection_negative_today",
    "affection_owner_profile",
    "affection_positive_today",
    "affection_score",
    "avg_user_chars",
    "emoji_count",
    "feature_counts",
    "group_activity_score",
    "history",
    "last_affection_idle_decay_at",
    "last_l2_decay_date",
    "last_user_at",
    "message_count",
    "proactive_awaiting_reply",
    "proactive_ignored_streak",
    "question_count",
    "structured_memory",
    "topic_words",
}

GROUP_RECORD_FIELDS = {
    "affection_initialized",
    "affection_owner_profile",
    "affection_score",
    "avg_user_chars",
    "emoji_count",
    "feature_counts",
    "group_activity_score",
    "history",
    "last_group_activity_at",
    "last_l2_decay_date",
    "last_user_at",
    "message_count",
    "proactive_awaiting_reply",
    "proactive_ignored_streak",
    "question_count",
    "structured_memory",
    "topic_words",
}


def _store_with_one_observation(tmp_path):
    memory_path = tmp_path / "users.json"
    store = UserMemoryStore(memory_path)
    for key in (PRIVATE_KEY, GROUP_KEY, GROUP_MEMBER_KEY):
        store.observe_user(key, "我平时晚上学习", now=1000)
    return json.loads(memory_path.read_text(encoding="utf-8"))


def test_memory_document_schema_is_stable(tmp_path) -> None:
    """记忆文档的顶层键与 schema 版本号。"""
    saved = _store_with_one_observation(tmp_path)

    assert set(saved) == {"version", "conversations"}
    # MEMORY_VERSION 目前是 2。这个数字变化意味着一次有意的记忆迁移。
    assert saved["version"] == 2


def test_conversation_keys_of_all_three_kinds_are_persisted(tmp_path) -> None:
    """三种会话 key 都直接作为 conversations 的键落盘，不做任何改写。

    账号化之后这里会变成 ``accounts -> conversations`` 两层，
    或者键本身带上账号维度；无论哪种，本条都会变红。
    """
    saved = _store_with_one_observation(tmp_path)

    conversations = saved["conversations"]
    assert PRIVATE_KEY in conversations
    assert GROUP_KEY in conversations
    assert GROUP_MEMBER_KEY in conversations


def test_private_conversation_record_fields_are_stable(tmp_path) -> None:
    saved = _store_with_one_observation(tmp_path)
    record = saved["conversations"][PRIVATE_KEY]

    assert set(record) == PRIVATE_RECORD_FIELDS


def test_group_conversation_record_fields_are_stable(tmp_path) -> None:
    saved = _store_with_one_observation(tmp_path)

    assert set(saved["conversations"][GROUP_KEY]) == GROUP_RECORD_FIELDS
    # 群内成员的记录今天与群记录同构。
    assert set(saved["conversations"][GROUP_MEMBER_KEY]) == GROUP_RECORD_FIELDS


def test_structured_memory_layers_are_stable(tmp_path) -> None:
    """结构化记忆的四层（L1/L2/L3 + 候选）以及历史的字段。"""
    saved = _store_with_one_observation(tmp_path)
    record = saved["conversations"][PRIVATE_KEY]

    assert set(record["structured_memory"]) == {"l1", "l2", "l3", "candidates"}
    assert record["history"], "首次 observe 应当写入一条历史"
    assert set(record["history"][0]) == {"at", "role", "text"}


def test_bot_qq_is_read_from_the_env_file(tmp_path) -> None:
    """机器人账号身份今天的唯一来源是 .env 的 BOT_QQ，没有账号注册表。"""
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_QQ=123456789\n", encoding="utf-8")

    config = load_config(env_file)

    assert config.bot_qq == 123456789


def test_data_paths_are_still_global_not_account_scoped(tmp_path) -> None:
    """记忆、检索、认知三条数据路径今天都是全局常量，不随账号变化。

    账号化之后这些路径应当由账号解析函数给出；本条变红是预期内的，
    因为"用户中心显示哪个账号"与"数据写到哪个库"必须同时切换。
    """
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_QQ=123456789\n", encoding="utf-8")

    config = load_config(env_file)

    assert config.memory_path == paths.DATA_DIR / "memory" / "users.json"
    assert (
        config.memory_retrieval_path
        == paths.DATA_DIR / "memory" / "semantic_memory.sqlite3"
    )
    assert config.cognition_state_path == paths.DATA_DIR / "cognition" / "state.sqlite3"
    # 三种会话共用一个记忆文件，没有按账号分库。
    assert config.memory_path == paths.MEMORY_PATH


def test_insights_database_path_cannot_be_swapped_at_runtime(tmp_path) -> None:
    """项目现有约定：运行中不热切换数据库路径，必须重启。

    见 ``src/atri_qq_bot/insights/runtime.py:47-48``。账号系统必须遵守同一条约定，
    否则换账号时会把 A 账号的评测写进 B 账号的库，而且不会报错。
    """
    config = replace(
        InsightsConfig.from_env(),
        database_path=tmp_path / "account-scoped.sqlite3",
    )
    runtime = InsightsRuntime(config)

    with pytest.raises(ValueError, match="请重启 ATRI"):
        asyncio.run(runtime.reload_config())
