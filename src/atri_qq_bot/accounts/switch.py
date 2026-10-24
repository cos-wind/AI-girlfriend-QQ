"""账号热切换协调器。

你要求"切换账号时面板与数据都跟着切、不要求重启"。热切换真正的风险不是切不过去，
而是**静默串号**——把 A 账号的记忆写进 B 账号的库，不报错、只错数据。
这个模块用三件事把窗口关掉：

1. **临界区 + 排空**：切换在锁内进行，且切换前先调用 ``drain()`` 等在途的消息处理
   结束。排空是**主要**手段——它从构造上关掉了"切换瞬间有 worker 正在写"这个窗口。
2. **整体重建 + 原子换引用**：账号作用域的对象（记忆 store、认知 store、评测
   runtime、WebUI 的 memory_admin……）全部由 ``build`` 重新构造，构造成功后才一次性
   替换引用。**绝不原地修改一个活着的 store**：那些 store 在 ``__init__`` 里就绑定了
   文件路径，原地改配置只会造成"配置指向新库、实际写旧库"。
3. **generation 校验**：每次真实切换递增一个计数器。任务在自己开始时 ``capture()``
   一份上下文并一直用它（这样它写的就是自己那个账号的库，天然安全）；对于必须
   延迟解析路径的调用点，用 ``discard_if_stale()`` 在落盘前复核，过期的写入丢弃并记日志。

关键约定：**每条消息任务在出队时 ``capture()`` 一次上下文，并在整个任务里只用它。**
不要在任务中途重新解析路径——那是唯一会真正串号的写法。
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterator, Mapping

from .layout import AccountPaths
from .registry import Account

LOGGER = logging.getLogger("atri.accounts.switch")


@dataclass(frozen=True)
class AccountContext:
    """某个时刻的账号作用域快照。

    ``generation`` 是用来判断"这份快照是否还属于当前账号"的凭据。
    ``account is None`` 表示账号系统没有介入，此时 ``config`` 就是原始的
    ``BotConfig``，行为与账号化之前逐条一致。
    """

    account: Account | None
    generation: int
    config: Any
    layout: AccountPaths | None = None
    resources: Mapping[str, Any] = field(default_factory=dict)

    @property
    def account_id(self) -> str | None:
        return self.account.account_id if self.account is not None else None

    @property
    def is_scoped(self) -> bool:
        """是否真的是"某个账号"的上下文（``False`` = 未介入）。"""
        return self.account is not None

    def resource(self, name: str, default: Any = None) -> Any:
        return self.resources.get(name, default)


@dataclass(frozen=True)
class AccountResources:
    """``build`` 的返回值：账号作用域的配置与资源。"""

    config: Any
    layout: AccountPaths | None = None
    resources: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SwitchEvent:
    at: float
    from_account_id: str | None
    to_account_id: str | None
    generation: int
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "from_account_id": self.from_account_id,
            "to_account_id": self.to_account_id,
            "generation": self.generation,
            "reason": self.reason,
        }


BuildFn = Callable[[Account | None, AccountContext], AccountResources]
DrainFn = Callable[[], None]
AsyncDrainFn = Callable[[], "Awaitable[None]"]
SwitchHook = Callable[[AccountContext, AccountContext], None]


class AccountSwitchCoordinator:
    """持有当前账号上下文，并在切换时原子替换。

    两把锁，职责不同：

    * ``_switch_lock`` 串行化多次切换。``aswitch`` 会**跨 await 持有它**，
      所以它绝不能用于读路径——否则排空期间 WebUI 会被卡住。
    * ``_context_lock`` 只保护 ``_context`` 的读写，持有时间极短。
      读路径只碰这把锁。
    """

    def __init__(
        self,
        config: Any,
        *,
        build: BuildFn,
        drain: DrainFn | None = None,
        async_drain: AsyncDrainFn | None = None,
        on_switch: SwitchHook | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._switch_lock = threading.Lock()
        self._context_lock = threading.RLock()
        self._build = build
        self._drain = drain if drain is not None else (lambda: None)
        self._async_drain = async_drain
        self._on_switch = on_switch
        self._clock = clock
        self._events: list[SwitchEvent] = []
        self._stale_writes = 0
        # 初始上下文：generation=0，account=None —— 账号系统未介入。
        self._context = AccountContext(
            account=None, generation=0, config=config, layout=None, resources={}
        )

    # ---- 读（可被任意线程安全调用）-------------------------------------

    @property
    def context(self) -> AccountContext:
        with self._context_lock:
            return self._context

    def capture(self) -> AccountContext:
        """取一份上下文快照。任务应当在整个生命周期里只用这一份。"""
        return self.context

    def generation(self) -> int:
        with self._context_lock:
            return self._context.generation

    def account(self) -> Account | None:
        with self._context_lock:
            return self._context.account

    def still_current(self, generation: int) -> bool:
        """这份快照是否仍属于当前账号。"""
        with self._context_lock:
            return self._context.generation == int(generation)

    def events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._context_lock:
            items = self._events[-max(1, int(limit)) :]
        return [item.public_dict() for item in reversed(items)]

    @property
    def stale_writes(self) -> int:
        """被丢弃的过期写入次数。持续增长说明有调用点在延迟解析路径。"""
        return self._stale_writes

    # ---- 写防护 ---------------------------------------------------------

    def discard_if_stale(self, generation: int, *, label: str = "") -> bool:
        """落盘前复核。返回 ``True`` 表示这次写入应被丢弃。

        用法::

            context = coordinator.capture()
            ...  ...
            if coordinator.discard_if_stale(context.generation, label="memory.save"):
                return False          # 账号已经换了，这次写入不属于当前账号
        """
        if self.still_current(generation):
            return False
        with self._context_lock:
            self._stale_writes += 1
            current_generation = self._context.generation
        LOGGER.warning(
            "丢弃过期写入：generation=%s 已不是当前账号（当前 %s）%s",
            generation,
            current_generation,
            f"，来源 {label}" if label else "",
        )
        return True

    @contextmanager
    def write_guard(self, generation: int, *, label: str = "") -> Iterator[bool]:
        """``discard_if_stale`` 的上下文管理器形式。yield ``False`` 表示写入已被丢弃。"""
        yield not self.discard_if_stale(generation, label=label)

    # ---- 切换 -----------------------------------------------------------

    def switch(self, account: Account | None, *, reason: str = "") -> AccountContext:
        """同步切换。``drain`` 也是同步的（纯线程环境或测试用）。

        ``aswitch`` 是 OneBot 那条 async 链路的入口——那里不能用这个版本：
        在事件循环上同步等待 asyncio 任务会直接死锁。
        """
        with self._switch_lock:
            current = self._context
            if _same_account(current.account, account):
                return current
            self._drain()
            return self._install(current, account, reason=reason)

    async def aswitch(
        self,
        account: Account | None,
        *,
        reason: str = "",
        drain: AsyncDrainFn | None = None,
    ) -> AccountContext:
        """异步切换，排空阶段可以 ``await``。

        ``_switch_lock`` 会跨 ``await`` 持有（串行化多次切换），但读路径只碰
        ``_context_lock``，所以排空期间面板/状态查询不会被卡住。
        """
        with self._switch_lock:
            current = self._context
            if _same_account(current.account, account):
                return current
            resolver = drain if drain is not None else self._async_drain
            if resolver is not None:
                await resolver()
            else:
                # 没有异步排空实现时退回同步版本，至少不会不退让地跳过排空。
                self._drain()
            return self._install(current, account, reason=reason)

    def _install(
        self,
        current: AccountContext,
        account: Account | None,
        *,
        reason: str,
    ) -> AccountContext:
        """构造新上下文并一次性替换引用。调用方必须已持有 ``_switch_lock``。

        构造失败时 ``self._context`` 尚未被触碰，所以不会出现"换了一半"的状态。
        """
        staged = self._build(account, current)

        if account is None and staged.resources:
            # 未介入时不允许携带任何账号资源：那会留下上一个账号 store 的
            # 引用，而调用方以为自己处在"没有账号"的状态里。
            raise ValueError(
                "账号系统未介入时不能携带账号资源，"
                f"收到：{sorted(staged.resources)}"
            )

        new_context = AccountContext(
            account=account,
            generation=current.generation + 1,
            config=staged.config,
            layout=staged.layout,
            resources=dict(staged.resources),
        )

        event = SwitchEvent(
            at=float(self._clock()),
            from_account_id=current.account_id,
            to_account_id=new_context.account_id,
            generation=new_context.generation,
            reason=str(reason or ""),
        )

        with self._context_lock:
            self._context = new_context
            self._events.append(event)

        LOGGER.info(
            "账号切换：%s → %s（generation=%s%s）",
            event.from_account_id or "未介入",
            event.to_account_id or "未介入",
            event.generation,
            f"，原因 {event.reason}" if event.reason else "",
        )
        if self._on_switch is not None:
            self._on_switch(current, new_context)
        return new_context


def _same_account(left: Account | None, right: Account | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return left.account_id == right.account_id


__all__ = [
    "AccountContext",
    "AccountResources",
    "AccountSwitchCoordinator",
    "SwitchEvent",
]
