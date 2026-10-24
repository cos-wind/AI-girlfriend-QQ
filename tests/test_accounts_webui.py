"""账号系统 WebUI 接口与横幅的测试（阶段 5）。

关键安全断言：**账号系统关闭时 `/api/account/current` 绝不打开注册表**——
那会在 ``data/accounts`` 下建库，破坏"开关关着就等于今天的代码路径"这条承诺。
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from atri_qq_bot.accounts import (
    AccountRegistry,
    AccountSwitchCoordinator,
    bootstrap_from_config,
)
from atri_qq_bot.config import load_config
from atri_webui.page import render_index
from atri_webui.server import AtriWebUIHandler

BOT_QQ = 900000002
OTHER_QQ = 900001003


def _config(tmp_path, *, enabled: bool, follow: bool = False):
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
    )


def _handler(config, coordinator=None):
    """借 AtriWebUIHandler 的方法，但用轻量 state，不构造整个 WebUIState。"""
    handler = AtriWebUIHandler.__new__(AtriWebUIHandler)
    handler.webui_state = SimpleNamespace(
        config=config,
        server=SimpleNamespace(account_coordinator=coordinator),
    )
    return handler


def _coordinator(config, account):
    return AccountSwitchCoordinator(
        config,
        build=lambda target, previous: SimpleNamespace(
            config=config, layout=None, resources={}
        ),
    )


# ---- 页面渲染 -----------------------------------------------------------


def test_page_contains_the_account_banner_and_script() -> None:
    html = render_index()

    assert 'id="accountBanner"' in html
    assert "loadAccountBanner" in html
    assert "/api/account/current" in html
    assert "startAccountBanner" in html
    assert "account-banner" in html  # CSS 也在


def test_page_has_exactly_one_script_block() -> None:
    """整页只能有**一个** ``<script>`` 块。

    所有 ``script_*.py`` 的 PART 都拼在同一个块里：``document_head.py`` 开标签、
    ``script_voice_test.py`` 结尾的 ``</script>`` 关标签。

    任何一个 ``script_*.py`` 自带 ``<script>`` / ``</script>``，都会：
    1. 在 JS 中间插进一个 ``<script>`` → 语法错误（控制台一堆报错）；
    2. **提前关闭整块脚本** → 后面所有 JS 变成页面上的纯文本 → 面板看起来"乱码"。

    这个错误真的发生过（账号脚本最初被写成了自带标签的独立块）。所以这里同时钉住
    标签数量和"脚本块没被提前截断"。
    """
    import re

    html = render_index()

    assert html.count("<script>") == 1
    assert html.count("</script>") == 1

    body = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    # 被提前截断时 body 只有几千字符。
    assert len(body) > 100_000
    # 第一个脚本模块与最后一个脚本模块的内容都必须在同一个块里。
    assert "startAccountBanner" in body
    assert "loadVoiceTestState" in body


def test_no_script_part_opens_or_closes_a_script_tag() -> None:
    """逐个检查 script_*.py 的 PART：都不许自带 script 标签。

    比"整页只有一个块"更早定位问题——它会直接告诉你是哪个模块写错了。
    """
    from atri_webui.page import script_account, script_evaluation, script_summary

    for module in (script_account, script_evaluation, script_summary):
        assert "<script>" not in module.PART, module.__name__
        assert "</script>" not in module.PART, module.__name__


def test_banner_switches_napcat_login_but_view_selection_stays_read_only() -> None:
    """账号条提供的是「切换 QQ 账号（NapCat 登录号）」，不是"把面板数据切到某号"。

    历史设计里这里断言"页面不能出现任何切换入口"——因为面板跟随 NapCat，运行账号
    不由 UI 决定。现在多出来的入口是**真的去换 NapCat 登录的账号**（清自动登录 →
    重启 NapCat → 打开登录页），而"面板查看哪个账号"仍然只有 ``accountViewSelect``
    一个只读选择器；也**没有**"直接把机器人账号设成某个号"这种绕过 NapCat 的入口。
    """

    html = render_index()

    # 新增：切换 NapCat 登录账号。
    assert 'id="accountSwitchNapcat"' in html
    assert "switchNapcatAccount(" in html
    assert "finishNapcatAccount(" in html
    assert "cancelNapcatSwitch(" in html
    assert "/api/account/napcat/switch" in html
    assert "/api/account/napcat'" in html or '/api/account/napcat"' in html
    # 仍然没有"绕开 NapCat 直接改运行账号"的入口。
    assert "switchAccount" not in html


def test_napcat_switch_ui_is_built_once_and_polled() -> None:
    """切换面板同样**只在壳子里建一次**，5 秒轮询只更新文字。

    和账号管理表单同一个坑：轮询里重建 DOM 会把用户正在用的东西抽走。
    """

    from atri_webui.page import script_account

    part = script_account.PART

    # 结构在壳子里（ensureAccountBarShell），轮询函数里不能再写 innerHTML = ...
    shell_start = part.index("function ensureAccountBarShell")
    shell_end = part.index("function toggleAddAccountForm")
    shell = part[shell_start:shell_end]
    assert 'id="accountNapcatPanel"' in shell
    assert 'id="accountNapcatLoginLink"' in shell
    assert 'id="accountNapcatFinish"' in shell

    render_start = part.index("function renderNapcatAccountState")
    render_end = part.index("async function loadNapcatAccountState")
    render = part[render_start:render_end]
    assert "innerHTML" not in render
    # 自动收尾每个账号只做一次（否则 5 秒轮询会反复写配置）。
    assert "window._napcatFinishedUins" in render
    assert "state.auto_finish_ready" in render


def test_account_manager_is_collapsed_at_the_top_not_a_tab() -> None:
    """账号管理收在**顶部账号条**里，不单独开标签页，也不重复列一遍账号。

    顶部已经有「面板显示」选择器了，再开一个「机器人账号」标签页是重复的；
    管理入口（新增账号。停用/启用）**只在需要时**出现：新增是默认收起的行内表单，
    停用/启用只在"面板正查看某个已确认账号"时才挂出来。
    """
    html = render_index()

    # 不能再有账号标签页。
    assert "showTab(event,'accounts')" not in html
    assert 'id="accounts" class="panel"' not in html
    # 管理入口在顶部账号条里，且新增表单默认收起。
    assert 'id="accountManagerDetails"' not in html  # 旧的折叠区已被账号条取代
    assert 'id="accountAddToggle"' in html
    assert 'id="accountAddInline"' in html
    assert 'class="account-add-inline" hidden' in html
    # 面板显示仍然是唯一的"查看哪个账号"入口。
    assert html.count('id="accountViewSelect"') == 1
    # 换 NapCat 登录账号是另一个动作，不能和"面板显示"混成一个入口。
    assert 'id="accountSwitchNapcat"' in html


def test_account_script_does_not_depend_on_other_page_modules() -> None:
    """账号脚本自带给定的时间格式化，不跨模块调用 qzoneDate 之类。

    页面模块是按顺序拼接的；一旦依赖别的模块里的函数，加载顺序变化就会静默失效。
    """
    from atri_webui.page import script_account

    part = script_account.PART
    assert "accountTimeText" in part
    assert "qzoneDate" not in part


# ---- 关闭时完全惰性 -----------------------------------------------------


def test_disabled_payload_does_not_create_the_registry(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)
    handler = _handler(config)

    payload = handler._account_payload()

    assert payload["ok"] is True
    assert payload["enabled"] is False
    assert payload["accounts"] == []
    assert payload["pending"] == []
    assert payload["current"] is None
    # 核心承诺：关闭时连注册表文件都不建。
    assert not config.accounts_db_path.exists()
    assert not config.accounts_db_path.parent.exists()


def test_disabled_payload_reports_bot_qq_for_display(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)

    payload = _handler(config)._account_payload()

    assert payload["bot_qq"] == str(BOT_QQ)
    assert payload["follow_napcat"] is False


# ---- 开启后的载荷 -------------------------------------------------------


def test_enabled_payload_lists_accounts(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    AccountRegistry(config.accounts_db_path).register(
        OTHER_QQ, confirmed=True, enabled=True
    )
    handler = _handler(config)

    payload = handler._account_payload()

    assert payload["enabled"] is True
    qqs = sorted(item["qq"] for item in payload["accounts"])
    assert qqs == sorted([str(BOT_QQ), str(OTHER_QQ)])
    # 两个都已确认，所以没有待确认项。
    assert payload["pending"] == []


def test_unconfirmed_accounts_are_reported_as_pending(tmp_path) -> None:
    config = _config(tmp_path, enabled=True, follow=True)
    bootstrap_from_config(config)
    AccountRegistry(config.accounts_db_path).observe_from_napcat(OTHER_QQ)
    handler = _handler(config)

    payload = handler._account_payload()

    pending_qqs = [item["qq"] for item in payload["pending"]]
    assert pending_qqs == [str(OTHER_QQ)]
    # 待确认账号不能获得数据目录。
    assert not (tmp_path / "accounts" / f"qq-{OTHER_QQ}").exists()


def test_current_account_and_layout_are_exposed(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    account = bootstrap_from_config(config)
    coordinator = AccountSwitchCoordinator(
        config,
        build=lambda target, previous: SimpleNamespace(
            config=config,
            layout=SimpleNamespace(
                public_dict=lambda: {"is_default": True, "root": None}
            ),
            resources={},
        ),
    )
    coordinator.switch(account, reason="test")
    handler = _handler(config, coordinator)

    payload = handler._account_payload()

    assert payload["current"] is not None
    assert payload["current"]["qq"] == str(BOT_QQ)
    assert payload["layout"] == {"is_default": True, "root": None}
    assert len(payload["events"]) == 1
    assert payload["events"][0]["to_account_id"] == account.account_id
    assert payload["stale_writes"] == 0


def test_stale_writes_are_surfaced_for_diagnosis(tmp_path) -> None:
    """过期写入计数持续增长说明有调用点在延迟解析路径，面板要能看到。"""
    config = _config(tmp_path, enabled=True)
    account = bootstrap_from_config(config)
    coordinator = AccountSwitchCoordinator(
        config,
        build=lambda target, previous: SimpleNamespace(
            config=config, layout=None, resources={}
        ),
    )
    captured = coordinator.capture().generation
    coordinator.switch(account)
    coordinator.discard_if_stale(captured, label="test")
    handler = _handler(config, coordinator)

    payload = handler._account_payload()

    assert payload["stale_writes"] == 1


def test_missing_coordinator_is_tolerated(tmp_path) -> None:
    """账号系统开着但协调器还没建起来（例如 WebUI 与 OneBot 分离启动）时不报错。"""
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)

    payload = _handler(config, coordinator=None)._account_payload()

    assert payload["enabled"] is True
    assert payload["current"] is None
    assert payload["events"] == []
    assert len(payload["accounts"]) == 1


def test_registry_read_failure_is_reported_not_raised(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    # 用一个不可能当数据库用的路径，模拟注册表损坏。
    broken = replace(config, accounts_db_path=tmp_path)
    bootstrap_from_config(_config(tmp_path, enabled=True))

    payload = _handler(broken)._account_payload()

    # 面板要能显示错误，而不是让整个请求 500。
    assert payload["ok"] is True
    assert payload.get("error")
    assert payload["accounts"] == []


# ---- 确认新账号 ---------------------------------------------------------


def _capturing_handler(config):
    """带 _send_json / _send_error 捕获的 handler 桩。"""
    handler = _handler(config)
    captured: dict[str, Any] = {"json": [], "errors": [], "payload": {}}
    handler._send_json = captured["json"].append
    handler._send_error = lambda status, message: captured["errors"].append(
        (status, message)
    )
    handler._read_json = lambda: captured["payload"]
    return handler, captured


def test_confirm_marks_account_and_creates_its_layout(tmp_path) -> None:
    """确认是"发现新账号"到"真正启用"之间的人工闸门。

    数据目录必须**在这一步才**创建——未确认的账号不该获得任何数据区。
    """
    config = _config(tmp_path, enabled=True, follow=True)
    bootstrap_from_config(config)
    registry = AccountRegistry(config.accounts_db_path)
    registry.observe_from_napcat(OTHER_QQ)
    account_dir = tmp_path / "accounts" / f"qq-{OTHER_QQ}"
    assert not account_dir.exists()

    handler, captured = _capturing_handler(config)
    captured["payload"] = {"account_id": f"qq:{OTHER_QQ}"}
    handler._handle_account_confirm()

    assert captured["errors"] == []
    assert captured["json"], "应当返回成功载荷"
    confirmed = registry.get_by_qq(OTHER_QQ)
    assert confirmed is not None
    assert confirmed.confirmed is True
    assert confirmed.enabled is True
    # 数据目录到这一步才出现。
    assert account_dir.is_dir()
    assert (account_dir / "memory").is_dir()
    # 返回的载荷里 pending 应该空了。
    assert captured["json"][0]["pending"] == []


def test_confirm_rejects_unknown_account(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"account_id": "qq:999999"}

    handler._handle_account_confirm()

    assert captured["json"] == []
    assert len(captured["errors"]) == 1
    assert "没有这个账号" in captured["errors"][0][1]


def test_confirm_rejects_missing_account_id(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {}

    handler._handle_account_confirm()

    assert captured["json"] == []
    assert len(captured["errors"]) == 1


def test_confirm_rejects_when_account_system_disabled(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"account_id": f"qq:{OTHER_QQ}"}

    handler._handle_account_confirm()

    assert captured["json"] == []
    assert "未启用" in captured["errors"][0][1]
    # 关闭时绝不创建注册表。
    assert not config.accounts_db_path.exists()


def test_page_has_the_confirm_action() -> None:
    html = render_index()

    assert "confirmAccount" in html
    assert "/api/account/confirm" in html
    assert "确认并启用" in html


# ---- 手动新增账号 -------------------------------------------------------


def test_add_registers_account_and_creates_its_layout(tmp_path) -> None:
    """手动登记：NapCat 总是自动登录同一个号，用户没法随手换号，
    所以"跟随 NapCat"这条路径永远触发不了——手动登记之后面板才有账号可切。"""
    config = _config(tmp_path, enabled=True, follow=False)
    bootstrap_from_config(config)
    account_dir = tmp_path / "accounts" / f"qq-{OTHER_QQ}"
    assert not account_dir.exists()

    handler, captured = _capturing_handler(config)
    captured["payload"] = {"qq": str(OTHER_QQ), "display_name": "小号"}
    handler._handle_account_add()

    assert captured["errors"] == []
    assert captured["json"], "应当返回成功载荷"
    registry = AccountRegistry(config.accounts_db_path)
    added = registry.get_by_qq(OTHER_QQ)
    assert added is not None
    # 手动登记的直接是已确认 + 启用（用户明确要求创建这个数据区）。
    assert added.confirmed is True
    assert added.enabled is True
    assert added.display_name == "小号"
    assert added.is_default is False
    # 数据目录在这一步创建。
    assert account_dir.is_dir()
    assert (account_dir / "memory").is_dir()
    # 返回载荷里应该有两个账号。
    assert len(captured["json"][0]["accounts"]) == 2


def test_add_defaults_display_name_when_blank(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"qq": str(OTHER_QQ)}

    handler._handle_account_add()

    added = AccountRegistry(config.accounts_db_path).get_by_qq(OTHER_QQ)
    assert added is not None
    assert added.display_name == f"QQ {OTHER_QQ}"


def test_add_rejects_existing_account(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"qq": str(BOT_QQ)}

    handler._handle_account_add()

    assert captured["json"] == []
    assert len(captured["errors"]) == 1
    assert "已存在" in captured["errors"][0][1]


def test_add_rejects_non_numeric_qq(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"qq": "abc"}

    handler._handle_account_add()

    assert captured["json"] == []
    assert "纯数字" in captured["errors"][0][1]


def test_add_rejects_when_account_system_disabled(tmp_path) -> None:
    config = _config(tmp_path, enabled=False)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"qq": str(OTHER_QQ)}

    handler._handle_account_add()

    assert captured["json"] == []
    assert "未启用" in captured["errors"][0][1]
    # 关闭时绝不创建注册表。
    assert not config.accounts_db_path.exists()


# ---- 启停账号 -----------------------------------------------------------


def test_update_toggles_enabled(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    handler, captured = _capturing_handler(config)
    captured["payload"] = {"account_id": account.account_id, "enabled": False}
    handler._handle_account_update()

    assert captured["errors"] == []
    updated = registry.get(account.account_id)
    assert updated is not None
    assert updated.enabled is False


def test_update_rejects_unknown_account(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"account_id": "qq:999999", "enabled": True}

    handler._handle_account_update()

    assert captured["json"] == []
    assert "没有这个账号" in captured["errors"][0][1]


def test_update_rejects_missing_enabled(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    handler, captured = _capturing_handler(config)
    captured["payload"] = {"account_id": f"qq:{BOT_QQ}"}

    handler._handle_account_update()

    assert captured["json"] == []
    assert "缺少 enabled" in captured["errors"][0][1]


def test_update_does_not_expose_setting_default(tmp_path) -> None:
    """刻意不提供"设为默认"：默认账号决定未跟随时机器人跑哪个号，
    把它改成 NapCat 没登录的号会让事件全部被丢弃（表现是"发消息完全没反应"）。
    """
    from atri_webui.server_parts import handler_account as module

    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)

    handler, captured = _capturing_handler(config)
    # 即使请求里带了 is_default，也不该被采纳。
    captured["payload"] = {
        "account_id": account.account_id,
        "enabled": True,
        "is_default": True,
    }
    handler._handle_account_update()

    assert registry.get(account.account_id).is_default is False
    assert registry.default_account().qq == str(BOT_QQ)
    assert module is not None


# ---- 账号数据信息 -------------------------------------------------------


def test_payload_includes_each_account_data_location(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    AccountRegistry(config.accounts_db_path).register(
        OTHER_QQ, confirmed=True, enabled=True
    )

    payload = _handler(config)._account_payload()

    by_qq = {item["qq"]: item for item in payload["accounts"]}
    # 默认账号 = 沿用全局路径，未搬迁。
    assert by_qq[str(BOT_QQ)]["data"]["is_default"] is True
    assert by_qq[str(BOT_QQ)]["data"]["root"] is None
    # 非默认账号 = 自己的目录，且此时还没建出来。
    assert by_qq[str(OTHER_QQ)]["data"]["is_default"] is False
    assert str(tmp_path) in by_qq[str(OTHER_QQ)]["data"]["root"]
    assert by_qq[str(OTHER_QQ)]["data"]["memory_exists"] is False
    assert by_qq[str(OTHER_QQ)]["data"]["root_exists"] is False


def test_payload_reports_existing_account_data_size(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)
    registry = AccountRegistry(config.accounts_db_path)
    account = registry.register(OTHER_QQ, confirmed=True, enabled=True)
    from atri_qq_bot.accounts import ensure_account_layout

    layout = ensure_account_layout(config, account)
    layout.memory_path.write_text('{"version":2,"conversations":{}}', encoding="utf-8")

    payload = _handler(config)._account_payload()

    item = next(entry for entry in payload["accounts"] if entry["qq"] == str(OTHER_QQ))
    assert item["data"]["memory_exists"] is True
    assert item["data"]["memory_bytes"] > 0
    assert item["data"]["root_exists"] is True


def test_payload_surfaces_running_account_id(tmp_path) -> None:
    config = _config(tmp_path, enabled=True)
    bootstrap_from_config(config)

    payload = _handler(config)._account_payload()

    # 桩宿主没有 running_account_id → 回落成 None，而不是整条载荷报错。
    assert payload["running_account_id"] is None


def test_page_has_the_account_manager() -> None:
    html = render_index()

    assert "新增账号" in html
    assert "addAccount" in html
    assert "/api/account/add" in html
    # 停用/启用仍然是可达的——账号条只在"查看某个已确认账号"时把它挂出来，
    # 但入口必须真的存在（否则 /api/account/update 就成了没有 UI 的死端点）。
    assert "/api/account/update" in html
    assert "toggleAccountEnabled" in html
    assert 'id="accountAddQq"' in html


def test_account_manager_form_is_not_rebuilt_by_polling() -> None:
    """账号条的**结构只建一次**，不能被 5 秒轮询重建。

    这个 bug 真的发生过：面板每 5 秒轮询 /api/account/current，而渲染函数每次都
    ``host.innerHTML = ...`` 重建整块区域——用户正在填的 QQ 号输入框被销毁重建，
    表现就是"数字填进去一会又没了"。

    所以这里把防回归的结构钉住：壳子只建一次、渲染只更新文字、下拉按签名判断是否
    重建、按钮还在等请求返回时不替换 DOM。
    """
    from atri_webui.page import script_account

    part = script_account.PART

    # 壳子只建一次（有这个守卫，输入框才不会被反复重建）。
    assert "function ensureAccountBarShell" in part
    assert "if($('accountCurrentName')) return;" in part
    # 渲染路径只更新内容：结构（表单、面板、下拉）都在壳子函数里建。
    render_start = part.index("function renderAccountBanner")
    render_end = part.index("function renderViewOptions")
    render = part[render_start:render_end]
    assert "ensureAccountBarShell(host);" in render
    assert 'id="accountAddQq"' not in render
    assert 'id="accountNapcatPanel"' not in render
    # 渲染里唯一的 innerHTML 清空只发生在"账号系统未启用"的隐藏分支。
    assert render.count("host.innerHTML") == 1
    # 下拉不能每轮重建，否则用户刚打开的下拉会被抽掉。
    assert "select.dataset.signature !== signature" in part
    # 按钮还在等请求返回时不替换 DOM（withButtonBusy 会把按钮置为 disabled）。
    assert "slot.querySelector('button[disabled]')" in part
    # 壳子必须包含新增表单与切换面板，渲染才能按 id 找到它们。
    shell_start = part.index("function ensureAccountBarShell")
    shell_end = part.index("function toggleAddAccountForm")
    shell = part[shell_start:shell_end]
    assert 'id="accountAddQq"' in shell
    assert 'id="accountAddInline"' in shell
