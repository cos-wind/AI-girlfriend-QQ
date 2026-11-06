"""账号系统面板接口。

面板**跟随 NapCat 登录的账号**，不由 UI 选择——所以这里只读，不提供切换接口。
真正的切换发生在 OneBot 侧的 `probe_onebot_status` 里（见
`onebot/server_parts/server_connection.py` 的 `follow_napcat_account`）。

返回内容同时服务两处 UI：顶部横幅（当前账号）与用户中心的账号列表。
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from .handler_support import WebUIHandlerMixin, _sync_webui_globals

from atri_qq_bot.accounts import (
    account_data_paths,
    account_id_for,
    ensure_account_layout,
    registry_for_config,
)
from atri_webui import account_view

LOGGER = logging.getLogger("atri.webui.account")


def view_memory_admin_for(host: Any) -> Any:
    """读路径应当使用的记忆管理对象。

    优先用"查看账号"的（手动选了别的账号时展示它的记忆）；宿主没提供这个能力时
    **显式退回运行账号的** ``memory_admin``，语义上就是"查看账号 = 运行账号"。

    写成**模块级函数**而不是方法：调用点（例如 ``_reply_strategy_objects``）的
    ``self`` 未必是完整的 handler——测试里就是裸 namespace。做成方法会让那种调用
    直接 AttributeError，而上层的 `except Exception: items = []` 又会把它静默变成
    "记忆对象为空"，测试只拿到一半数据却不报错。这个坑真的踩到过。
    """
    state = getattr(host, "webui_state", None)
    if state is None:
        return None
    getter = getattr(state, "view_memory_admin", None)
    if callable(getter):
        return getter()
    return getattr(state, "memory_admin", None)


def is_read_only_view_for(host: Any) -> bool:
    """宿主是否处于只读检视模式。

    宿主没有查看账号能力时返回 ``False``（不是只读）——**这不是安全漏洞，而是正确
    的语义**：不支持查看选择的宿主永远处于 ``auto``，即"查看账号 = 运行账号"，
    此时写操作本来就该放行。

    和 :func:`view_memory_admin_for` 用同样的模块级回落模式：调用点的 ``self``
    未必是完整 handler。
    """
    state = getattr(host, "webui_state", None)
    if state is None:
        return False
    checker = getattr(state, "is_read_only_view", None)
    if callable(checker):
        return bool(checker())
    return False


def effective_bot_qq_for(host: Any) -> Any:
    """用户目录里代表"机器人自己"的 QQ 号。

    必须跟随**生效账号**（手动查看别的账号时就是那个账号的），否则换号后用户目录
    仍把旧号当机器人，把旧号标成"自己"。

    和 :func:`view_memory_admin_for` 用同样的模块级回落模式：宿主没有
    ``effective_bot_qq`` 时退回 ``view_config().bot_qq``——语义完全一样，因为
    "查看账号 = 运行账号" 的宿主本来就只有一份配置。**不能**直接写成
    ``state.effective_bot_qq()``：那样任何只实现 ``view_*`` 读访问器的宿主（测试里
    就是）都会 AttributeError，被下面的 ``except Exception`` 吞成一个 503，
    表现成"用户目录整个打不开"。
    """
    state = getattr(host, "webui_state", None)
    if state is None:
        return None
    getter = getattr(state, "effective_bot_qq", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None
        if value:
            return value
    for name in ("view_config", "config"):
        reader = getattr(state, name, None)
        config = reader() if callable(reader) else reader
        value = getattr(config, "bot_qq", None)
        if value:
            return value
    return None


def _account_data_info(config: Any, account: Any) -> dict[str, Any]:
    """该账号的数据位置与体积。

    只用 ``stat()``，**不解析记忆 JSON**——那是 12MB 的文件，不能每个请求读一遍。
    也不创建目录（用 ``account_data_paths`` 而不是 ``ensure_account_layout``）。
    """
    try:
        layout = account_data_paths(config, account)
    except Exception as exc:
        return {"error": str(exc)}
    if layout is None:
        return {}

    def size_of(path: Any) -> int | None:
        try:
            return int(path.stat().st_size)
        except OSError:
            return None

    memory_size = size_of(layout.memory_path)
    insights_size = size_of(layout.insights_db_path)
    return {
        "is_default": layout.is_default,
        "root": str(layout.root) if layout.root else None,
        "memory_path": str(layout.memory_path),
        "memory_bytes": memory_size,
        "memory_exists": memory_size is not None,
        "insights_path": str(layout.insights_db_path),
        "insights_bytes": insights_size,
        "insights_exists": insights_size is not None,
        "root_exists": bool(layout.root and layout.root.is_dir()),
        "public": layout.public_dict(),
    }


def running_account_id_for(state: Any) -> str | None:
    """机器人**正在运行**的账号 ID；宿主没这个能力时返回 ``None``。

    和其它几个一样用模块级回落：桩宿主（测试）不该因为缺这个方法就整条载荷报错。
    ``None`` 的语义是"账号系统未介入 / 未知"，面板据此不显示"运行中"徽标。
    """
    if state is None:
        return None
    getter = getattr(state, "running_account_id", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return None


class HandlerAccountMixin(WebUIHandlerMixin):
    def _account_payload(self) -> Any:
        _sync_webui_globals(self)
        state = self.webui_state
        config = state.config
        enabled = bool(getattr(config, "account_system_enabled", False))

        payload: dict[str, Any] = {
            "ok": True,
            "enabled": enabled,
            "follow_napcat": bool(getattr(config, "account_follow_napcat", False)),
            "bot_qq": str(getattr(config, "bot_qq", "") or ""),
            "current": None,
            "layout": None,
            "events": [],
            "stale_writes": 0,
            "accounts": [],
            "pending": [],
        }

        if not enabled:
            # 关闭时**绝不打开注册表**——那会在 data/accounts 下建库。
            # 面板据此显示"账号系统未启用"，不显示任何账号。
            return payload

        # 协调器挂在 OneBot server 上（WebUI 与 OneBot 共用一个进程）。
        coordinator = getattr(state.server, "account_coordinator", None)
        if coordinator is not None:
            context = coordinator.context
            payload["current"] = (
                context.account.public_dict() if context.account else None
            )
            payload["layout"] = (
                context.layout.public_dict() if context.layout else None
            )
            payload["events"] = coordinator.events(limit=10)
            # 持续增长说明有调用点在延迟解析路径，是需要修掉的信号。
            payload["stale_writes"] = coordinator.stale_writes

        try:
            accounts = registry_for_config(config).list_all()
        except Exception as exc:
            payload["error"] = f"读取账号注册表失败：{exc}"
            return payload

        # 每个账号附上数据位置与体积，账号管理区据此显示"数据在哪、有多大"。
        payload["accounts"] = [
            {**account.public_dict(), "data": _account_data_info(config, account)}
            for account in accounts
        ]
        payload["running_account_id"] = running_account_id_for(state)
        # 未确认的新账号：面板据此提示"是否创建它的独立数据区"。
        payload["pending"] = [
            item for item in payload["accounts"] if not item["confirmed"]
        ]
        return payload

    def _handle_account_current(self) -> None:
        self._send_json(self._account_payload())

    # ---- 查看账号（只读选择）-------------------------------------------

    def _view_memory_admin(self) -> Any:
        """``view_memory_admin_for`` 的方法形式，方便 handler 内部调用。"""
        return view_memory_admin_for(self)

    def _refuse_when_read_only(self, action: str) -> bool:
        """只读检视模式下拒绝写操作。返回 ``True`` 表示已经拒绝（调用方直接 return）。

        为什么不让写跟随查看账号：那样"切到 X 看数据"和"改到 X 的数据"混在一起，
        很容易在看别的账号时误改它的记忆。所以显式选别的账号 = 只读。
        """
        if not is_read_only_view_for(self):
            return False
        logger = getattr(self.webui_state, "log_read_only_refusal", None)
        if callable(logger):
            logger(action)
        self._send_error(
            HTTPStatus.BAD_REQUEST,
            "面板正在只读查看另一个账号，已停用编辑。"
            "把查看账号切回「跟随运行账号」后才能修改。",
        )
        return True

    # ---- 手动新增账号 ---------------------------------------------------

    def _handle_account_add(self) -> None:
        """手动登记一个机器人账号。

        为什么需要这个入口：NapCat 通常会自动登录同一个号，用户没法随手换号，
        于是"跟随 NapCat"这条路径永远触发不了。手动登记之后，面板才能在这些账号
        之间切换查看。

        **登记不等于让机器人跑它**：机器人运行哪个账号仍由 NapCat 决定。
        要让机器人真的用这个号，必须让 NapCat 登录它。
        """
        if self._refuse_when_read_only("新增账号"):
            return
        config = self.webui_state.config
        if not bool(getattr(config, "account_system_enabled", False)):
            return self._send_error(HTTPStatus.BAD_REQUEST, "账号系统未启用")

        payload = self._read_json() or {}
        raw_qq = str(payload.get("qq") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not raw_qq.isdigit():
            return self._send_error(
                HTTPStatus.BAD_REQUEST, "QQ 号必须是纯数字"
            )
        try:
            account_id = account_id_for(raw_qq)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

        try:
            registry = registry_for_config(config)
            existing = registry.get(account_id)
            if existing is not None:
                return self._send_error(
                    HTTPStatus.BAD_REQUEST,
                    f"账号已存在：{account_id}（当前状态 "
                    f"{'已确认' if existing.confirmed else '待确认'}）",
                )
            # 手动登记的直接标为已确认并启用——这是用户明确要求创建的数据区。
            account = registry.register(
                raw_qq,
                display_name=display_name or f"QQ {raw_qq}",
                is_default=False,
                enabled=True,
                confirmed=True,
                notes="由 WebUI 手动登记",
            )
            ensure_account_layout(config, account)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

        LOGGER.info("已手动登记账号 %s", account_id)
        self._send_json(
            {"ok": True, "account": account.public_dict(), **self._account_payload()}
        )

    # ---- 启停账号 -------------------------------------------------------

    def _handle_account_update(self) -> None:
        """启用/停用账号。

        **刻意不提供"设为默认"**：默认账号决定"未开启跟随时机器人跑哪个号"。
        把它改成 NapCat 没登录的号，会让事件全部因 self_id 不匹配被丢弃——
        表现就是"发消息完全没反应"。运行账号只由 NapCat 登录状态决定。
        """
        if self._refuse_when_read_only("修改账号状态"):
            return
        config = self.webui_state.config
        if not bool(getattr(config, "account_system_enabled", False)):
            return self._send_error(HTTPStatus.BAD_REQUEST, "账号系统未启用")

        payload = self._read_json() or {}
        account_id = str(payload.get("account_id") or "").strip()
        if not account_id:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少 account_id")
        if "enabled" not in payload:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少 enabled")

        try:
            registry = registry_for_config(config)
            if registry.get(account_id) is None:
                return self._send_error(
                    HTTPStatus.BAD_REQUEST, f"没有这个账号：{account_id}"
                )
            updated = registry.update(account_id, enabled=bool(payload["enabled"]))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

        self._send_json(
            {
                "ok": True,
                "account": updated.public_dict() if updated else None,
                **self._account_payload(),
            }
        )

    def _handle_account_view_get(self) -> None:
        self._send_json({"ok": True, **self.webui_state.view_payload()})

    # ---- 确认新账号 -----------------------------------------------------

    def _handle_account_confirm(self) -> None:
        """确认一个由 NapCat 自动发现的账号：标记已确认并**在这时才**建数据目录。

        这是"发现新账号"到"真正启用"之间那道人工闸门。之前只有展示、没有确认入口，
        而未确认的账号按设计永远不会被跟随——所以没有这个端点，跟随功能根本无法验收。
        """
        if self._refuse_when_read_only("确认新账号"):
            return
        config = self.webui_state.config
        if not bool(getattr(config, "account_system_enabled", False)):
            return self._send_error(HTTPStatus.BAD_REQUEST, "账号系统未启用")

        payload = self._read_json() or {}
        account_id = str(payload.get("account_id") or "").strip()
        if not account_id:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少 account_id")

        try:
            registry = registry_for_config(config)
            account = registry.get(account_id)
            if account is None:
                return self._send_error(
                    HTTPStatus.BAD_REQUEST, f"没有这个账号：{account_id}"
                )
            confirmed = registry.mark_confirmed(account_id, enabled=True)
            if confirmed is None:
                return self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR, "确认账号失败"
                )
            # 数据目录在这一步才创建——未确认的账号不该获得任何数据区。
            ensure_account_layout(config, confirmed)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

        LOGGER.info(
            "已确认账号 %s，数据目录已就绪；下一次探测到该登录号时会切换到它",
            account_id,
        )
        self._send_json(
            {
                "ok": True,
                "account": confirmed.public_dict(),
                **self._account_payload(),
            }
        )

    def _handle_account_view_set(self) -> None:
        payload = self._read_json() or {}
        value = str(payload.get("view") or "").strip()
        if payload.get("auto"):
            value = account_view.AUTO
        if not value:
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少 view 参数")
        if value != account_view.AUTO and value not in self._registered_account_ids():
            return self._send_error(HTTPStatus.BAD_REQUEST, f"没有这个账号：{value}")
        try:
            saved = self.webui_state.set_view_selection(value)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "saved": saved, **self.webui_state.view_payload()})

    def _registered_account_ids(self) -> set[str]:
        if not bool(getattr(self.webui_state.config, "account_system_enabled", False)):
            return set()
        try:
            return {
                account.account_id
                for account in registry_for_config(self.webui_state.config).list_all()
            }
        except Exception:
            return set()

    # ---- 切换 NapCat 登录账号（退出 → 手动登录 → 自动收尾）----------------

    def _handle_account_napcat_status(self) -> None:
        """只读：NapCat 当前登录的账号 + 本项目的自动登录设置。"""

        try:
            self._send_json(napcat_login_state())
        except Exception as exc:  # pragma: no cover - 状态读取失败也要给面板一个答复
            self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))

    def _handle_account_napcat_switch(self) -> None:
        """``logout`` = 退出准备换号；``finish`` = 新号登录后收尾；``cancel`` = 放弃。"""

        if self._refuse_when_read_only("切换登录账号"):
            return
        payload = self._read_json() or {}
        action = str(payload.get("action") or "").strip().lower()
        try:
            if action == "logout":
                result = begin_account_switch()
            elif action == "finish":
                result = finish_account_switch(self.webui_state.config)
            elif action == "cancel":
                result = cancel_account_switch()
            else:
                return self._send_error(
                    HTTPStatus.BAD_REQUEST, "action 必须是 logout、finish 或 cancel"
                )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except (OSError, RuntimeError) as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        LOGGER.info("NapCat 账号切换：action=%s", action)
        self._send_json({**result, "state": napcat_login_state()})
