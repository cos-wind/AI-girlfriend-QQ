"""OneBot 侧账号接线（阶段 3c-2）。

用**轻量 server 桩**而不是真的起 OneBot 服务：这里要验证的是"跟随策略"与
"换引用"这两件事的正确性，不需要真实 websocket。

安全前提：所有数据路径都重定向到 tmp，绝不创建/写入真实的 ``data/`` 文件
（除了注册表本身，它也指向 tmp）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace

from atri_qq_bot.accounts import AccountRegistry, build_runtime_resources
from atri_qq_bot.config import load_config
from atri_qq_bot.onebot.server import OneBotServer
from atri_qq_bot.onebot.server_parts import server_connection

BOT_QQ = 900000002
OTHER_QQ = 900001003


def _config(tmp_path, *, enabled: bool, follow: bool):
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
        account_follow_napcat=follow,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
        memory_extraction_enabled=False,
        memory_backfill_enabled=False,
    )


def _lightweight_builders() -> dict:
    return {"memory": lambda account, config, layout, base: ("memory", account.qq)}


class _FakeEngine:
    """只提供 apply_account_context 需要的两个属性。"""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.memory = SimpleNamespace(tag=tag)


def _server_stub(config, *, coordinator=None, engine=None):
    """借 OneBotServer 的方法，但跳过重量级 __init__。"""
    server = OneBotServer.__new__(OneBotServer)
    server.config = config
    server._account_base_config = config
    server.account_coordinator = coordinator
    server.reply_engine = engine or _FakeEngine("base")
    server.insights = None
    server.cognition_shadow = None
    server.stickers = None
    server.tools = None
    server.voice = None
    server.proactive_planner = None
    server._group_reply_focus = None
    server._message_tasks = set()
    server._conversation_workers = {}
    return server


def _coordinator_for(config):
    return server_connection.AccountSwitchCoordinator(
        config,
        build=lambda account, previous: build_runtime_resources(
            config, account, builders=_lightweight_builders(), required=set()
        ),
        async_drain=lambda: asyncio.sleep(0),
    )


# ---- 关闭时完全惰性 -----------------------------------------------------


def test_disabled_account_system_builds_no_coordinator(tmp_path) -> None:
    config = _config(tmp_path, enabled=False, follow=False)
    server = _server_stub(config)

    # 真实 __init__ 里这段逻辑等价于：开关关闭 → 不构造协调器。
    server.account_coordinator = (
        server._build_account_coordinator(config)
        if bool(getattr(config, "account_system_enabled", False))
        else None
    )

    assert server.account_coordinator is None
    # 关闭时不应该创建注册表文件。
    assert not config.accounts_db_path.exists()


def test_disabled_follow_is_a_noop(tmp_path) -> None:
    config = _config(tmp_path, enabled=False, follow=True)
    server = _server_stub(config, coordinator=None)

    asyncio.run(server.follow_napcat_account(OTHER_QQ))

    assert server.config is config
    assert not config.accounts_db_path.exists()


# ---- 开启后引导默认账号 -------------------------------------------------


def test_enabled_builds_coordinator_and_bootstraps_default_account(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    server = _server_stub(config)

    server.account_coordinator = server._build_account_coordinator(config)

    # 协调器建起来了，且 BOT_QQ 被引导成默认账号（已确认）。
    assert server.account_coordinator is not None
    registry = AccountRegistry(config.accounts_db_path)
    assert registry.count() == 1
    account = registry.get_by_qq(BOT_QQ)
    assert account is not None
    assert account.is_default is True
    assert account.confirmed is True
    # 起始状态仍是"未介入"，真正切换发生在第一次探测到登录号时。
    assert server.account_coordinator.account() is None


# ---- 跟随策略 -----------------------------------------------------------


def test_follow_off_switches_to_default_account(tmp_path) -> None:
    """未开启跟随时，当前账号永远是注册表的默认账号（BOT_QQ）。

    NapCat 登录了别的号也只会继续用默认账号——这正是今天的
    "账号不一致就忽略消息"行为。
    """
    config = _config(tmp_path, enabled=True, follow=False)
    coordinator = _coordinator_for(config)
    server = _server_stub(config, coordinator=coordinator)

    # 触发一次真实的引导（等价于 _build_account_coordinator 里的那一步）。
    from atri_qq_bot.accounts import bootstrap_from_config

    bootstrap_from_config(config)

    asyncio.run(server.follow_napcat_account(OTHER_QQ))

    assert coordinator.account() is not None
    assert coordinator.account().qq == str(BOT_QQ)


def test_follow_on_switches_to_confirmed_napcat_account(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=True)
    from atri_qq_bot.accounts import bootstrap_from_config

    bootstrap_from_config(config)
    AccountRegistry(config.accounts_db_path).register(
        OTHER_QQ, confirmed=True, enabled=True
    )
    coordinator = _coordinator_for(config)
    server = _server_stub(config, coordinator=coordinator)

    asyncio.run(server.follow_napcat_account(OTHER_QQ))

    assert coordinator.account() is not None
    assert coordinator.account().qq == str(OTHER_QQ)
    assert server.config.bot_qq == OTHER_QQ


def test_follow_on_ignores_unconfirmed_napcat_account(tmp_path) -> None:
    """未确认的新账号不切换：行为回落到今天的"账号不一致"。

    这是整个跟随功能的安全底线——不会因为 NapCat 换了个号就凭空给一个新账号
    建数据区。
    """
    config = _config(tmp_path, enabled=True, follow=True)
    from atri_qq_bot.accounts import bootstrap_from_config

    bootstrap_from_config(config)
    coordinator = _coordinator_for(config)
    server = _server_stub(config, coordinator=coordinator)

    asyncio.run(server.follow_napcat_account(OTHER_QQ))

    # 被发现并登记，但未确认 → 不切换。
    assert coordinator.account() is None
    discovered = AccountRegistry(config.accounts_db_path).get_by_qq(OTHER_QQ)
    assert discovered is not None
    assert discovered.confirmed is False
    assert discovered.enabled is False
    # 未确认账号不应该获得数据目录。
    assert not (tmp_path / "accounts" / f"qq-{OTHER_QQ}").exists()


def test_repeated_same_account_probe_does_not_switch_again(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    from atri_qq_bot.accounts import bootstrap_from_config

    bootstrap_from_config(config)
    coordinator = _coordinator_for(config)
    server = _server_stub(config, coordinator=coordinator)

    asyncio.run(server.follow_napcat_account(BOT_QQ))
    generation = coordinator.generation()
    asyncio.run(server.follow_napcat_account(BOT_QQ))

    assert coordinator.generation() == generation


def test_switch_failure_keeps_using_previous_account(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=True)
    from atri_qq_bot.accounts import bootstrap_from_config

    bootstrap_from_config(config)
    AccountRegistry(config.accounts_db_path).register(
        OTHER_QQ, confirmed=True, enabled=True
    )

    def failing_build(account, previous):
        raise RuntimeError("资源构造失败")

    coordinator = server_connection.AccountSwitchCoordinator(
        config, build=failing_build, async_drain=lambda: asyncio.sleep(0)
    )
    server = _server_stub(config, coordinator=coordinator)

    asyncio.run(server.follow_napcat_account(OTHER_QQ))

    # 失败原子性：上下文没变，server 仍用原配置。
    assert coordinator.account() is None
    assert coordinator.generation() == 0
    assert server.config is config


# ---- 换引用绝不保留旧账号对象 -------------------------------------------


def test_apply_account_context_replaces_every_scoped_attribute(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    from atri_qq_bot.accounts import bootstrap_from_config

    account = bootstrap_from_config(config)
    staged = build_runtime_resources(
        config, account, builders=_lightweight_builders(), required=set()
    )
    context = server_connection.AccountContext(
        account=account,
        generation=1,
        config=staged.config,
        layout=staged.layout,
        resources={"reply_engine": _FakeEngine("account"), "memory": ("memory", account.qq)},
    )

    server = _server_stub(config, engine=_FakeEngine("old"))
    server.stickers = "OLD_STICKERS"
    server.tools = "OLD_TOOLS"
    server.voice = "OLD_VOICE"
    server.insights = "OLD_INSIGHTS"
    server.cognition_shadow = "OLD_COGNITION"

    server.apply_account_context(context)

    assert server.reply_engine.tag == "account"
    assert server.config.bot_qq == BOT_QQ
    # 上下文里没有的资源必须被清成 None，绝不能留着上一个账号的对象。
    for name in ("insights", "cognition_shadow", "stickers", "tools", "voice"):
        assert getattr(server, name) is None, f"{name} 残留了旧对象"


def test_apply_account_context_without_engine_clears_planner(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    from atri_qq_bot.accounts import bootstrap_from_config

    account = bootstrap_from_config(config)
    staged = build_runtime_resources(
        config, account, builders=_lightweight_builders(), required=set()
    )
    context = server_connection.AccountContext(
        account=account,
        generation=1,
        config=staged.config,
        layout=staged.layout,
        resources={},
    )

    server = _server_stub(config, engine=_FakeEngine("old"))
    server.proactive_planner = "OLD_PLANNER"

    server.apply_account_context(context)

    assert server.reply_engine is None
    assert server.proactive_planner is None


# ---- 真实 OneBotServer.__init__ 的集成验证 ------------------------------


def test_real_server_init_builds_coordinator_and_bootstraps_account(tmp_path) -> None:
    """走一遍真实的 __init__，而不是手工桩。"""
    config = _config(tmp_path, enabled=True, follow=False)

    server = OneBotServer(config, _FakeEngine("base"))

    assert server.account_coordinator is not None
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.get_by_qq(BOT_QQ)
    assert account is not None
    assert account.is_default is True
    assert account.confirmed is True
    # 构造完还没有切换，仍是"未介入"。
    assert server.account_coordinator.account() is None


def test_real_server_follow_reaches_default_account_with_equivalent_config(
    tmp_path,
) -> None:
    """开启账号系统、且只有一个默认账号时，切换后的 config 与原 config 逐字段相等。

    这就是"默认账号零搬迁"在运行时侧的证明：不会因为打开了开关就改变行为。
    """
    config = _config(tmp_path, enabled=True, follow=False)
    server = OneBotServer(config, _FakeEngine("base"))
    # 用轻量资源替换默认表，避免在测试里构造 persona 引擎；
    # 排空、切换、换引用这些步骤仍然是真实实现。
    server.account_coordinator = server._build_account_coordinator(
        config, builders=_lightweight_builders(), required=set()
    )
    server._message_tasks = set()
    server._conversation_workers = {}

    asyncio.run(server.follow_napcat_account(BOT_QQ))

    assert server.account_coordinator.generation() == 1
    assert server.account_coordinator.account().qq == str(BOT_QQ)
    # 关键：默认账号解析出的配置与原配置逐字段相等。
    assert server.config == config


# ---- 排空 ---------------------------------------------------------------


def test_drain_returns_immediately_when_nothing_pending(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    server = _server_stub(config)

    started = time.monotonic()
    asyncio.run(server.drain_account_work())

    assert time.monotonic() - started < 0.5


def test_drain_waits_for_pending_tasks(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=False)
    server = _server_stub(config)

    async def scenario() -> None:
        finished = asyncio.Event()

        async def slow() -> None:
            await asyncio.sleep(0.2)
            finished.set()

        task = asyncio.create_task(slow())
        server._message_tasks.add(task)
        await server.drain_account_work()
        # 排空返回时任务应该已经跑完，而不是被 cancel 掉。
        assert finished.is_set()
        assert task.done()
        assert not task.cancelled()

    asyncio.run(scenario())


def test_drain_times_out_instead_of_hanging(tmp_path, monkeypatch) -> None:
    """卡住的任务不能让换账号永久挂死。"""
    monkeypatch.setattr(server_connection, "ACCOUNT_DRAIN_TIMEOUT_SECONDS", 0.2)
    config = _config(tmp_path, enabled=True, follow=False)
    server = _server_stub(config)

    async def scenario() -> None:
        # 一个永远不结束的任务。
        task = asyncio.create_task(asyncio.sleep(30))
        server._message_tasks.add(task)
        started = time.monotonic()
        await server.drain_account_work()
        elapsed = time.monotonic() - started
        task.cancel()
        assert elapsed < 2.0, f"排空没有按时超时：{elapsed:.2f}s"

    asyncio.run(scenario())
