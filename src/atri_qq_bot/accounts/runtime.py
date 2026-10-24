"""账号作用域运行时资源的构造。

热切换要求"整体重建 + 原子换引用"，所以每个账号都需要一整套重新构造的对象。
这个模块把"怎么造"集中在一处，并允许注入，便于测试用真实但轻量的对象验证隔离性。

设计要点：

* **按资源容错**：某个资源构造失败只跳过它并记 warning，不影响其它资源。
  这和项目既有立场一致——评测/总结/认知都是旁路，初始化失败不应打断 QQ 回复。
* **未介入时返回空资源**：``account is None`` 直接返回 ``resources={}``，
  协调器那边还有一条不变量会再兜一次。
* **真实实现延迟导入**：``atri_qq_bot.accounts`` 在 import 时不应该拉起
  persona / onebot / 评测这些重模块，否则会形成循环依赖并拖慢纯数据层测试。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .layout import AccountPaths, account_data_paths, ensure_account_layout
from .registry import Account
from .resolve import resolve_account_settings, resolve_config, resolve_insights_config
from .switch import AccountResources

LOGGER = logging.getLogger("atri.accounts.runtime")

# (account, scoped_config, layout, base_config) -> 资源对象；返回 None 表示不可用。
BuilderFn = Callable[[Account, Any, AccountPaths, Any], Any]


def _build_reply_engine(
    account: Account, config: Any, layout: AccountPaths, base_config: Any
) -> Any:
    from ..persona import AtriReplyEngine

    return AtriReplyEngine(config)


def _build_insights(
    account: Account, config: Any, layout: AccountPaths, base_config: Any
) -> Any:
    from ..insights.config import InsightsConfig
    from ..insights.runtime import InsightsRuntime

    scoped = resolve_insights_config(InsightsConfig.from_env(), account, base_config)
    return InsightsRuntime(scoped)


def _build_cognition_shadow(
    account: Account, config: Any, layout: AccountPaths, base_config: Any
) -> Any:
    if not bool(getattr(config, "cognition_shadow_enabled", False)):
        return None
    from ..cognition import CognitionShadowRunner

    return CognitionShadowRunner.from_config(config)


def _build_stickers(
    account: Account, config: Any, layout: AccountPaths, base_config: Any
) -> Any:
    from ..stickers import StickerManager

    return StickerManager(
        config.sticker_dir,
        config.sticker_trigger_file,
        config.sticker_capture_dir,
    )


def _build_tools(
    account: Account, config: Any, layout: AccountPaths, base_config: Any
) -> Any:
    from ..toolbox import ToolAnalyzer

    return ToolAnalyzer(config)


def _build_voice(
    account: Account, config: Any, layout: AccountPaths, base_config: Any
) -> Any:
    from ..voice import VoiceManager

    return VoiceManager(config)


def default_builders() -> dict[str, BuilderFn]:
    """默认的资源构造表。返回新字典，调用方可以安全地增删。"""
    return {
        "reply_engine": _build_reply_engine,
        "insights": _build_insights,
        "cognition_shadow": _build_cognition_shadow,
        "stickers": _build_stickers,
        "tools": _build_tools,
        "voice": _build_voice,
    }


def build_runtime_resources(
    base_config: Any,
    account: Account | None,
    *,
    builders: dict[str, BuilderFn] | None = None,
    extra_builders: dict[str, BuilderFn] | None = None,
    ensure_dirs: bool = True,
    required: frozenset[str] | set[str] = frozenset({"reply_engine"}),
) -> AccountResources:
    """为一个账号构造完整的运行时资源。

    ``builders`` **整体替换**默认表（传 ``{}`` 表示什么资源都不建），
    ``extra_builders`` 则是在默认表上**追加/覆盖**若干项——例如 WebUI 想额外造一个
    ``memory_admin``，但不希望丢掉 ``reply_engine``。

    两者语义刻意分开：如果 ``builders`` 也是合并语义，那么"只想注入两个轻量对象"
    的测试就被迫把 persona 引擎和工具链一起拉起来。

    ``required`` 里的资源构造失败时**整体抛错**，而不是跳过。这一点很关键：
    协调器已经保证"``build`` 抛异常则当前上下文保持原样"，所以"新账号的回复引擎
    起不来"会变成"这次切换不生效、继续用旧账号"，而不是装上一个没有回复引擎的
    上下文把机器人弄哑。其余资源（评测、认知……）失败仍然只跳过。

    ``ensure_dirs=True`` 时会先建好账号目录——非默认账号第一次启用时必须先有目录，
    否则记忆初次的原子写（临时文件 + replace）会因为父目录不存在而失败。
    """
    if account is None:
        # 未介入：原样返回基础配置，且不带任何账号资源。
        return AccountResources(config=base_config, layout=None, resources={})

    if ensure_dirs:
        layout = ensure_account_layout(base_config, account)
    else:
        layout = account_data_paths(base_config, account)
    if layout is None:  # pragma: no cover - account 非 None 时必然非 None
        return AccountResources(config=base_config, layout=None, resources={})

    scoped_config = resolve_config(
        base_config, account, overrides=resolve_account_settings(base_config, account)
    )

    if builders is None:
        table = default_builders()
        if extra_builders:
            table.update(extra_builders)
    else:
        table = dict(builders)

    resources: dict[str, Any] = {}
    for name, builder in table.items():
        try:
            value = builder(account, scoped_config, layout, base_config)
        except Exception as exc:
            if name in required:
                raise RuntimeError(
                    f"账号 {account.account_id} 的必需资源 {name} 构造失败：{exc}"
                ) from exc
            # 旁路资源不可用时只跳过它：换账号不应该因为评测/认知起不来就整体失败。
            LOGGER.warning("账号资源 %s 构造失败，已跳过：%s", name, exc)
            continue
        if value is None:
            if name in required:
                raise RuntimeError(
                    f"账号 {account.account_id} 的必需资源 {name} 返回了空值"
                )
            continue
        resources[name] = value

    return AccountResources(
        config=scoped_config,
        layout=layout,
        resources=resources,
    )


__all__ = ["BuilderFn", "build_runtime_resources", "default_builders"]
