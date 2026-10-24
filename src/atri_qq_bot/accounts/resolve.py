"""把"当前是哪个账号"解析成账号作用域的运行配置。

这个模块是账号维度唯一的注入点。设计目标是让**引擎、OneBot 消息链路、人格模块
完全不需要知道"账号"这个概念存在**——它们继续收一个 ``BotConfig``，只是这个
``BotConfig`` 现在是账号作用域的（见 ``resolve_config``）。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from ..config import load_config
from .layout import AccountPaths, account_data_paths, ensure_account_layout
from .registry import (
    Account,
    AccountRegistry,
    account_id_for,
    bootstrap_from_config,
    qq_from_account_id,
    registry_for_config,
)


def current_account(
    config: Any,
    *,
    napcat_uin: int | str | None = None,
) -> Account | None:
    """解析当前账号。

    返回 ``None`` 表示"不要介入"——此时调用方必须继续使用 ``config.bot_qq``，
    行为与账号化之前逐条一致。

    判定顺序：

    1. ``ACCOUNT_SYSTEM_ENABLED=off``（默认）→ 返回 ``None``，账号系统完全不介入。
    2. 开启跟随（``ACCOUNT_FOLLOW_NAPCAT=on``）且拿到 NapCat 实际登录号 →
       以该号为准。**注意**：拿不到或字典里没有这个账号时也返回 ``None``，
       于是行为回落到今天的"账号不一致"（忽略全部消息 + 告警），
       不会因为换了个号就凭空产生数据。
    3. 否则 → 注册表里的默认账号（由 ``BOT_QQ`` 引导出来）。

    ``napcat_uin`` 由调用方从运行时状态里取（``runtime/control.py`` 的
    NapCat 状态文件里有 ``peer_uin``）。阶段 2 不接这条线，所以默认是 ``None``。
    """
    if not bool(getattr(config, "account_system_enabled", False)):
        return None

    registry = registry_for_config(config)
    follow = bool(getattr(config, "account_follow_napcat", False))

    if follow and napcat_uin is not None:
        try:
            account_id = account_id_for(napcat_uin)
        except ValueError:
            return None
        account = registry.get(account_id)
        if account is None or not account.enabled:
            # 未确认/未启用的账号不参与运行，行为等同今天的"账号不一致"。
            return None
        return account

    return registry.default_account()


def resolve_account_settings(config: Any, account: Account | None) -> dict[str, Any]:
    """取该账号的配置覆盖（键名与 .env 同名，见 ``config_admin.CONFIG_FIELDS``）。

    账号系统关闭、账号为空、或注册表读不出来时返回空字典——即"全部继承全局默认"。
    """
    if account is None:
        return {}
    if not bool(getattr(config, "account_system_enabled", False)):
        return {}
    try:
        return registry_for_config(config).settings(account.account_id)
    except Exception:
        # 注册表损坏不应该让换账号失败：退回"全部继承全局默认"。
        return {}


def resolve_config(
    base: Any,
    account: Account | None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> Any:
    """派生账号作用域的 ``BotConfig``。

    ``account`` 为 ``None`` 时原样返回 ``base``，所以"账号系统没介入"这条路径
    是零成本的。

    覆盖三类内容：

    * **身份**：``bot_qq``
    * **账号级配置覆盖**：``overrides``（键名与 .env 同名）。它走
      :func:`atri_qq_bot.config.load_config` 的 ``overrides`` 通道，因此
      **范围钳制与类型校验与 .env 完全一致**，不会出现"账号覆盖绕过校验"这种漂移。
      注意覆盖是**相对 .env 全局默认**计算的——与 WebUI 保存配置走同一条路径，
      .env 始终是全局默认的事实源。
    * **``BotConfig`` 上已有的账号作用域路径**：记忆、向量检索、认知状态、
      收到的表情归档

    ``default`` 账号且无覆盖时解析出来的结果与原配置**逐字段相等**（见
    ``account_data_paths`` 对默认账号的处理），这是"现有账号零搬迁"的保证。

    评测库、QQ 空间库、``data/webui/*.json``、人设目录不在 ``BotConfig`` 上，
    由 :func:`resolve_insights_config` 与 :class:`AccountPaths` 分别提供。
    """
    if account is None:
        return base

    layout = account_data_paths(base, account)
    if layout is None:  # pragma: no cover - account 非 None 时 layout 必然非 None
        return base

    scoped = load_config(overrides=overrides) if overrides else base

    return replace(
        scoped,
        bot_qq=account.qq_int,
        memory_path=layout.memory_path,
        memory_retrieval_path=layout.memory_retrieval_path,
        cognition_state_path=layout.cognition_state_path,
        sticker_capture_dir=layout.sticker_capture_dir,
    )


def resolve_insights_config(insights_config: Any, account: Account | None, base: Any) -> Any:
    """把评测配置的库路径指向该账号的库。

    ``BotConfig`` 上没有评测库路径——它由 ``InsightsConfig.from_env()`` 直接读
    ``INSIGHTS_DB_PATH`` 得到，所以只能在这一层覆盖。``account`` 为 ``None`` 或
    默认账号时原样返回，不改既有行为。
    """
    if account is None:
        return insights_config
    layout = account_data_paths(base, account)
    if layout is None:
        return insights_config
    return replace(insights_config, database_path=layout.insights_db_path)


__all__ = [
    "Account",
    "AccountPaths",
    "AccountRegistry",
    "account_data_paths",
    "account_id_for",
    "bootstrap_from_config",
    "current_account",
    "ensure_account_layout",
    "qq_from_account_id",
    "registry_for_config",
    "resolve_account_settings",
    "resolve_config",
    "resolve_insights_config",
]
