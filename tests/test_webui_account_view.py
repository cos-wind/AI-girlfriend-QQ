"""面板「查看账号」的测试。

边界必须清楚：**允许手动切换面板查看哪个账号，但机器人运行哪个账号永远由
NapCat 决定。** 手动切到别的账号时进入只读检视模式——读路径跟随查看账号，
写路径一律拒绝。
"""

from __future__ import annotations

import json
from http import HTTPStatus
from types import SimpleNamespace

import pytest

from atri_webui import account_view
from atri_webui.page import render_index
from atri_webui.server import AtriWebUIHandler
from atri_webui.server_parts.handler_account import view_memory_admin_for


# ---- account_view（纯逻辑）---------------------------------------------


def test_default_selection_is_auto(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(account_view, "VIEW_PATH", tmp_path / "account_view.json")

    assert account_view.load_view_selection() == account_view.AUTO


def test_missing_or_corrupt_file_falls_back_to_auto(tmp_path, monkeypatch) -> None:
    path = tmp_path / "account_view.json"
    monkeypatch.setattr(account_view, "VIEW_PATH", path)

    path.write_text("{not json", encoding="utf-8")
    assert account_view.load_view_selection() == account_view.AUTO

    path.write_text('{"view": 123}', encoding="utf-8")
    assert account_view.load_view_selection() == account_view.AUTO


def test_save_and_load_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(account_view, "VIEW_PATH", tmp_path / "account_view.json")

    saved = account_view.save_view_selection("qq:900001003")

    assert saved == "qq:900001003"
    assert account_view.load_view_selection() == "qq:900001003"


def test_save_rejects_malformed_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(account_view, "VIEW_PATH", tmp_path / "account_view.json")

    with pytest.raises(ValueError):
        account_view.save_view_selection("900001003")


@pytest.mark.parametrize(
    "selection,running,expected",
    [
        ("auto", "qq:1", False),
        ("auto", None, False),
        ("qq:1", "qq:1", False),      # 恰好选中运行账号 → 不是只读
        ("qq:2", "qq:1", True),       # 选中别的账号 → 只读
        ("qq:2", None, True),         # 没有运行账号时选了具体账号 → 只读
        ("", "qq:1", False),
    ],
)
def test_is_read_only(selection: str, running: str | None, expected: bool) -> None:
    assert account_view.is_read_only(selection, running) is expected


def test_describe_reports_read_only_reason() -> None:
    state = account_view.describe("qq:2", "qq:1")

    assert state["selection"] == "qq:2"
    assert state["is_auto"] is False
    assert state["read_only"] is True


# ---- 页面 ---------------------------------------------------------------


def test_page_has_the_view_selector() -> None:
    html = render_index()

    # 选择器现在内联在账号条里（不再单独占一行），id 也随之改为 accountViewSelect。
    assert 'id="accountViewSelect"' in html
    assert "selectAccountView" in html
    assert "/api/account/view" in html


def test_page_has_no_runtime_account_switch() -> None:
    """**运行账号**的切换入口不能出现在页面上。

    面板可以手动选"看哪个账号"（只读），但绝不能有一个把机器人运行账号改掉的
    控件——NapCat 登录的是 Y、机器人却按 X 运行，就会把 Y 的事件写进 X 的库。
    """
    html = render_index()

    assert "switchAccount" not in html
    assert "切换运行账号" not in html
    assert "/api/account/activate" not in html
    assert "/api/accounts/" not in html


# ---- handler ------------------------------------------------------------


class _FakeState:
    def __init__(self, *, read_only: bool = False, enabled: bool = True) -> None:
        self._read_only = read_only
        self.refused: list[str] = []
        self.errors: list[tuple[Any, str]] = []
        self.saved: list[str] = []
        self.config = SimpleNamespace(account_system_enabled=enabled)

    def is_read_only_view(self) -> bool:
        return self._read_only

    def log_read_only_refusal(self, action: str) -> None:
        self.refused.append(action)

    def view_payload(self) -> dict:
        return {
            "selection": "qq:2" if self._read_only else "auto",
            "is_auto": not self._read_only,
            "read_only": self._read_only,
            "running_account_id": "qq:1",
            "viewing_account_id": "qq:2" if self._read_only else "qq:1",
            "enabled": self.config.account_system_enabled,
        }

    def set_view_selection(self, value: str) -> str:
        if value != account_view.AUTO and not value.startswith("qq:"):
            raise ValueError(f"查看账号选择非法：{value!r}")
        self.saved.append(value)
        return value


def _handler(state: _FakeState) -> AtriWebUIHandler:
    handler = AtriWebUIHandler.__new__(AtriWebUIHandler)
    handler.webui_state = state
    handler._send_error = lambda status, message: state.errors.append((status, message))
    return handler


def test_refuse_helper_is_a_noop_when_not_read_only() -> None:
    state = _FakeState(read_only=False)

    assert _handler(state)._refuse_when_read_only("保存记忆") is False
    assert state.refused == []
    assert state.errors == []


def test_refuse_helper_blocks_writes_in_read_only_mode() -> None:
    state = _FakeState(read_only=True)
    handler = _handler(state)

    assert handler._refuse_when_read_only("保存记忆") is True

    assert state.refused == ["保存记忆"]
    assert len(state.errors) == 1
    status, message = state.errors[0]
    assert status == HTTPStatus.BAD_REQUEST
    # 提示要能解释为什么被拒，而不是只说"失败"。
    assert "只读查看" in message
    assert "跟随运行账号" in message


def test_view_set_accepts_auto(monkeypatch) -> None:
    state = _FakeState()
    handler = _handler(state)
    sent: list[dict] = []
    handler._send_json = sent.append
    handler._read_json = lambda: {"auto": True}

    handler._handle_account_view_set()

    assert state.saved == [account_view.AUTO]
    assert sent and sent[0]["ok"] is True
    assert sent[0]["saved"] == account_view.AUTO


def test_view_set_rejects_unknown_account(monkeypatch) -> None:
    state = _FakeState()
    handler = _handler(state)
    handler._read_json = lambda: {"view": "qq:999"}
    handler._registered_account_ids = lambda: {"qq:1"}

    handler._handle_account_view_set()

    assert state.saved == []
    assert len(state.errors) == 1
    assert "没有这个账号" in state.errors[0][1]


def test_view_set_rejects_empty_payload() -> None:
    state = _FakeState()
    handler = _handler(state)
    handler._read_json = lambda: {}

    handler._handle_account_view_set()

    assert state.saved == []
    assert len(state.errors) == 1


def test_view_set_rejects_malformed_selection() -> None:
    """非法值要由 account_view 的校验拦下，而不是存进去。"""
    state = _FakeState()
    handler = _handler(state)
    handler._read_json = lambda: {"view": "900001003"}
    handler._registered_account_ids = lambda: {"900001003"}

    handler._handle_account_view_set()

    assert state.saved == []
    assert len(state.errors) == 1


def test_registered_ids_is_empty_when_account_system_disabled() -> None:
    """关闭时绝不打开注册表（那会在 data/accounts 下建库）。"""
    state = _FakeState(enabled=False)
    handler = _handler(state)

    assert handler._registered_account_ids() == set()


def test_view_memory_admin_prefers_the_viewing_account() -> None:
    """读路径跟随查看账号：宿主提供了 view_memory_admin 就用它。"""
    viewing = object()
    running = object()
    state = _FakeState()
    state.memory_admin = running
    state.view_memory_admin = lambda: viewing
    host = SimpleNamespace(webui_state=state)

    assert view_memory_admin_for(host) is viewing


def test_view_memory_admin_falls_back_when_host_lacks_it() -> None:
    """宿主只提供 memory_admin 时显式退回它，语义上等于"查看账号 = 运行账号"。

    这条回落是必需的：上层 `_reply_strategy_objects` 里的
    `except Exception: items = []` 会把"缺少这个方法"静默变成"记忆对象为空"。
    做成模块级函数还额外兼容"self 是裸 namespace"的调用点（测试里就是）。
    """
    running = object()
    state = _FakeState()
    state.memory_admin = running
    host = SimpleNamespace(webui_state=state)

    assert view_memory_admin_for(host) is running


def test_view_memory_admin_tolerates_a_host_without_state() -> None:
    assert view_memory_admin_for(SimpleNamespace()) is None
    assert view_memory_admin_for(SimpleNamespace(webui_state=None)) is None


def test_method_form_delegates_to_the_module_function() -> None:
    running = object()
    state = _FakeState()
    state.memory_admin = running
    handler = _handler(state)

    assert handler._view_memory_admin() is running


# ---- 按账号读取的数据源 ------------------------------------------------


def test_modality_policy_is_read_per_path_without_touching_the_cache(tmp_path) -> None:
    """看别的账号时读它自己的权限文件；**不回落到全局**。

    回落会让"看 X"显示运行账号的权限配置——那正是用户报的 bug 之一。
    """
    from atri_qq_bot.runtime.modality_access import load_modality_access_from

    own = tmp_path / "modality_access.json"
    own.write_text(
        json.dumps({"users": {"10001": {"vision": True, "voice": False}}}),
        encoding="utf-8",
    )

    policy = load_modality_access_from(own)
    assert policy["users"]["10001"]["vision"] is True

    # 文件不存在 → 空策略（不是全局那份）。
    empty = load_modality_access_from(tmp_path / "missing.json")
    assert empty["users"] == {}


def test_modality_policy_survives_a_corrupt_file(tmp_path) -> None:
    from atri_qq_bot.runtime.modality_access import load_modality_access_from

    broken = tmp_path / "modality_access.json"
    broken.write_text("{not json", encoding="utf-8")

    assert load_modality_access_from(broken)["users"] == {}


def test_qzone_targets_are_read_readonly_and_never_created(tmp_path) -> None:
    """查看别的账号时只读它的库；**库不存在就返回空，且不创建文件**。"""
    import sqlite3

    from atri_webui.server import _read_qzone_targets

    missing = tmp_path / "qzone.sqlite3"
    assert _read_qzone_targets(missing) == []
    assert not missing.exists(), "只读查看不该创建库文件"

    connection = sqlite3.connect(missing)
    try:
        connection.execute(
            "CREATE TABLE qzone_targets(user_id TEXT, nickname TEXT, "
            "enabled_like INTEGER, enabled_comment INTEGER, updated_at REAL)"
        )
        connection.execute(
            "INSERT INTO qzone_targets VALUES('10001','甲',1,0,0)"
        )
        connection.commit()
    finally:
        connection.close()

    rows = _read_qzone_targets(missing)
    assert [row["user_id"] for row in rows] == ["10001"]


def test_qzone_targets_tolerate_a_broken_database(tmp_path) -> None:
    from atri_webui.server import _read_qzone_targets

    broken = tmp_path / "qzone.sqlite3"
    broken.write_text("not a database", encoding="utf-8")

    assert _read_qzone_targets(broken) == []


# ---- 用户中心必须跟随查看账号（用户报的 bug）---------------------------


class _ScopedState:
    """只提供"查看账号"那一套读访问器的桩 state。"""

    def __init__(self, *, viewing_other: bool) -> None:
        self._viewing_other = viewing_other
        self.config = SimpleNamespace(
            bot_qq=900000002, owner_qqs=(900000001,), account_system_enabled=True
        )
        self.server = SimpleNamespace(insights=None)

    def view_account(self):
        return object() if self._viewing_other else None

    def view_insights_store(self):
        # 被查看的账号还没有评测库 → None（不是运行账号的 store）。
        return None

    def view_modality_policy(self):
        return {"users": {}, "groups": {}}

    def view_qzone_targets(self):
        return []

    def view_config(self):
        return self.config

    def is_read_only_view(self) -> bool:
        return self._viewing_other


class _StubMemoryAdmin:
    """只提供"查看账号"记忆的桩——里面有一个运行账号**没有**的用户。"""

    def summary(self) -> dict:
        return {
            "items": [
                {
                    "id": "private:99999",
                    "kind": "person",
                    "display_name": "被查看账号独有的用户",
                    "target": {"user_id": "99999"},
                }
            ]
        }


def _users_handler(state, captured):
    # 必须用完整的 AtriWebUIHandler：_handle_users 会调用
    # HandlerInsightsMixin 上的 _decorate_memory_payload，只用
    # HandlerConfigMixin 会 AttributeError。
    handler = AtriWebUIHandler.__new__(AtriWebUIHandler)
    handler.webui_state = state
    handler._send_json = captured.append
    handler._send_error = lambda status, message: captured.append(
        {"error": message, "status": status}
    )
    handler._group_name_cache = lambda: {}
    handler._qzone_admin = lambda: SimpleNamespace(friends=lambda: [])
    return handler


def test_user_directory_follows_the_viewed_account(monkeypatch) -> None:
    """切换面板到别的账号后，用户中心必须显示**那个账号**的用户。

    用户报的 bug：切到新账号后面板还是原账号的用户和配置。根因是用户中心聚合了
    四个来源，而当时只有 memory 接了"查看账号"，insights / modality / qzone
    仍然读运行账号。
    """
    from atri_webui.server_parts import handler_config

    monkeypatch.setattr(
        handler_config, "view_memory_admin_for", lambda host: _StubMemoryAdmin()
    )
    captured: list[dict] = []
    handler = _users_handler(_ScopedState(viewing_other=True), captured)

    handler._handle_users("")

    payload = captured[0]
    ids = {item["id"] for item in payload["items"]}
    # 被查看账号记忆里的用户必须在。
    assert "qq:99999" in ids
    # 而且**只有**它加上目录本身固定注入的 bot 与 owner（来自 view_config）。
    # 如果 insights/modality/qzone 还读运行账号，这里会多出运行账号的用户。
    assert ids == {"qq:99999", "qq:900000002", "qq:900000001"}


def test_qzone_friends_are_not_fetched_when_viewing_another_account() -> None:
    """QQ 空间是**运行账号**的登录会话；查看别的账号时不能把它的好友混进来。"""
    fetched: list[int] = []

    def _qzone_admin():
        return SimpleNamespace(friends=lambda: fetched.append(1) or [])

    viewing = _users_handler(_ScopedState(viewing_other=True), [])
    viewing._qzone_admin = _qzone_admin
    viewing._handle_users("sync_qzone=1")
    assert fetched == [], "查看别的账号时不该拉运行账号的空间好友"

    running = _users_handler(_ScopedState(viewing_other=False), [])
    running._qzone_admin = _qzone_admin
    running._handle_users("sync_qzone=1")
    assert fetched == [1], "跟随运行账号时应当照常拉好友"


# ---- 页面的进度反馈与"当前在看哪个账号"--------------------------------


def test_page_shows_which_account_the_panel_is_showing() -> None:
    from atri_webui.page import script_account

    part = script_account.PART
    assert "accountActiveHint" in part
    assert "function renderActiveAccountHint" in part
    # 提示里必须明确写清"下面这份数据是谁的"以及"机器人实际在跑谁"。
    assert "机器人实际仍在运行" in part
    assert "跟随运行账号" in part


def test_account_view_switch_has_progress_feedback() -> None:
    """切换要重载 12MB 级的记忆，必须有进度反馈，且不能被 5 秒轮询覆盖掉。"""
    from atri_webui.page import script_account

    part = script_account.PART
    assert "正在切换面板数据…" in part
    assert "正在载入该账号的记忆与用户目录…" in part
    assert "hint.dataset.busy = '1'" in part
    assert "delete hint.dataset.busy" in part
    # 载入提示处于 busy 时不被轮询覆盖。
    assert "if(!hint || hint.dataset.busy === '1') return;" not in part  # 已改为 targets[0]
    assert "targets[0].dataset.busy === '1'" in part
    # 下拉在切换期间禁用，完成后恢复。
    assert "select.disabled = true" in part
    assert "select.disabled = false" in part


def test_scope_hint_appears_both_at_the_top_and_in_the_user_center() -> None:
    """同一份"当前在看哪个账号"的提示要同时出现在顶部与用户中心。"""
    html = render_index()
    from atri_webui.page import script_account

    assert 'id="accountActiveHint"' in html
    assert 'id="userDirectoryScopeHint"' in html
    # 提示要写清 QQ 好友/群/空间动态属于谁，避免用户以为切过去就能看到。
    assert "QQ 好友、群列表、QQ 空间动态只属于正在登录的那个账号" in script_account.PART


# ---- QQ 空间在查看别的账号时必须"不撒谎"-------------------------------


def test_qzone_reads_are_unavailable_when_viewing_another_account() -> None:
    """QQ 空间是运行账号的登录会话；查看别的账号时要返回空 + 原因。

    用户报的 bug：切到新账号后 QQ 空间还显示原账号的动态。显示别人的数据是在撒谎，
    比显示空更糟——用户会以为切过去了。
    """
    from atri_webui.server_parts.handler_qzone import HandlerQZoneMixin

    sent: list[dict] = []
    handler = AtriWebUIHandler.__new__(AtriWebUIHandler)
    handler.webui_state = SimpleNamespace(view_account=lambda: object())
    handler._send_json = sent.append
    handler._send_error = lambda status, message: sent.append({"error": message})

    handler._handle_qzone_dashboard()
    handler._handle_qzone_feeds("user_id=10001")
    handler._handle_qzone_all_feeds("limit=20")
    handler._handle_qzone_friends()

    assert len(sent) == 4
    for payload in sent:
        assert payload["viewing_other_account"] is True
        assert payload["unavailable_reason"], "必须说明为什么没有数据"
        assert "NapCat" in payload["unavailable_reason"]
    # 动态与好友必须是空表，不能是运行账号的。
    assert sent[0]["users"] == []
    assert sent[1]["feeds"] == []
    assert sent[2]["feeds"] == []
    assert sent[3]["friends"] == []


def test_qzone_reason_is_declared_once() -> None:
    """原因文案只有一份，四处返回共用，避免说法不一致。"""
    from atri_webui.server_parts.handler_qzone import HandlerQZoneMixin

    reason = HandlerQZoneMixin.QZONE_VIEWED_OTHER_REASON
    assert reason
    assert "登录会话" in reason
