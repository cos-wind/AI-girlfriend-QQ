"""账号注册表与账号解析的测试（阶段 2）。

这一阶段的硬约束是**行为零变化**：账号系统默认关闭，关闭时不该创建任何文件、
不该改变任何既有行为。所以这里既测"注册表本身工作正常"，也测"关着的时候什么都不做"。
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from atri_qq_bot.accounts import (
    AccountRegistry,
    account_id_for,
    bootstrap_from_config,
    current_account,
    qq_from_account_id,
    resolve_account,
    resolve_config,
)
from atri_qq_bot.accounts.registry import SCHEMA_VERSION
from atri_qq_bot.config import load_config

BOT_QQ = 900000002
OTHER_QQ = 900001003


def _config(tmp_path, *, enabled: bool = True, follow: bool = False):
    """构造一个指向 tmp 的配置，不碰真实 data/ 目录。"""
    env_file = tmp_path / "config.env"
    env_file.write_text(f"BOT_QQ={BOT_QQ}\n", encoding="utf-8")
    base = load_config(env_file)
    return replace(
        base,
        account_system_enabled=enabled,
        account_follow_napcat=follow,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
    )


# ---- account_id 规范 ----------------------------------------------------


def test_account_id_round_trips() -> None:
    assert account_id_for(900000002) == "qq:900000002"
    assert account_id_for("900000002") == "qq:900000002"
    assert qq_from_account_id("qq:900000002") == "900000002"


@pytest.mark.parametrize("bad", ["", "abc", "qq:", "qq:12a", "qq: 123"])
def test_invalid_input_is_rejected_by_both_helpers(bad: str) -> None:
    with pytest.raises(ValueError):
        account_id_for(bad)
    with pytest.raises(ValueError):
        qq_from_account_id(bad)


def test_bare_digits_are_valid_for_account_id_but_not_for_qq_from_account_id() -> None:
    # 裸号码是 account_id_for 的合法输入（它负责补前缀）；
    # 但 qq_from_account_id 要求已经带前缀的主键。
    assert account_id_for("900000002") == "qq:900000002"
    with pytest.raises(ValueError):
        qq_from_account_id("900000002")


# ---- 建表与 schema 版本 -------------------------------------------------


def test_registry_creates_schema_with_user_version(tmp_path) -> None:
    path = tmp_path / "accounts" / "index.sqlite3"
    AccountRegistry(path)

    assert path.is_file()
    connection = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        assert "accounts" in tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()


def test_registry_construction_is_idempotent(tmp_path) -> None:
    path = tmp_path / "accounts" / "index.sqlite3"
    first = AccountRegistry(path)
    first.register(BOT_QQ, display_name="亚托莉", is_default=True, confirmed=True)

    second = AccountRegistry(path)

    assert second.count() == 1
    assert second.get_by_qq(BOT_QQ) is not None


# ---- 登记、去重、默认账号 -----------------------------------------------


def test_register_is_idempotent_and_keeps_manual_edits(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "index.sqlite3")
    created = registry.register(BOT_QQ, display_name="亚托莉", is_default=True)

    registry.update(created.account_id, display_name="改过的名字")
    again = registry.register(BOT_QQ, display_name="不该覆盖")

    # 重复登记不能把人工改过的字段冲掉。
    assert again.display_name == "改过的名字"


def test_default_account_is_unique(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "index.sqlite3")
    registry.register(BOT_QQ, is_default=True)
    registry.register(OTHER_QQ, is_default=True)

    accounts = registry.list_all()
    defaults = [item for item in accounts if item.is_default]

    assert len(defaults) == 1
    assert defaults[0].qq == str(OTHER_QQ)
    # 默认账号排在最前，方便 WebUI 直接展示。
    assert accounts[0].qq == str(OTHER_QQ)


def test_update_rejects_unknown_fields(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "index.sqlite3")
    created = registry.register(BOT_QQ)

    updated = registry.update(created.account_id, not_a_column="x", display_name="ok")

    assert updated is not None
    assert updated.display_name == "ok"


def test_update_returns_none_for_unknown_account(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "index.sqlite3")
    assert registry.update("qq:1", display_name="x") is None


# ---- NapCat 发现 --------------------------------------------------------


def test_observe_from_napcat_registers_unconfirmed_first_time(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "index.sqlite3")

    account, discovered = registry.observe_from_napcat(OTHER_QQ, now=1000.0)

    assert discovered is True
    assert account.qq == str(OTHER_QQ)
    # 首次发现必须是"未确认且未启用"：在用户确认之前不能凭空获得数据区，
    # 行为要等同今天的"账号不一致"。
    assert account.confirmed is False
    assert account.enabled is False
    assert account.last_login_at == 1000.0


def test_observe_from_napcat_is_not_discovery_twice(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "index.sqlite3")
    registry.observe_from_napcat(OTHER_QQ, now=1000.0)

    account, discovered = registry.observe_from_napcat(OTHER_QQ, now=2000.0)

    assert discovered is False
    assert account.last_login_at == 2000.0
    assert registry.count() == 1


# ---- 从 BOT_QQ 引导 -----------------------------------------------------


def test_bootstrap_creates_confirmed_default_from_bot_qq(tmp_path) -> None:
    config = _config(tmp_path)

    account = bootstrap_from_config(config)

    assert account is not None
    assert account.qq == str(BOT_QQ)
    assert account.is_default is True
    assert account.confirmed is True
    assert account.enabled is True


def test_bootstrap_is_idempotent(tmp_path) -> None:
    config = _config(tmp_path)
    first = bootstrap_from_config(config)
    second = bootstrap_from_config(config)

    assert first is not None and second is not None
    assert first.account_id == second.account_id
    assert AccountRegistry(config.accounts_db_path).count() == 1


def test_bootstrap_does_not_steal_default_when_registry_has_others(tmp_path) -> None:
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    registry.register(OTHER_QQ, is_default=True, confirmed=True)

    account = bootstrap_from_config(config)

    # 注册表里已经有别的账号时，不要拿 BOT_QQ 去抢默认位。
    assert account is not None
    assert account.qq == str(OTHER_QQ)
    assert registry.count() == 1


def test_bootstrap_returns_none_when_bot_qq_unset(tmp_path) -> None:
    env_file = tmp_path / "config.env"
    env_file.write_text("BOT_QQ=0\n", encoding="utf-8")
    config = replace(
        load_config(env_file),
        account_system_enabled=True,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
    )

    assert bootstrap_from_config(config) is None
    assert not config.accounts_db_path.exists()


# ---- 开关关闭时什么都不做（零行为变化的核心保证）-----------------------


def test_everything_is_inert_when_account_system_disabled(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)

    assert current_account(config) is None
    assert resolve_account(config, BOT_QQ) is None
    # 关闭时绝不能创建 data/accounts 下的任何文件。
    assert not config.accounts_db_path.exists()
    assert not config.accounts_db_path.parent.exists()


def test_resolve_config_is_identity_when_account_is_none(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)

    assert resolve_config(config, None) is config


# ---- current_account 的判定顺序 ----------------------------------------


def test_current_account_uses_default_when_following_is_off(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    bootstrap_from_config(config)

    account = current_account(config)

    assert account is not None
    assert account.qq == str(BOT_QQ)


def test_current_account_prefers_napcat_login_when_following(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=True)
    bootstrap_from_config(config)
    registry = AccountRegistry(config.accounts_db_path)
    registry.register(OTHER_QQ, confirmed=True, enabled=True)

    account = current_account(config, napcat_uin=OTHER_QQ)

    assert account is not None
    assert account.qq == str(OTHER_QQ)


def test_current_account_falls_back_to_none_for_unconfirmed_napcat_account(
    tmp_path,
) -> None:
    """跟随模式下遇到未确认的新账号时返回 None。

    这一点是阶段 3 安全性的关键：返回值 None 意味着调用方继续用 ``config.bot_qq``，
    于是行为回落到今天的"账号不一致"（忽略全部消息 + 告警）——
    不会因为 NapCat 换了个号就凭空给新账号建数据区。
    """
    config = _config(tmp_path, enabled=True, follow=True)
    bootstrap_from_config(config)
    AccountRegistry(config.accounts_db_path).observe_from_napcat(OTHER_QQ)

    assert current_account(config, napcat_uin=OTHER_QQ) is None


def test_current_account_ignores_garbage_napcat_uin(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=True)
    bootstrap_from_config(config)

    assert current_account(config, napcat_uin="not-a-qq") is None


# ---- resolve_config 的账号作用域 ---------------------------------------


def test_resolve_config_applies_account_identity(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True)

    resolved = resolve_config(config, account)

    assert resolved.bot_qq == OTHER_QQ
    # 阶段 3a 起，非默认账号的数据路径也一并切到账号目录（这是有意的行为变更，
    # 见 docs/account_system/03-account-follow-napcat.md）。
    assert resolved.memory_path != config.memory_path
    assert resolved.memory_path.parent.parent.parent == config.accounts_db_path.parent
    assert resolve_config(config, account) is not resolved
    # 原配置不能被就地修改（BotConfig 是 frozen dataclass）。
    assert config.bot_qq == BOT_QQ
    assert config.memory_path.parent.name == "memory"
