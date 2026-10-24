"""换号后面板必须跟着读**运行账号**的数据，而不是进程启动时的默认账号。

历史 bug：``WebUIState.view_memory_admin()`` 在 ``auto``（跟随运行账号）时直接返回
``self.memory_admin`` —— 那是进程启动时按 ``BOT_QQ`` 建的。于是 NapCat 换成另一个
QQ 登录后，用户中心读的还是原账号的记忆文件（"用户和群聊没变"），而写路径（保存/
删除记忆、手动备份、QQ 空间名单）也会落到旧账号的数据区。
"""

from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

from atri_webui import server as webui_server


def _stub_state(*, running_id: str | None, base_admin: object) -> object:
    state = types.SimpleNamespace(
        config=object(),
        memory_admin=base_admin,
        _view_lock=threading.Lock(),
        _view_memory_admin=None,
    )
    state.view_account = lambda: None  # auto：不查看别的账号
    state.running_account = lambda: (
        None if running_id is None else types.SimpleNamespace(account_id=running_id)
    )
    # view_memory_admin 内部会调 running_memory_admin / _memory_admin_for_account，
    # 桩对象得把真实实现接上（否则只能测到 AttributeError）。
    state.running_memory_admin = lambda: webui_server.WebUIState.running_memory_admin(state)
    state._memory_admin_for_account = (
        lambda account: webui_server.WebUIState._memory_admin_for_account(state, account)
    )
    return state


def _patch_factories(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        webui_server,
        "memory_admin_for_config",
        lambda config: types.SimpleNamespace(admin_for=config),
    )
    monkeypatch.setattr(
        webui_server,
        "resolve_config",
        lambda base, account, **kwargs: calls.append(account.account_id)
        or f"config:{account.account_id}",
    )


def test_view_memory_admin_follows_running_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_factories(monkeypatch, calls)
    state = _stub_state(running_id="qq:900001003", base_admin=types.SimpleNamespace(admin_for="base"))

    admin = webui_server.WebUIState.view_memory_admin(state)

    assert calls == ["qq:900001003"]
    assert admin.admin_for == "config:qq:900001003"


def test_view_memory_admin_is_cached_per_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_factories(monkeypatch, calls)
    state = _stub_state(running_id="qq:900001003", base_admin=types.SimpleNamespace(admin_for="base"))

    first = webui_server.WebUIState.view_memory_admin(state)
    second = webui_server.WebUIState.view_memory_admin(state)

    assert first is second
    assert calls == ["qq:900001003"]  # 只构造一次


def test_view_memory_admin_falls_back_to_process_admin_without_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_factories(monkeypatch, calls)
    base = types.SimpleNamespace(admin_for="base")
    state = _stub_state(running_id=None, base_admin=base)

    assert webui_server.WebUIState.view_memory_admin(state) is base
    assert calls == []


def test_running_memory_admin_matches_view_when_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """读路径与写路径在 auto 下必须是同一个对象，否则"看到 A 却改到 B"。"""

    calls: list[str] = []
    _patch_factories(monkeypatch, calls)
    state = _stub_state(running_id="qq:900001003", base_admin=types.SimpleNamespace(admin_for="base"))

    assert (
        webui_server.WebUIState.running_memory_admin(state)
        is webui_server.WebUIState.view_memory_admin(state)
    )


def _bind_effective_account(state: object) -> object:
    """桩对象要把 effective_account 接上真实实现（它内部用 view/running 账号）。"""

    state.effective_account = lambda: webui_server.WebUIState.effective_account(state)
    return state


def test_effective_bot_qq_follows_running_account() -> None:
    """换号后目录里代表"机器人自己"的必须是新号，而不是全局 .env 里的旧号。"""

    state = _bind_effective_account(types.SimpleNamespace(
        view_account=lambda: None,
        running_account=lambda: types.SimpleNamespace(account_id="qq:900001003", qq="900001003"),
        view_config=lambda: types.SimpleNamespace(bot_qq="900000002"),
    ))

    assert webui_server.WebUIState.effective_bot_qq(state) == "900001003"


def test_effective_bot_qq_falls_back_to_config() -> None:
    state = _bind_effective_account(types.SimpleNamespace(
        view_account=lambda: None,
        running_account=lambda: None,
        view_config=lambda: types.SimpleNamespace(bot_qq="900000002"),
    ))

    assert webui_server.WebUIState.effective_bot_qq(state) == "900000002"


def test_view_modality_policy_follows_running_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """全局白名单是原账号的（实测 232 条），换号后不能再拿它当用户目录的来源。"""

    account_webui = tmp_path / "account" / "webui"
    account_webui.mkdir(parents=True)
    (account_webui / "modality_access.json").write_text("{}", encoding="utf-8")

    import atri_qq_bot.accounts as accounts_pkg
    import atri_qq_bot.runtime.modality_access as modality_module

    monkeypatch.setattr(
        accounts_pkg,
        "account_data_paths",
        lambda base, account: types.SimpleNamespace(webui_dir=account_webui),
    )
    loaded: list[Path] = []
    monkeypatch.setattr(
        modality_module,
        "load_modality_access_from",
        lambda path: loaded.append(Path(path)) or {"from": str(path)},
    )
    monkeypatch.setattr(webui_server, "load_modality_access", lambda: {"from": "global"})

    state = _bind_effective_account(types.SimpleNamespace(
        config=object(),
        view_account=lambda: None,
        running_account=lambda: types.SimpleNamespace(account_id="qq:900001003", qq="900001003"),
    ))

    policy = webui_server.WebUIState.view_modality_policy(state)

    assert loaded == [account_webui / "modality_access.json"]
    assert policy != {"from": "global"}


def test_view_qzone_targets_follows_running_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """空间互动对象同样是"当前登录那个号"的名单，不能读全局库。"""

    account_db = tmp_path / "account" / "qzone_automation.sqlite3"
    account_db.parent.mkdir(parents=True)
    account_db.write_bytes(b"")

    import atri_qq_bot.accounts as accounts_pkg

    monkeypatch.setattr(
        accounts_pkg,
        "account_data_paths",
        lambda base, account: types.SimpleNamespace(qzone_db_path=account_db),
    )
    monkeypatch.setattr(webui_server, "_read_qzone_targets", lambda path: [{"group_id": "1"}])

    state = _bind_effective_account(types.SimpleNamespace(
        config=object(),
        qzone_automation=types.SimpleNamespace(
            store=types.SimpleNamespace(targets=lambda: [{"group_id": "old"}])
        ),
        view_account=lambda: None,
        running_account=lambda: types.SimpleNamespace(account_id="qq:900001003", qq="900001003"),
    ))

    assert webui_server.WebUIState.view_qzone_targets(state) == [{"group_id": "1"}]


def test_memory_writers_use_the_running_account() -> None:
    """写路径不能再用进程默认账号的 memory_admin（会写进旧账号的数据区）。"""

    from atri_webui.server_parts import handler_core, handler_qzone, handler_stickers_memory

    for module in (handler_core, handler_qzone, handler_stickers_memory):
        source = module.__file__
        with open(source, encoding="utf-8") as stream:
            text = stream.read()
        assert "self.webui_state.memory_admin" not in text, module.__name__


def _insights_stub(running_id: str | None, *, store_path: str | None) -> object:
    store = None if store_path is None else types.SimpleNamespace(path=store_path)
    state = types.SimpleNamespace(
        config=object(),
        _view_lock=threading.Lock(),
        _view_insights_store=None,
        server=types.SimpleNamespace(insights=types.SimpleNamespace(store=store)),
    )
    state.view_account = lambda: None
    state.running_account = lambda: (
        None if running_id is None else types.SimpleNamespace(account_id=running_id, is_default=False)
    )
    return state


def test_view_insights_store_opens_the_running_account_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """进程级评测库指向**别的**账号时必须另开，否则换号后群里还是原账号那一套。"""

    running_db = tmp_path / "running" / "insights.sqlite3"
    running_db.parent.mkdir(parents=True, exist_ok=True)
    running_db.write_bytes(b"")

    import atri_qq_bot.accounts as accounts_pkg
    import atri_qq_bot.insights.store as store_module

    monkeypatch.setattr(
        accounts_pkg,
        "account_data_paths",
        lambda base, account: types.SimpleNamespace(insights_db_path=running_db),
    )
    opened: list[Path] = []
    monkeypatch.setattr(
        store_module,
        "InsightsStore",
        lambda path: opened.append(Path(path)) or types.SimpleNamespace(path=Path(path)),
    )
    state = _insights_stub(
        "qq:900001003", store_path=str(tmp_path / "default" / "insights.sqlite3")
    )

    store = webui_server.WebUIState.view_insights_store(state)

    assert opened == [running_db]
    assert store.path == running_db


def test_view_insights_store_reuses_process_store_when_it_is_the_same_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """默认账号（进程级 runtime 就是它的库）时直接复用，不重复开连接。"""

    default_db = tmp_path / "insights.sqlite3"
    default_db.write_bytes(b"")

    import atri_qq_bot.accounts as accounts_pkg

    monkeypatch.setattr(
        accounts_pkg,
        "account_data_paths",
        lambda base, account: types.SimpleNamespace(insights_db_path=default_db),
    )
    process_store = types.SimpleNamespace(path=str(default_db))
    state = _insights_stub("qq:900000002", store_path=str(default_db))
    state.server.insights.store = process_store

    assert webui_server.WebUIState.view_insights_store(state) is process_store
