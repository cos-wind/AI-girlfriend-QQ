"""账号数据布局与路径解析的测试（阶段 3a）。

两条硬约束：

1. **默认账号解析出来必须与今天逐字段相等**——现有账号一个新文件都不搬。
2. **非默认账号的数据必须完全落在自己的目录里**——串号在物理上不可能发生。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from atri_qq_bot.accounts import (
    AccountRegistry,
    account_data_paths,
    bootstrap_from_config,
    ensure_account_layout,
    resolve_config,
    resolve_insights_config,
)
from atri_qq_bot.config import load_config
from atri_qq_bot.insights.config import InsightsConfig
from atri_qq_bot.insights.runtime import InsightsRuntime

BOT_QQ = 900000002
OTHER_QQ = 900001003


def _config(tmp_path, *, enabled: bool = True):
    env_file = tmp_path / "config.env"
    env_file.write_text(f"BOT_QQ={BOT_QQ}\n", encoding="utf-8")
    return replace(
        load_config(env_file),
        account_system_enabled=enabled,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
    )


def _default_account(config):
    account = bootstrap_from_config(config)
    assert account is not None
    return account


def _other_account(config):
    registry = AccountRegistry(config.accounts_db_path)
    return registry.register(OTHER_QQ, confirmed=True, enabled=True)


# ---- account_data_paths -------------------------------------------------


def test_paths_are_none_for_no_account(tmp_path) -> None:
    assert account_data_paths(_config(tmp_path), None) is None


def test_default_account_keeps_todays_global_paths(tmp_path) -> None:
    config = _config(tmp_path)

    layout = account_data_paths(config, _default_account(config))

    assert layout is not None
    assert layout.is_default is True
    # root 为 None 就是"沿用全局路径、零搬迁"的标记。
    assert layout.root is None
    assert layout.memory_path == config.memory_path
    assert layout.memory_retrieval_path == config.memory_retrieval_path
    assert layout.cognition_state_path == config.cognition_state_path
    assert layout.sticker_capture_dir == config.sticker_capture_dir


def test_non_default_account_gets_its_own_directory(tmp_path) -> None:
    config = _config(tmp_path)
    # 先引导默认账号，再登记另一个——bootstrap 在注册表非空时不会再抢默认位。
    default_layout = account_data_paths(config, _default_account(config))

    layout = account_data_paths(config, _other_account(config))

    assert layout is not None
    assert default_layout is not None
    assert layout.is_default is False
    expected_root = tmp_path / "accounts" / f"qq-{OTHER_QQ}"
    assert layout.root == expected_root
    # 每一项都必须落在自己的目录里——任何一项漏掉都会造成跨账号读写。
    for path in (
        layout.memory_path,
        layout.memory_backup_dir,
        layout.memory_retrieval_path,
        layout.cognition_state_path,
        layout.insights_db_path,
        layout.qzone_db_path,
        layout.webui_dir,
        layout.prompt_dir,
        layout.sticker_capture_dir,
    ):
        assert expected_root in path.parents, f"{path} 没有落在账号目录内"
    # 与默认账号的全局路径不能有任何重叠。
    assert layout.memory_path != default_layout.memory_path
    assert layout.insights_db_path != default_layout.insights_db_path


def test_layout_public_dict_is_relative_and_serializable(tmp_path) -> None:
    config = _config(tmp_path)

    payload = account_data_paths(config, _other_account(config)).public_dict()

    assert payload["is_default"] is False
    assert payload["bot_qq"] == OTHER_QQ
    # 测试用的是 tmp 目录，不在 PROJECT_ROOT 下，所以这里是绝对路径；
    # 真实部署下会显示成 data/accounts/... 的相对路径。
    assert payload["memory_path"].endswith(f"qq-{OTHER_QQ}/memory/users.json")
    assert payload["insights_db_path"].endswith(
        f"qq-{OTHER_QQ}/insights/insights.sqlite3"
    )
    assert all(
        isinstance(value, (str, bool, int, type(None))) for value in payload.values()
    )


# ---- resolve_config -----------------------------------------------------


def test_resolve_config_for_default_account_is_field_for_field_identity(tmp_path) -> None:
    """这是"现有账号零搬迁"的核心保证：默认账号解析后与原配置逐字段相等。"""
    config = _config(tmp_path)

    resolved = resolve_config(config, _default_account(config))

    assert resolved == config
    assert resolved.bot_qq == BOT_QQ
    assert resolved.memory_path == config.memory_path


def test_resolve_config_for_non_default_account_rewrites_identity_and_paths(tmp_path) -> None:
    config = _config(tmp_path)

    resolved = resolve_config(config, _other_account(config))

    assert resolved.bot_qq == OTHER_QQ
    assert resolved.memory_path != config.memory_path
    assert resolved.memory_retrieval_path != config.memory_retrieval_path
    assert resolved.cognition_state_path != config.cognition_state_path
    assert resolved.sticker_capture_dir != config.sticker_capture_dir
    # 原配置是 frozen dataclass，不能被就地修改。
    assert config.bot_qq == BOT_QQ


def test_resolve_config_is_identity_without_account(tmp_path) -> None:
    config = _config(tmp_path)
    assert resolve_config(config, None) is config


# ---- ensure_account_layout ---------------------------------------------


def test_ensure_account_layout_creates_directories_for_non_default(tmp_path) -> None:
    config = _config(tmp_path)
    account = _other_account(config)
    assert not (tmp_path / "accounts" / f"qq-{OTHER_QQ}").exists()

    layout = ensure_account_layout(config, account)

    assert layout is not None
    for directory in (
        layout.memory_path.parent,
        layout.memory_backup_dir,
        layout.cognition_state_path.parent,
        layout.insights_db_path.parent,
        layout.qzone_db_path.parent,
        layout.webui_dir,
        layout.prompt_dir,
    ):
        assert directory.is_dir(), f"{directory} 未创建"


def test_ensure_account_layout_touches_nothing_for_default_account(tmp_path) -> None:
    config = _config(tmp_path)

    layout = ensure_account_layout(config, _default_account(config))

    assert layout is not None
    assert layout.root is None
    # 只应存在注册表文件，不应为默认账号多建任何目录。
    accounts_dir = tmp_path / "accounts"
    assert sorted(item.name for item in accounts_dir.iterdir()) == ["index.sqlite3"]


# ---- resolve_insights_config -------------------------------------------


def test_insights_config_unchanged_for_default_account(tmp_path) -> None:
    config = _config(tmp_path)
    base = InsightsConfig.from_env()

    assert resolve_insights_config(base, _default_account(config), config) == base


def test_insights_config_points_at_account_database_for_non_default(tmp_path) -> None:
    config = _config(tmp_path)
    account = _other_account(config)
    base = InsightsConfig.from_env()

    scoped = resolve_insights_config(base, account, config)

    assert scoped.database_path == tmp_path / "accounts" / f"qq-{OTHER_QQ}" / "insights" / "insights.sqlite3"
    # 其余字段不动。
    assert scoped is not base
    assert scoped.judge_model == base.judge_model


def test_insights_config_unchanged_without_account(tmp_path) -> None:
    base = InsightsConfig.from_env()
    assert resolve_insights_config(base, None, _config(tmp_path)) is base


# ---- 评测库路径的显式声明通道 ------------------------------------------


def test_reload_config_accepts_declared_matching_database_path(tmp_path) -> None:
    """账号系统用它防止 .env 的全局路径在重载时覆盖账号作用域的库。"""
    database = (tmp_path / "account.sqlite3").resolve()
    runtime = InsightsRuntime(
        replace(InsightsConfig.from_env(), database_path=database)
    )

    asyncio.run(runtime.reload_config(database_path=database))

    assert runtime.config.database_path == database


def test_reload_config_still_rejects_a_genuinely_different_path(tmp_path) -> None:
    """守卫仍然有效：声明一个不同的库依然报错，避免"配置指向新库、实际写旧库"。"""
    database = (tmp_path / "account.sqlite3").resolve()
    runtime = InsightsRuntime(
        replace(InsightsConfig.from_env(), database_path=database)
    )

    with pytest.raises(ValueError, match="请重启 ATRI"):
        asyncio.run(
            runtime.reload_config(database_path=tmp_path / "other.sqlite3")
        )
