"""账号热切换协调器的测试（阶段 3b）。

这里用**假对象**而不是真实服务：热切换的安全性必须能在不碰 QQ、不碰真实数据
文件的前提下被证明。真实接线在 3c，接完再跑一遍跨账号隔离专项测试。

重点验证四件事：

1. 空操作：切到同一个账号不递增 generation、不调用 build。
2. 失败原子性：``build`` 抛异常时上下文与 generation 都保持原样。
3. 排空先于构造：``drain`` 必须在 ``build`` 之前被调用（否则窗口没关掉）。
4. 不撕裂：并发读到的上下文里，config 与 resources 必须来自同一个 generation。
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, replace

import pytest

from atri_qq_bot.accounts import AccountRegistry, AccountSwitchCoordinator, bootstrap_from_config
from atri_qq_bot.accounts.switch import AccountResources
from atri_qq_bot.config import load_config

BOT_QQ = 900000002
OTHER_QQ = 900001003


@dataclass(frozen=True)
class _FakeConfig:
    bot_qq: int
    memory_path: str


def _config(tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text(f"BOT_QQ={BOT_QQ}\n", encoding="utf-8")
    return replace(
        load_config(env_file),
        account_system_enabled=True,
        accounts_db_path=tmp_path / "accounts" / "index.sqlite3",
    )


class _Recorder:
    """记录调用顺序，用来断言 drain 与 build 的先后。"""

    def __init__(self, base_qq: int = BOT_QQ) -> None:
        self.calls: list[str] = []
        self.build_inputs: list[tuple[str | None, int]] = []
        self.base_qq = base_qq

    def drain(self) -> None:
        self.calls.append("drain")

    def build(self, account, previous):
        self.calls.append("build")
        self.build_inputs.append(
            (account.account_id if account else None, previous.generation)
        )
        if account is None:
            # 未介入时回落到基础配置，且不带任何账号资源——
            # 协调器会强制"未介入 ⇒ resources 为空"这条不变量。
            return AccountResources(
                config=_FakeConfig(bot_qq=self.base_qq, memory_path="/m/base.json")
            )
        qq = account.qq_int
        return AccountResources(
            config=_FakeConfig(bot_qq=qq, memory_path=f"/m/{qq}.json"),
            layout=None,
            # tag 用来检测"撕裂"：它必须与 config.bot_qq 始终一致。
            resources={"tag": str(qq)},
        )


def _coordinator(tmp_path, *, drain=None, on_switch=None, build=None, async_drain=None):
    config = _config(tmp_path)
    registry = AccountRegistry(config.accounts_db_path)
    default_account = bootstrap_from_config(config)
    other_account = registry.register(OTHER_QQ, confirmed=True, enabled=True)
    recorder = _Recorder()
    coordinator = AccountSwitchCoordinator(
        config,
        build=build or recorder.build,
        drain=drain or recorder.drain,
        async_drain=async_drain,
        on_switch=on_switch,
        clock=lambda: 1000.0,
    )
    return coordinator, recorder, default_account, other_account


# ---- 初始状态 -----------------------------------------------------------


def test_initial_context_is_unscoped(tmp_path) -> None:
    coordinator, recorder, _, _ = _coordinator(tmp_path)

    context = coordinator.context

    assert context.account is None
    assert context.account_id is None
    assert context.is_scoped is False
    assert context.generation == 0
    assert context.config.bot_qq == BOT_QQ  # 原始配置，未介入
    assert dict(context.resources) == {}
    assert recorder.calls == []


# ---- 空操作 -------------------------------------------------------------


def test_switching_to_same_account_is_a_noop(tmp_path) -> None:
    coordinator, recorder, _, other = _coordinator(tmp_path)
    first = coordinator.switch(other)
    recorder.calls.clear()

    second = coordinator.switch(other)

    assert second is first
    assert second.generation == 1
    assert recorder.calls == []


def test_switching_to_none_twice_is_a_noop(tmp_path) -> None:
    coordinator, _, _, _ = _coordinator(tmp_path)

    assert coordinator.switch(None) is coordinator.context
    assert coordinator.generation() == 0


# ---- 真实切换 -----------------------------------------------------------


def test_switch_builds_and_increments_generation(tmp_path) -> None:
    coordinator, recorder, default, other = _coordinator(tmp_path)

    context = coordinator.switch(other, reason="NapCat 登录变化")

    assert context.generation == 1
    assert context.account_id == other.account_id
    assert context.is_scoped is True
    assert context.config.bot_qq == OTHER_QQ
    assert context.resource("tag") == str(OTHER_QQ)
    assert recorder.build_inputs == [(other.account_id, 0)]


def test_each_real_change_increments_generation(tmp_path) -> None:
    coordinator, _, default, other = _coordinator(tmp_path)

    assert coordinator.switch(other).generation == 1
    assert coordinator.switch(default).generation == 2
    assert coordinator.switch(other).generation == 3
    assert coordinator.switch(None).generation == 4


def test_switch_back_to_unscoped_clears_resources(tmp_path) -> None:
    """退回"账号系统未介入"时必须清掉账号资源，不能留下上一个账号的引用。"""
    coordinator, _, _, other = _coordinator(tmp_path)
    coordinator.switch(other)

    context = coordinator.switch(None)

    assert context.account is None
    assert dict(context.resources) == {}
    assert context.config.bot_qq == BOT_QQ


# ---- 排空先于构造 -------------------------------------------------------


def test_drain_runs_before_build(tmp_path) -> None:
    """排空是关掉"切换瞬间正在写"这个窗口的主要手段，顺序不能反。"""
    coordinator, recorder, _, other = _coordinator(tmp_path)

    coordinator.switch(other)

    assert recorder.calls == ["drain", "build"]


def test_drain_is_not_called_for_a_noop_switch(tmp_path) -> None:
    coordinator, recorder, _, other = _coordinator(tmp_path)
    coordinator.switch(other)
    recorder.calls.clear()

    coordinator.switch(other)

    assert recorder.calls == []


# ---- 失败原子性 ---------------------------------------------------------


def test_build_failure_leaves_context_untouched(tmp_path) -> None:
    calls: list[str] = []

    def failing_build(account, previous):
        calls.append("build")
        raise RuntimeError("构造失败")

    coordinator, _, default, other = _coordinator(tmp_path, build=failing_build)
    before = coordinator.context

    with pytest.raises(RuntimeError, match="构造失败"):
        coordinator.switch(other)

    assert calls == ["build"]
    # 不能出现"换了一半"的状态。
    assert coordinator.context is before
    assert coordinator.generation() == 0
    assert coordinator.context.account is None


def test_build_failure_does_not_record_an_event(tmp_path) -> None:
    def failing_build(account, previous):
        raise RuntimeError("boom")

    coordinator, _, _, other = _coordinator(tmp_path, build=failing_build)

    with pytest.raises(RuntimeError):
        coordinator.switch(other)

    assert coordinator.events() == []


def test_unscoped_context_may_not_carry_account_resources(tmp_path) -> None:
    """未介入时携带账号资源会留下上一个账号 store 的引用，必须报错而不是静默接受。

    场景：先从有账号状态退回"未介入"，而 build 忘了清空 resources。
    """

    def leaky_build(account, previous):
        if account is None:
            # 这里故意不返回空 resources —— 模拟接错线的 build。
            return AccountResources(
                config=_FakeConfig(bot_qq=BOT_QQ, memory_path="/m/base.json"),
                resources={"memory_store": object()},
            )
        return AccountResources(
            config=_FakeConfig(bot_qq=account.qq_int, memory_path="/m/x.json"),
            resources={"tag": str(account.qq_int)},
        )

    coordinator, _, _, other = _coordinator(tmp_path, build=leaky_build)
    scoped = coordinator.switch(other)
    assert scoped.generation == 1

    with pytest.raises(ValueError, match="不能携带账号资源"):
        coordinator.switch(None)

    # 退回失败不能破坏当前状态。
    assert coordinator.context is scoped
    assert coordinator.generation() == 1
    assert coordinator.account() is other


# ---- generation 与过期写入 ---------------------------------------------


def test_still_current_reflects_switches(tmp_path) -> None:
    coordinator, _, _, other = _coordinator(tmp_path)
    captured = coordinator.capture()

    assert coordinator.still_current(captured.generation) is True
    coordinator.switch(other)

    assert coordinator.still_current(captured.generation) is False
    assert coordinator.still_current(coordinator.generation()) is True


def test_discard_if_stale_reports_and_counts(tmp_path) -> None:
    coordinator, _, _, other = _coordinator(tmp_path)
    captured = coordinator.capture()

    assert coordinator.discard_if_stale(captured.generation, label="memory.save") is False
    assert coordinator.stale_writes == 0

    coordinator.switch(other)

    assert coordinator.discard_if_stale(captured.generation, label="memory.save") is True
    assert coordinator.stale_writes == 1


def test_write_guard_yields_false_for_stale_generation(tmp_path) -> None:
    coordinator, _, _, other = _coordinator(tmp_path)
    captured = coordinator.capture()

    with coordinator.write_guard(captured.generation) as allowed:
        assert allowed is True

    coordinator.switch(other)

    with coordinator.write_guard(captured.generation) as allowed:
        assert allowed is False


# ---- 事件与钩子 ---------------------------------------------------------


def test_events_record_the_switch(tmp_path) -> None:
    coordinator, _, default, other = _coordinator(tmp_path)

    coordinator.switch(other, reason="NapCat 登录变化")

    events = coordinator.events()
    assert len(events) == 1
    assert events[0]["from_account_id"] is None
    assert events[0]["to_account_id"] == other.account_id
    assert events[0]["generation"] == 1
    assert events[0]["reason"] == "NapCat 登录变化"
    assert events[0]["at"] == 1000.0


def test_events_are_newest_first_and_limited(tmp_path) -> None:
    coordinator, _, default, other = _coordinator(tmp_path)
    coordinator.switch(other)
    coordinator.switch(default)
    coordinator.switch(other)

    events = coordinator.events(limit=2)

    assert len(events) == 2
    assert events[0]["generation"] == 3
    assert events[1]["generation"] == 2


def test_on_switch_hook_receives_old_and_new(tmp_path) -> None:
    seen: list[tuple[int, int]] = []
    coordinator, _, _, other = _coordinator(
        tmp_path, on_switch=lambda old, new: seen.append((old.generation, new.generation))
    )

    coordinator.switch(other)

    assert seen == [(0, 1)]


# ---- 并发不撕裂 ---------------------------------------------------------


def test_concurrent_readers_never_observe_a_torn_context(tmp_path) -> None:
    """并发读到的上下文里 config 与 resources 必须来自同一个 generation。

    这是"原子换引用"的核心保障：如果实现改成先改 config、再改 resources，
    这个测试会抓到。
    """
    coordinator, _, default, other = _coordinator(tmp_path)
    stop = threading.Event()
    torn: list[str] = []
    observations = [0]

    def reader() -> None:
        while not stop.is_set():
            context = coordinator.capture()
            observations[0] += 1
            if not context.is_scoped:
                continue
            # tag 由 build 依据账号写入，必须与 config 完全对应。
            if context.resource("tag") != str(context.config.bot_qq):
                torn.append(
                    f"generation={context.generation} "
                    f"tag={context.resource('tag')} qq={context.config.bot_qq}"
                )

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for thread in readers:
        thread.start()
    try:
        for _ in range(60):
            coordinator.switch(other)
            coordinator.switch(default)
    finally:
        stop.set()
        for thread in readers:
            thread.join()

    assert torn == []
    assert observations[0] > 0


# ---- 异步切换（OneBot 那条链路用这个）---------------------------------


def test_aswitch_awaits_async_drain_before_build(tmp_path) -> None:
    order: list[str] = []

    async def async_drain() -> None:
        # 真的让出一次控制权，证明它是一个被 await 的协程而不是被直接调用。
        await asyncio.sleep(0)
        order.append("drain")

    def build(account, previous):
        order.append("build")
        return AccountResources(
            config=_FakeConfig(bot_qq=account.qq_int, memory_path="/m/x.json"),
            resources={"tag": str(account.qq_int)},
        )

    coordinator, _, _, other = _coordinator(tmp_path, build=build, async_drain=async_drain)

    context = asyncio.run(coordinator.aswitch(other, reason="probe"))

    assert order == ["drain", "build"]
    assert context.generation == 1
    assert context.resource("tag") == str(OTHER_QQ)


def test_aswitch_is_a_noop_for_the_same_account(tmp_path) -> None:
    drained: list[int] = []

    async def async_drain() -> None:
        drained.append(1)

    coordinator, _, _, other = _coordinator(tmp_path, async_drain=async_drain)
    first = asyncio.run(coordinator.aswitch(other))
    drained.clear()

    second = asyncio.run(coordinator.aswitch(other))

    assert second is first
    assert second.generation == 1
    assert drained == []


def test_aswitch_falls_back_to_sync_drain(tmp_path) -> None:
    coordinator, recorder, _, other = _coordinator(tmp_path)

    asyncio.run(coordinator.aswitch(other))

    assert recorder.calls == ["drain", "build"]


def test_aswitch_build_failure_leaves_context_untouched(tmp_path) -> None:
    def failing_build(account, previous):
        raise RuntimeError("boom")

    coordinator, _, _, other = _coordinator(tmp_path, build=failing_build)
    before = coordinator.context

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(coordinator.aswitch(other))

    assert coordinator.context is before
    assert coordinator.generation() == 0


def test_aswitch_does_not_block_readers_while_draining(tmp_path) -> None:
    """排空期间读路径必须立刻返回 —— 这正是 ``_switch_lock`` 与 ``_context_lock``
    分开的理由。如果实现图省事用同一把锁跨 await 持有，WebUI 会在切换期间卡住。
    """
    gate = threading.Event()
    drain_started = threading.Event()

    async def parking_drain() -> None:
        drain_started.set()
        while not gate.is_set():
            await asyncio.sleep(0.005)

    coordinator, _, _, other = _coordinator(tmp_path, async_drain=parking_drain)

    def run_switch() -> None:
        asyncio.run(coordinator.aswitch(other))

    worker = threading.Thread(target=run_switch)
    worker.start()
    try:
        assert drain_started.wait(timeout=5), "排空没有开始"
        # 排空挂起期间反复读上下文，每次都必须很快返回。
        started = time.monotonic()
        for _ in range(50):
            context = coordinator.context
            assert context.account is None  # 新上下文还没装上
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, f"读路径被排空阻塞了 {elapsed:.2f}s"
    finally:
        gate.set()
        worker.join(timeout=5)

    assert coordinator.account() is other
    assert coordinator.generation() == 1
