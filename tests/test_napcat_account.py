"""切换 NapCat 登录账号：清自动登录 → 重启 → 新号登录后自动收尾。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from atri_webui import napcat_account


@pytest.fixture(autouse=True)
def isolated_auth_cache():
    napcat_account._CREDENTIALS.clear()
    napcat_account._AUTH_RETRY_AFTER.clear()
    yield
    napcat_account._CREDENTIALS.clear()
    napcat_account._AUTH_RETRY_AFTER.clear()


def test_concurrent_poll_authenticates_only_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time
    monkeypatch.setattr(napcat_account, "_napcat_base", lambda: ("http://concurrent.test", "test"))
    auth = []
    def post(url, payload, token=""):
        if url.endswith("/auth/login"):
            auth.append(url)
            time.sleep(0.01)
            return {"code": 0, "data": {"Credential": "shared"}}
        return {"code": 0, "data": {"isLogin": True}}
    monkeypatch.setattr(napcat_account, "_post_json", post)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: napcat_account._napcat_call("/QQLogin/CheckLoginStatus"), range(16)))
    assert len(auth) == 1
    assert all(result["data"]["isLogin"] for result in results)


@pytest.mark.parametrize("http_error", [False, True])
def test_rejected_credential_is_renewed_once(monkeypatch, http_error):
    monkeypatch.setattr(napcat_account, "_napcat_base", lambda: ("http://renew.test", "test"))
    auth = []
    def post(url, payload, token=""):
        if url.endswith("/auth/login"):
            auth.append(url)
            return {"code": 0, "data": {"Credential": str(len(auth))}}
        if token == "1":
            if http_error:
                raise napcat_account.HTTPError(url, 401, "Unauthorized", {}, None)
            return {"code": -1, "message": "Unauthorized"}
        return {"code": 0, "data": {"isLogin": True}}
    monkeypatch.setattr(napcat_account, "_post_json", post)
    assert napcat_account._napcat_call("/QQLogin/CheckLoginStatus")["data"]["isLogin"]
    assert len(auth) == 2


def test_auth_cooldown_does_not_repeat_rate_limited_login(monkeypatch):
    monkeypatch.setattr(napcat_account, "_napcat_base", lambda: ("http://limited.test", "test"))
    clock, calls = [100.0], []
    monkeypatch.setattr(napcat_account.time, "monotonic", lambda: clock[0])
    def post(url, payload, token=""):
        calls.append(url)
        return {"code": -1, "message": "login rate limit"}
    monkeypatch.setattr(napcat_account, "_post_json", post)
    for _ in range(12):
        with pytest.raises(RuntimeError, match="限流"):
            napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    assert len(calls) == 1
    clock[0] += 61
    with pytest.raises(RuntimeError, match="限流"):
        napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    assert len(calls) == 2


def test_permanently_rejected_credentials_do_not_create_auth_storm(monkeypatch):
    monkeypatch.setattr(napcat_account, "_napcat_base", lambda: ("http://rejected.test", "test"))
    auth = []
    def post(url, payload, token=""):
        if url.endswith("/auth/login"):
            auth.append(url)
            return {"code": 0, "data": {"Credential": str(len(auth))}}
        return {"code": -1, "message": "Unauthorized"}
    monkeypatch.setattr(napcat_account, "_post_json", post)
    for _ in range(12):
        with pytest.raises(RuntimeError):
            napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    assert len(auth) == 2


@pytest.mark.parametrize("response", [{"code": -1, "data": {"isLogin": False}},
    {"code": 0, "data": {}}, {"code": 0, "data": "bad"}, {"code": 0, "data": {"isLogin": "false"}}])
def test_invalid_status_payload_is_unknown(monkeypatch, tmp_path, response):
    _prepare_config(monkeypatch, tmp_path)
    monkeypatch.setattr(napcat_account, "_napcat_call", lambda *args: response)
    state = napcat_account.napcat_login_state(lightweight=True)
    assert not state["status_known"] and state["error"]


def test_cache_respects_token_changes_and_expiry(monkeypatch):
    target, clock, auth = ["http://cache.test", "first"], [100.0], []
    monkeypatch.setattr(napcat_account, "_napcat_base", lambda: tuple(target))
    monkeypatch.setattr(napcat_account.time, "monotonic", lambda: clock[0])
    def post(url, payload, token=""):
        if url.endswith("/auth/login"):
            auth.append(url)
            return {"code": 0, "data": {"Credential": str(len(auth))}}
        return {"code": 0}
    monkeypatch.setattr(napcat_account, "_post_json", post)
    napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    target[1] = "second"
    napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    clock[0] += 3001
    napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    assert len(auth) == 3


def _load_launcher_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "launch"
        / "qq_legacy"
        / "hidden_launcher.py"
    )
    spec = importlib.util.spec_from_file_location("atri_napcat_account_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_quick_account_file_path_matches_launcher() -> None:
    """两边各写了一份路径常量，漂移会让"切换账号"静默失效。"""

    launcher = _load_launcher_module()

    assert Path(launcher.NAPCAT_QUICK_ACCOUNT_FILE) == napcat_account.QUICK_ACCOUNT_FILE


def test_launcher_quick_account_override_semantics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher = _load_launcher_module()
    target = tmp_path / "napcat-quick-account.txt"
    monkeypatch.setattr(launcher, "NAPCAT_QUICK_ACCOUNT_FILE", target)

    assert launcher.napcat_quick_account() is None  # 文件不存在 → 按 BOT_QQ

    target.write_text("off\n", encoding="utf-8")
    assert launcher.napcat_quick_account() == ""  # 显式手动登录

    target.write_text("900000001\n", encoding="utf-8")
    assert launcher.napcat_quick_account() == "900000001"

    target.write_text("not-a-uin\n", encoding="utf-8")
    assert launcher.napcat_quick_account() is None


def test_isolated_qq_arguments_drop_quick_login_when_no_uin(tmp_path: Path) -> None:
    """没有指定账号就绝不能带 -q，否则 QQ 会用旧会话登回原账号。"""

    launcher = _load_launcher_module()
    profile = tmp_path / "profile"

    with_uin = launcher.isolated_qq_arguments(Path("QQ.exe"), "900000002", profile)
    without = launcher.isolated_qq_arguments(Path("QQ.exe"), "", profile)

    assert "-q" in with_uin and "900000002" in with_uin
    assert "-q" not in without
    assert all("900000002" not in item for item in without)


def _prepare_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    """把 NapCat 的 webui.json / config/.env 指向临时文件。"""

    napcat_dir = tmp_path / "napcat"
    (napcat_dir / "config").mkdir(parents=True)
    webui_path = napcat_dir / "config" / "webui.json"
    webui_path.write_text(
        json.dumps({"port": 6100, "token": "abc123", "autoLoginAccount": "900000002"}),
        encoding="utf-8",
    )
    (napcat_dir / "config" / ".env").write_text(
        "NAPCAT_QUICK_ACCOUNT=900000002\nOTHER=1\n", encoding="utf-8"
    )
    monkeypatch.setattr(napcat_account, "webui_config_path", lambda: webui_path)
    monkeypatch.setattr(
        napcat_account,
        "napcat_webui_access",
        lambda: {"configured": True, "reachable": True, "host": "::", "port": 6100,
                 "url": "http://127.0.0.1:6100/webui?token=abc123", "config_path": str(webui_path)},
    )
    return webui_path, napcat_dir / "config" / ".env"


def test_login_state_reads_current_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_config(monkeypatch, tmp_path)
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", tmp_path / "quick.txt")

    def fake_call(path: str, payload: dict | None = None) -> dict:
        return {
            "/QQLogin/CheckLoginStatus": {"data": {"isLogin": True, "loginPhase": "ready"}},
            "/QQLogin/GetQQLoginInfo": {"data": {"uin": "900000002", "nick": "ATRI", "online": True}},
            "/QQLogin/GetQuickLoginQQ": {"data": "900000002"},
        }[path]

    monkeypatch.setattr(napcat_account, "_napcat_call", fake_call)

    state = napcat_account.napcat_login_state()

    assert state["is_login"] is True
    assert state["uin"] == "900000002"
    assert state["nick"] == "ATRI"
    assert state["auto_login_account"] == "900000002"
    assert state["auto_finish_ready"] is False  # 还没进入"手动登录"模式


def test_poll_reuses_webui_credential_instead_of_hitting_login_rate_limit(monkeypatch):
    monkeypatch.setattr(napcat_account, "_napcat_base", lambda: ("http://poll.test", "test-token"))
    calls = []
    def post(url, payload, token=""):
        calls.append(url)
        if url.endswith("/auth/login"):
            return {"code": 0, "data": {"Credential": "test-credential"}}
        assert token == "test-credential"
        return {"code": 0, "data": {}}
    monkeypatch.setattr(napcat_account, "_post_json", post)
    for _ in range(12):
        napcat_account._napcat_call("/QQLogin/CheckLoginStatus")
    assert sum(url.endswith("/auth/login") for url in calls) == 1


def test_optional_login_info_failure_does_not_mean_logged_out(monkeypatch, tmp_path):
    _prepare_config(monkeypatch, tmp_path)
    def call(path, payload=None):
        if path.endswith("CheckLoginStatus"):
            return {"code": 0, "data": {"isLogin": True, "loginPhase": "ready"}}
        raise RuntimeError("optional info unavailable")
    monkeypatch.setattr(napcat_account, "_napcat_call", call)
    state = napcat_account.napcat_login_state()
    assert state["is_login"] is True
    assert state["status_known"] is True


def test_status_read_failure_is_unknown_instead_of_confirmed_logout(monkeypatch, tmp_path):
    _prepare_config(monkeypatch, tmp_path)
    def call(*args, **kwargs):
        raise RuntimeError("login rate limit")
    monkeypatch.setattr(napcat_account, "_napcat_call", call)
    state = napcat_account.napcat_login_state()
    assert state["status_known"] is False
    assert state["error"]


def test_qr_poll_only_requests_login_status(monkeypatch, tmp_path):
    _prepare_config(monkeypatch, tmp_path)
    calls = []
    def call(path, payload=None):
        calls.append(path)
        return {"code": 0, "data": {"isLogin": False, "loginPhase": "waiting_qrcode", "qrcodeurl": "https://qq.test/qr"}}
    monkeypatch.setattr(napcat_account, "_napcat_call", call)
    state = napcat_account.napcat_login_state(lightweight=True)
    assert state["status_known"] and state["qrcode_url"]
    assert calls == ["/QQLogin/CheckLoginStatus"]


def test_begin_switch_clears_auto_login_then_restarts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    webui_path, env_path = _prepare_config(monkeypatch, tmp_path)
    quick_file = tmp_path / "napcat-quick-account.txt"
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", quick_file)
    monkeypatch.setattr(
        napcat_account, "napcat_login_state", lambda: {"ok": True, "uin": "900000002", "nick": "ATRI"}
    )
    spawned: list[str] = []
    monkeypatch.setattr(napcat_account, "_spawn_launcher", lambda mode: spawned.append(mode))

    result = napcat_account.begin_account_switch()

    # 快速登录覆盖文件必须是 "off"：否则重启后 QQ 会拿 -q 旧号登回去。
    assert quick_file.read_text(encoding="utf-8").strip() == napcat_account.MANUAL_LOGIN
    # webui.json 的自动登录清空，且**不能带 BOM**（否则 NapCat/ATRI 都读不出来）。
    raw = webui_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["autoLoginAccount"] == ""
    # NapCat 自己的 config/.env 也要清，并保留其它行。
    env_text = env_path.read_text(encoding="utf-8")
    assert "NAPCAT_QUICK_ACCOUNT=" in env_text
    assert "NAPCAT_QUICK_ACCOUNT=900000002" not in env_text
    assert "OTHER=1" in env_text
    assert spawned == ["napcat-restart"]
    assert result["previous_uin"] == "900000002"


def test_remember_login_persists_session_and_history_before_setup(monkeypatch, tmp_path):
    from atri_qq_bot.accounts import AccountRegistry

    webui_path, env_path = _prepare_config(monkeypatch, tmp_path)
    quick_file = tmp_path / "quick.txt"
    quick_file.write_text("off\n", encoding="utf-8")
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", quick_file)
    config = SimpleNamespace(account_system_enabled=True, accounts_db_path=tmp_path / "accounts.sqlite3")
    state = {"status_known": True, "is_login": True, "uin": "900000001", "nick": "已登录账号"}

    napcat_account.remember_login(config, state)

    assert napcat_account.quick_account_override() == state["uin"]
    assert json.loads(webui_path.read_text(encoding="utf-8"))["autoLoginAccount"] == state["uin"]
    assert "NAPCAT_QUICK_ACCOUNT=900000001" in env_path.read_text(encoding="utf-8")
    history = napcat_account.login_history(config)
    assert [(row["qq"], row["display_name"]) for row in history] == [(state["uin"], state["nick"])]
    assert history[0]["last_login_at"] is not None
    # Remembering a session does not grant the new account permission to reply.
    account = AccountRegistry(config.accounts_db_path).get("qq:900000001")
    assert not account.confirmed and not account.enabled
    napcat_account.remember_login(config, state)
    assert len(napcat_account.login_history(config)) == 1


@pytest.mark.parametrize("changes", [{"status_known": False}, {"is_login": False}, {"uin": ""}])
def test_unconfirmed_login_never_overwrites_saved_session(monkeypatch, tmp_path, changes):
    webui_path, env_path = _prepare_config(monkeypatch, tmp_path)
    quick_file = tmp_path / "quick.txt"
    quick_file.write_text("900000002\n", encoding="utf-8")
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", quick_file)
    paths = [quick_file, webui_path, env_path]
    before = [path.read_bytes() for path in paths]
    config = SimpleNamespace(account_system_enabled=True, accounts_db_path=tmp_path / "accounts.sqlite3")
    with pytest.raises(ValueError, match="尚未确认"):
        napcat_account.remember_login(config, {"status_known": True, "is_login": True, "uin": "900000001", **changes})
    assert [path.read_bytes() for path in paths] == before
    assert not config.accounts_db_path.exists()


def test_finish_switch_sets_quick_login_and_confirms_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    webui_path, env_path = _prepare_config(monkeypatch, tmp_path)
    quick_file = tmp_path / "napcat-quick-account.txt"
    quick_file.write_text("off\n", encoding="utf-8")
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", quick_file)
    monkeypatch.setattr(
        napcat_account,
        "napcat_login_state",
        lambda: {"ok": True, "is_login": True, "uin": "900000001", "nick": "新号"},
    )

    registered: list[tuple] = []
    confirmed: list[str] = []
    layouts: list[str] = []

    class FakeRegistry:
        def observe_from_napcat(self, *args, **kwargs):
            pass

        def get(self, account_id: str) -> None:
            return None

        def register(self, qq: str, **kwargs: object) -> SimpleNamespace:
            registered.append((qq, kwargs))
            return SimpleNamespace(account_id=f"qq:{qq}", qq=qq, confirmed=True)

        def mark_confirmed(self, account_id: str, *, enabled: bool = True) -> SimpleNamespace:
            confirmed.append(account_id)
            return SimpleNamespace(account_id=account_id, confirmed=True)

    monkeypatch.setattr(napcat_account, "registry_for_config", lambda config: FakeRegistry())
    monkeypatch.setattr(napcat_account, "account_id_for", lambda qq: f"qq:{qq}")
    monkeypatch.setattr(
        napcat_account, "ensure_account_layout", lambda config, account: layouts.append(account.account_id)
    )

    config = SimpleNamespace(account_system_enabled=True)
    result = napcat_account.finish_account_switch(config)

    assert quick_file.read_text(encoding="utf-8").strip() == "900000001"
    assert json.loads(webui_path.read_text(encoding="utf-8"))["autoLoginAccount"] == "900000001"
    assert "NAPCAT_QUICK_ACCOUNT=900000001" in env_path.read_text(encoding="utf-8")
    assert registered and registered[0][0] == "900000001"
    assert layouts == ["qq:900000001"]
    assert result["uin"] == "900000001"


def test_finish_switch_refuses_when_nothing_logged_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        napcat_account,
        "napcat_login_state",
        lambda: {"ok": True, "is_login": False, "uin": ""},
    )

    with pytest.raises(ValueError):
        napcat_account.finish_account_switch(SimpleNamespace(account_system_enabled=True))


def test_account_confirm_is_skipped_when_account_system_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", tmp_path / "quick.txt")
    monkeypatch.setattr(napcat_account, "webui_config_path", lambda: None)
    monkeypatch.setattr(
        napcat_account,
        "napcat_login_state",
        lambda: {"ok": True, "is_login": True, "uin": "900000002", "nick": "ATRI"},
    )

    result = napcat_account.finish_account_switch(SimpleNamespace(account_system_enabled=False))

    assert result["account"]["skipped"] == "账号系统未启用"


def test_cancel_switch_restores_default_quick_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    quick_file = tmp_path / "napcat-quick-account.txt"
    quick_file.write_text("off\n", encoding="utf-8")
    monkeypatch.setattr(napcat_account, "QUICK_ACCOUNT_FILE", quick_file)

    napcat_account.cancel_account_switch()

    assert not quick_file.exists()
