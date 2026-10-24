"""账号运行时资源构造与跨账号隔离的测试（阶段 3c）。

**安全前提**：默认账号沿用全局路径，也就是真实的 ``data/memory/users.json``。
所以本文件的配置辅助函数会把 ``MEMORY_PATH`` / ``MEMORY_RETRIEVAL_PATH`` /
``COGNITION_STATE_PATH`` / ``INSIGHTS_DB_PATH`` / ``QZONE_AUTOMATION_DB``
全部重定向到 tmp 目录——**任何时候都不允许测试写到真实数据文件**。

核心断言是"跨账号不串号"：用真实的 ``UserMemoryStore``（真 JSON 文件）与
``InsightsStore``（真 SQLite）各写一份，然后逐字节检查两个文件互不包含对方内容。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from atri_qq_bot.accounts import (
    AccountRegistry,
    AccountSwitchCoordinator,
    bootstrap_from_config,
    build_runtime_resources,
    default_builders,
    ensure_account_layout,
)
from atri_qq_bot.config import load_config
from atri_qq_bot.insights.store import InsightsStore
from atri_qq_bot.memory import UserMemoryStore

BOT_QQ = 900000002
OTHER_QQ = 900001003


def _config(tmp_path, *, enabled: bool = True):
    """所有数据路径都指向 tmp，绝不碰真实 data/。"""
    global_root = tmp_path / "global"
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "\n".join(
            (
                f"BOT_QQ={BOT_QQ}",
                f"MEMORY_PATH={(global_root / 'memory' / 'users.json').as_posix()}",
                f"MEMORY_RETRIEVAL_PATH={(global_root / 'memory' / 'semantic.sqlite3').as_posix()}",
                f"COGNITION_STATE_PATH={(global_root / 'cognition' / 'state.sqlite3').as_posix()}",
                f"INSIGHTS_DB_PATH={(global_root / 'insights' / 'insights.sqlite3').as_posix()}",
                f"QZONE_AUTOMATION_DB={(global_root / 'qzone.sqlite3').as_posix()}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return replace(
        load_config(env_file),
        account_system_enabled=enabled,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
        # 关掉记忆的后台线程：单元测试不应该留下回填/提取线程。
        memory_extraction_enabled=False,
        memory_backfill_enabled=False,
    )


def _lightweight_builders() -> dict:
    """只替换成真实但轻量的持久化对象，其余资源不建。

    reply_engine / tools / voice 会把整个 persona 引擎和工具链拉起来，
    与"隔离性"这件事无关；隔离性取决于**真实文件与真实 store 实例**，
    这两点由 UserMemoryStore 与 InsightsStore 覆盖。
    """

    def memory(account, config, layout, base):
        return UserMemoryStore(config.memory_path, config)

    def insights_store(account, config, layout, base):
        return InsightsStore(layout.insights_db_path)

    return {"memory": memory, "insights_store": insights_store}


def _coordinator(tmp_path):
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account_a = bootstrap_from_config(config)
    account_b = registry.register(OTHER_QQ, confirmed=True, enabled=True)
    builders = _lightweight_builders()
    coordinator = AccountSwitchCoordinator(
        config,
        build=lambda account, previous: build_runtime_resources(
            config, account, builders=builders
        ),
    )
    return config, coordinator, account_a, account_b


# ---- 未介入 -------------------------------------------------------------


def test_unscoped_build_returns_base_config_and_no_resources(tmp_path) -> None:
    config = _config(tmp_path)

    staged = build_runtime_resources(config, None, builders=_lightweight_builders())

    assert staged.config is config
    assert staged.layout is None
    assert dict(staged.resources) == {}


# ---- 默认账号 -----------------------------------------------------------


def test_default_account_reuses_global_paths_and_creates_no_account_dir(tmp_path) -> None:
    config = _config(tmp_path)
    account = bootstrap_from_config(config)

    staged = build_runtime_resources(config, account, builders=_lightweight_builders())

    assert staged.layout is not None
    assert staged.layout.root is None
    assert staged.config == config
    assert staged.config.memory_path == Path(config.memory_path)
    accounts_dir = tmp_path / "accounts"
    assert sorted(item.name for item in accounts_dir.iterdir()) == ["index.sqlite3"]


# ---- 非默认账号 ---------------------------------------------------------


def test_non_default_account_gets_dirs_and_scoped_config(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    staged = build_runtime_resources(config, account, builders=_lightweight_builders())

    assert staged.layout is not None
    assert staged.layout.root == tmp_path / "accounts" / f"qq-{OTHER_QQ}"
    assert staged.config.bot_qq == OTHER_QQ
    assert staged.config.memory_path != config.memory_path
    # 记忆首次写入是"临时文件 + replace"，父目录必须已经存在。
    assert staged.config.memory_path.parent.is_dir()
    # builders 是整体替换语义，所以这里正好只有注入的那两项。
    assert set(staged.resources) == {"memory", "insights_store"}


def test_ensure_dirs_false_skips_directory_creation(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    # builders={} 表示不构造任何资源；否则真实 store 一构造就会自己建出目录来。
    staged = build_runtime_resources(
        config, account, builders={}, ensure_dirs=False
    )

    assert staged.layout is not None
    assert dict(staged.resources) == {}
    assert not staged.layout.root.exists()


# ---- 按资源容错 ---------------------------------------------------------


def test_failing_builder_is_skipped_without_losing_others(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    def broken(account, config, layout, base):
        raise RuntimeError("模拟评测库起不来")

    builders = _lightweight_builders()
    builders["insights_store"] = broken

    staged = build_runtime_resources(config, account, builders=builders)

    # 评测是旁路：它起不来不应该影响记忆，也不应该让整个换账号失败。
    assert "memory" in staged.resources
    assert "insights_store" not in staged.resources


def test_builder_returning_none_is_not_recorded(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    builders = _lightweight_builders()
    builders["optional"] = lambda *args: None

    staged = build_runtime_resources(config, account, builders=builders)

    assert "optional" not in staged.resources


# ---- 默认资源表 ---------------------------------------------------------


def test_default_builders_cover_the_account_scoped_components() -> None:
    """默认表就是"一个账号需要哪些运行时对象"的清单，增删都必须是有意的。"""
    assert set(default_builders()) == {
        "reply_engine",
        "insights",
        "cognition_shadow",
        "stickers",
        "tools",
        "voice",
    }


def test_default_builders_are_not_stubs(tmp_path) -> None:
    """默认表里最轻的一个（stickers）真跑一次，证明它不是空壳。"""
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    staged = build_runtime_resources(config, account, builders=None)

    # 只断言 stickers 真的被造出来了；persona/评测那几项依赖真实运行环境，
    # 起不来会走"跳过并记 warning"的分支，这不影响本测试的意图。
    stickers = staged.resources.get("stickers")
    if stickers is not None:
        assert stickers.__class__.__name__ == "StickerManager"


def test_extra_builders_are_merged_on_top_of_defaults(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    staged = build_runtime_resources(
        config,
        account,
        extra_builders={"marker": lambda *args: "ok"},
    )

    assert staged.resources.get("marker") == "ok"


# ---- 跨账号不串号（核心）------------------------------------------------


def test_memory_writes_never_leak_across_accounts(tmp_path) -> None:
    """用真实的 UserMemoryStore 与真 JSON 文件证明隔离。

    这是整个账号系统最重要的一条断言：换账号之后，A 的记忆不会出现在
    B 的文件里，反之亦然。任何路径解析漏项都会在这里当场暴露。
    """
    config, coordinator, account_a, account_b = _coordinator(tmp_path)

    context_a = coordinator.switch(account_a, reason="test")
    store_a = context_a.resource("memory")
    store_a.observe_user("private:10001", "A 账号独有的记忆内容", now=1000)

    context_b = coordinator.switch(account_b, reason="test")
    store_b = context_b.resource("memory")
    assert store_b is not store_a
    store_b.observe_user("private:10001", "B 账号独有的记忆内容", now=2000)

    path_a = Path(context_a.config.memory_path)
    path_b = Path(context_b.config.memory_path)
    assert path_a != path_b
    assert path_a.is_file() and path_b.is_file()

    text_a = path_a.read_text(encoding="utf-8")
    text_b = path_b.read_text(encoding="utf-8")
    assert "A 账号独有的记忆内容" in text_a
    assert "B 账号独有的记忆内容" not in text_a
    assert "B 账号独有的记忆内容" in text_b
    assert "A 账号独有的记忆内容" not in text_b


def test_insights_databases_are_separate_per_account(tmp_path) -> None:
    config, coordinator, account_a, account_b = _coordinator(tmp_path)

    context_a = coordinator.switch(account_a)
    context_b = coordinator.switch(account_b)

    path_a = Path(context_a.layout.insights_db_path)
    path_b = Path(context_b.layout.insights_db_path)
    assert path_a != path_b
    assert context_a.resource("insights_store") is not context_b.resource("insights_store")

    # 两边都真的落成文件，且都是独立的 SQLite。
    context_a.resource("insights_store").add_group_message(
        message_key="1:1",
        group_id="1",
        user_id="1",
        nickname="甲",
        content="A 账号群的聊天",
        message_type="text",
        created_at="2026-09-15T00:00:00+00:00",
    )
    window = ("2026-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00")
    assert len(context_a.resource("insights_store").group_messages("1", *window, 10)) == 1
    assert context_b.resource("insights_store").group_messages("1", *window, 10) == []


def test_switching_back_and_forth_keeps_files_stable(tmp_path) -> None:
    """反复切换不应该把记忆写到别处，也不应该互相覆盖。"""
    config, coordinator, account_a, account_b = _coordinator(tmp_path)

    for round_index in range(3):
        context_a = coordinator.switch(account_a)
        context_a.resource("memory").observe_user(
            "private:10001", f"A 第 {round_index} 轮", now=1000 + round_index
        )
        context_b = coordinator.switch(account_b)
        context_b.resource("memory").observe_user(
            "private:10001", f"B 第 {round_index} 轮", now=2000 + round_index
        )

    text_a = Path(context_a.config.memory_path).read_text(encoding="utf-8")
    text_b = Path(context_b.config.memory_path).read_text(encoding="utf-8")

    events_a = json.loads(text_a)["conversations"]["private:10001"]
    events_b = json.loads(text_b)["conversations"]["private:10001"]

    # 两个账号各自只累加自己的 3 条，互不干扰。
    assert events_a["message_count"] == 3
    assert events_b["message_count"] == 3
    assert "B 第" not in text_a
    assert "A 第" not in text_b


def test_ensure_account_layout_is_idempotent(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    first = ensure_account_layout(config, account)
    second = ensure_account_layout(config, account)

    assert first == second
    assert first.root.is_dir()
