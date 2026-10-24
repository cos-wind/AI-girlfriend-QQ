"""账号管理系统。

方案与阶段进度见 ``docs/account_system/``。

对外只暴露三个函数，其余都是实现细节：

* :func:`resolve_account` —— 登记/查询账号
* :func:`current_account` —— 当前是哪个账号
* :func:`resolve_config` —— 派生账号作用域的 BotConfig

这样引擎、OneBot 消息链路和人格模块都不需要知道"账号"这个概念存在。
"""

from __future__ import annotations

from .layout import (
    AccountPaths,
    account_data_paths,
    account_dir_name,
    accounts_root,
    ensure_account_layout,
)
from .registry import (
    Account,
    AccountRegistry,
    PLATFORM_QQ,
    SCHEMA_VERSION,
    account_id_for,
    bootstrap_from_config,
    qq_from_account_id,
    registry_for_config,
)
from .resolve import (
    current_account,
    resolve_account_settings,
    resolve_config,
    resolve_insights_config,
)
from .runtime import build_runtime_resources, default_builders
from .switch import (
    AccountContext,
    AccountResources,
    AccountSwitchCoordinator,
    SwitchEvent,
)


def resolve_account(config: object, qq: int | str) -> Account | None:
    """按 QQ 号查询账号（不存在的返回 None，不隐式创建）。

    账号系统关闭时直接返回 ``None`` 且**不创建任何文件**——这正是"开关关着就等于
    今天的代码路径"这条承诺的一部分。
    """
    if not bool(getattr(config, "account_system_enabled", False)):
        return None
    registry = registry_for_config(config)
    try:
        account_id = account_id_for(qq)
    except ValueError:
        return None
    return registry.get(account_id)


__all__ = [
    "Account",
    "AccountContext",
    "AccountPaths",
    "AccountRegistry",
    "AccountResources",
    "AccountSwitchCoordinator",
    "PLATFORM_QQ",
    "SCHEMA_VERSION",
    "SwitchEvent",
    "account_data_paths",
    "account_dir_name",
    "account_id_for",
    "accounts_root",
    "bootstrap_from_config",
    "build_runtime_resources",
    "current_account",
    "default_builders",
    "ensure_account_layout",
    "qq_from_account_id",
    "registry_for_config",
    "resolve_account",
    "resolve_account_settings",
    "resolve_config",
    "resolve_insights_config",
]
