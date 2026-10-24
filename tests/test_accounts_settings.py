"""账号级配置分层的测试（阶段 4a）。

两层模型：**`.env` 是全局默认，账号覆盖在注册表里**。没有覆盖行 = 继承。

`resolve_config` 在带覆盖时走 `load_config(overrides=...)`，所以覆盖会经过
loader 的完整钳制与类型校验。测试刻意验证了这一点（`MESSAGE_SPLIT_MAX_CHARS`
填 9999 会被钳到 200），并验证 `os.environ` 不被污染。
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from atri_qq_bot.accounts import (
    AccountRegistry,
    bootstrap_from_config,
    build_runtime_resources,
    resolve_account_settings,
    resolve_config,
)
from atri_qq_bot.config import load_config

BOT_QQ = 900000002
OTHER_QQ = 900001003


def _config(tmp_path, *, enabled: bool = True):
    root = tmp_path / "global"
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "\n".join(
            (
                f"BOT_QQ={BOT_QQ}",
                f"MEMORY_PATH={(root / 'memory' / 'users.json').as_posix()}",
                f"MEMORY_RETRIEVAL_PATH={(root / 'memory' / 'semantic.sqlite3').as_posix()}",
                f"COGNITION_STATE_PATH={(root / 'cognition' / 'state.sqlite3').as_posix()}",
                f"INSIGHTS_DB_PATH={(root / 'insights' / 'insights.sqlite3').as_posix()}",
                f"QZONE_AUTOMATION_DB={(root / 'qzone.sqlite3').as_posix()}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return replace(
        load_config(env_file),
        account_system_enabled=enabled,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
        memory_extraction_enabled=False,
        memory_backfill_enabled=False,
    )


def _accounts(config):
    registry = AccountRegistry(config.accounts_db_path)
    default = bootstrap_from_config(config)
    other = registry.register(OTHER_QQ, confirmed=True, enabled=True)
    return registry, default, other


# ---- load_config 的 overrides 通道 --------------------------------------


def test_overrides_are_applied(tmp_path) -> None:
    _config(tmp_path)  # 只为建好 tmp 目录

    scoped = load_config(overrides={"REPLY_MODE": "all", "MAX_TOKENS": "777"})

    assert scoped.reply_mode == "all"
    assert scoped.max_tokens == 777


def test_overrides_are_relative_to_the_env_not_to_the_passed_base(tmp_path) -> None:
    """记录一条**刻意的语义**：覆盖是相对 `.env` 全局默认计算的。

    所以 ``resolve_config(base, account, overrides=...)`` 里未覆盖的普通配置项
    来自 `.env`，而不是来自调用方传入的 ``base``。这与 WebUI 保存配置走同一条
    路径——`.env` 始终是全局默认的事实源。生产环境下 ``base`` 本身就是
    ``load_config()`` 的产物，两者一致。

    （附注：``load_config(env_file)`` 本身不是密闭的——``load_dotenv(override=True)``
    只覆盖文件里出现的键，``os.environ`` 里已有的其它键会漏进来。这是项目既有行为，
    所以这里不去构造"临时 env_file 与真实 .env 不同"的对比，改为逐项对齐断言。）
    """
    config = _config(tmp_path)
    account = bootstrap_from_config(config)

    scoped = resolve_config(config, account, overrides={"MAX_TOKENS": "777"})
    fresh = load_config()

    # 覆盖生效。
    assert scoped.max_tokens == 777
    # 未覆盖的普通配置项来自 .env。
    for field in ("reply_mode", "temperature", "frequency_penalty", "openai_model"):
        assert getattr(scoped, field) == getattr(fresh, field), field
    # 身份与账号作用域路径来自账号，不来自 .env。
    assert scoped.bot_qq == account.qq_int


def test_overrides_go_through_the_same_clamping_as_env(tmp_path) -> None:
    """覆盖不能绕过 loader 的范围钳制——这是复用 overrides 通道的全部意义。"""
    scoped = load_config(overrides={"MESSAGE_SPLIT_MAX_CHARS": "9999"})

    assert scoped.message_split_max_chars == 200


def test_overrides_do_not_pollute_the_process_environment() -> None:
    before = os.environ.get("MAX_TOKENS")

    load_config(overrides={"MAX_TOKENS": "1234"})

    assert os.environ.get("MAX_TOKENS") == before
    # 之后再加载也不会带着上一次的覆盖。
    assert load_config().max_tokens != 1234 or before == "1234"


def test_empty_overrides_behaves_like_no_overrides() -> None:
    assert load_config(overrides={}) == load_config()


# ---- 注册表的设置读写 ---------------------------------------------------


def test_settings_round_trip_preserves_types(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, _ = _accounts(config)

    registry.set_settings(
        default.account_id,
        {
            "REPLY_MODE": "all",
            "MAX_TOKENS": 512,
            "TEMPERATURE": 0.25,
            "STICKER_CAPTURE_ENABLED": False,
        },
    )

    settings = registry.settings(default.account_id)

    # JSON 保存，所以类型不会退化：整数不会变成字符串、布尔不会变成 "False"。
    assert settings["REPLY_MODE"] == "all"
    assert settings["MAX_TOKENS"] == 512
    assert settings["TEMPERATURE"] == 0.25
    assert settings["STICKER_CAPTURE_ENABLED"] is False


def test_setting_is_upserted_not_duplicated(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, _ = _accounts(config)

    registry.set_setting(default.account_id, "MAX_TOKENS", 100)
    registry.set_setting(default.account_id, "MAX_TOKENS", 200)

    assert registry.settings(default.account_id) == {"MAX_TOKENS": 200}
    assert registry.settings_count(default.account_id) == 1


def test_delete_setting_restores_inheritance(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, _ = _accounts(config)
    registry.set_setting(default.account_id, "MAX_TOKENS", 100)

    removed = registry.delete_setting(default.account_id, "MAX_TOKENS")

    assert removed is True
    assert registry.settings(default.account_id) == {}
    # 再删一次应该是 False，而不是报错。
    assert registry.delete_setting(default.account_id, "MAX_TOKENS") is False


def test_clear_settings_wipes_only_that_account(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, other = _accounts(config)
    registry.set_setting(default.account_id, "MAX_TOKENS", 100)
    registry.set_setting(other.account_id, "MAX_TOKENS", 200)

    cleared = registry.clear_settings(default.account_id)

    assert cleared == 1
    assert registry.settings(default.account_id) == {}
    assert registry.settings(other.account_id) == {"MAX_TOKENS": 200}


def test_setting_rows_carry_metadata_for_the_ui(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, _ = _accounts(config)
    registry.set_setting(default.account_id, "MAX_TOKENS", 300, now=1234.0)

    rows = registry.setting_rows(default.account_id)

    assert rows == [{"key": "MAX_TOKENS", "value": 300, "updated_at": 1234.0}]


def test_corrupt_value_does_not_break_reading_the_panel(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, _ = _accounts(config)
    registry.set_setting(default.account_id, "MAX_TOKENS", 300)

    # 直接写入坏 JSON，模拟手工改库或旧版本残留。
    import sqlite3

    connection = sqlite3.connect(config.accounts_db_path)
    try:
        connection.execute(
            "UPDATE account_settings SET value_json=? WHERE key=?",
            ("{not json", "MAX_TOKENS"),
        )
        connection.commit()
    finally:
        connection.close()

    rows = registry.setting_rows(default.account_id)

    # 坏数据原样返回字符串，而不是让整个面板读不出来。
    assert rows[0]["value"] == "{not json"


# ---- resolve_account_settings ------------------------------------------


def test_resolve_account_settings_is_empty_when_disabled(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)
    registry, default, _ = _accounts(config)
    registry.set_setting(default.account_id, "MAX_TOKENS", 100)

    # 账号系统关闭时账号级覆盖完全不参与。
    assert resolve_account_settings(config, default) == {}


def test_resolve_account_settings_is_empty_without_account(tmp_path) -> None:
    assert resolve_account_settings(_config(tmp_path), None) == {}


def test_resolve_account_settings_returns_the_rows(tmp_path) -> None:
    config = _config(tmp_path)
    registry, default, _ = _accounts(config)
    registry.set_setting(default.account_id, "MAX_TOKENS", 100)

    assert resolve_account_settings(config, default) == {"MAX_TOKENS": 100}


# ---- resolve_config 的两层合并 -----------------------------------------


def test_resolve_config_default_account_without_overrides_is_identity(tmp_path) -> None:
    """无覆盖时默认账号必须逐字段恒等——"现有账号零搬迁"的保证。"""
    config = _config(tmp_path)
    _registry, default, _ = _accounts(config)

    assert resolve_config(config, default) == config


def test_resolve_config_applies_account_overrides(tmp_path) -> None:
    config = _config(tmp_path)
    _registry, default, _ = _accounts(config)

    scoped = resolve_config(config, default, overrides={"REPLY_MODE": "all"})

    assert scoped.reply_mode == "all"
    # 账号作用域路径仍然由账号决定，不被覆盖影响。
    assert scoped.memory_path == config.memory_path
    assert scoped.bot_qq == BOT_QQ


def test_resolve_config_overrides_are_clamped_too(tmp_path) -> None:
    config = _config(tmp_path)
    _registry, default, _ = _accounts(config)

    scoped = resolve_config(
        config, default, overrides={"MESSAGE_SPLIT_MAX_CHARS": "99999"}
    )

    assert scoped.message_split_max_chars == 200


def test_resolve_config_overrides_do_not_touch_the_non_default_paths(tmp_path) -> None:
    config = _config(tmp_path)
    _registry, _default, other = _accounts(config)

    scoped = resolve_config(config, other, overrides={"REPLY_MODE": "private"})

    assert scoped.reply_mode == "private"
    assert scoped.bot_qq == OTHER_QQ
    # 身份与路径来自账号，只有普通配置项来自覆盖。
    assert scoped.memory_path != config.memory_path


# ---- 资源工厂自动带上账号设置 ------------------------------------------


def test_build_runtime_resources_picks_up_stored_settings(tmp_path) -> None:
    """端到端：往注册表里写一条覆盖 → 造资源时自动生效，不需要调用方记得传。"""
    config = _config(tmp_path)
    registry, _default, other = _accounts(config)
    registry.set_setting(other.account_id, "REPLY_MODE", "all")
    registry.set_setting(other.account_id, "MAX_TOKENS", 640)

    staged = build_runtime_resources(config, other, builders={}, required=set())

    assert staged.config.reply_mode == "all"
    assert staged.config.max_tokens == 640
    assert staged.config.bot_qq == OTHER_QQ


def test_build_runtime_resources_without_settings_keeps_globals(tmp_path) -> None:
    config = _config(tmp_path)
    _registry, default, _ = _accounts(config)

    staged = build_runtime_resources(config, default, builders={}, required=set())

    assert staged.config.reply_mode == config.reply_mode
    assert staged.config.max_tokens == config.max_tokens


def test_two_accounts_see_their_own_overrides(tmp_path) -> None:
    """同一进程里两个账号各自的覆盖互不影响。"""
    config = _config(tmp_path)
    registry, default, other = _accounts(config)
    registry.set_setting(default.account_id, "REPLY_MODE", "all")
    registry.set_setting(other.account_id, "REPLY_MODE", "private")

    staged_default = build_runtime_resources(
        config, default, builders={}, required=set()
    )
    staged_other = build_runtime_resources(config, other, builders={}, required=set())

    assert staged_default.config.reply_mode == "all"
    assert staged_other.config.reply_mode == "private"
