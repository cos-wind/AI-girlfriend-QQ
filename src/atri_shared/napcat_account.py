"""NapCat 登录账号切换：退出旧号 → 手动登录新号 → 其余由程序收尾。

用户要的体验是"像 QQ 一样退出登录，然后扫码或输账号密码换号"。NapCat 本身没有
独立的"退出登录"接口，而且这套项目启动时会把 ``BOT_QQ`` 作为快速登录账号传给
QQ（``-q <uin>`` 与 ``NAPCAT_QUICK_ACCOUNT``），所以用户登出后会被旧会话拉回去。
这个模块把整条链路包成一次动作：

* **退出前**：清掉自动登录（本项目覆盖文件写成"手动"、``webui.json`` 的
  ``autoLoginAccount`` 置空、NapCat ``config/.env`` 的 ``NAPCAT_QUICK_ACCOUNT``
  置空），否则重启后 QQ 又用旧会话登回原账号；
* **重启**：交给启动器的 ``napcat-restart`` 模式（复用隔离 profile、隐藏窗口、
  只结束自己安装目录下的进程，绝不动桌面 QQ）；
* **收尾**：确认新号已登录后，把快速登录改成新号（下次免扫码），并在 ATRI 账号
  系统里登记 + 确认，这样"跟随 NapCat 登录账号"这条路径才会真正切过去。

⚠️ 写 JSON 一律用 UTF-8 **不带 BOM**：PowerShell 的 ``Set-Content -Encoding utf8``
在 Windows PowerShell 5.1 下会写 BOM，NapCat 与 ATRI 的 ``json.loads`` 都会直接
读不出来（表现为面板显示"未配置"、NapCat 退回默认端口和随机 token）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from atri_qq_bot.accounts import account_id_for, ensure_account_layout, registry_for_config
from atri_qq_bot.runtime.observability import napcat_webui_access
from atri_qq_bot.runtime.paths import PROJECT_ROOT, TOOLS_DIR


LAUNCHER = TOOLS_DIR / "launch" / "qq_legacy" / "hidden_launcher.py"
# 与 tools/launch/qq_legacy/hidden_launcher.py 的 NAPCAT_QUICK_ACCOUNT_FILE 必须一致
# （tests/test_napcat_account.py 里有断言防止两边漂移）。
QUICK_ACCOUNT_FILE = PROJECT_ROOT / "data" / "runtime" / "napcat-quick-account.txt"
MANUAL_LOGIN = "off"
_HTTP_TIMEOUT_SECONDS = 12.0
_AUTH_LOCK = threading.Lock()
_CREDENTIALS: dict[tuple[str, str], tuple[str, float]] = {}
_AUTH_RETRY_AFTER: dict[tuple[str, str], float] = {}


def _credential(target: tuple[str, str], rejected: str = "") -> str:
    # NapCat credentials last an hour; polling must not consume its login quota.
    with _AUTH_LOCK:
        now = time.monotonic()
        cached = _CREDENTIALS.get(target)
        if cached and cached[1] > now and cached[0] != rejected:
            return cached[0]
        _CREDENTIALS.pop(target, None)
        if _AUTH_RETRY_AFTER.get(target, 0) > now:
            raise RuntimeError("NapCat 状态认证暂时限流，稍后将自动重试（QQ 登录不受影响）")
        base, token = target
        try:
            login = _post_json(f"{base}/api/auth/login", {
                "hash": hashlib.sha256(f"{token}.napcat".encode()).hexdigest(), "totpCode": ""})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"NapCat WebUI 不可达：{exc}") from exc
        if "rate limit" in str(login.get("message") or "").lower():
            _AUTH_RETRY_AFTER[target] = now + 60
            raise RuntimeError("NapCat 状态认证暂时限流，稍后将自动重试（QQ 登录不受影响）")
        data = login.get("data")
        credential = str(data.get("Credential") or "") if isinstance(data, dict) else ""
        if login.get("code") != 0 or not credential:
            raise RuntimeError("NapCat WebUI 拒绝登录（token 可能已变化）")
        if len(_CREDENTIALS) >= 8:
            _CREDENTIALS.clear()
        _CREDENTIALS[target] = (credential, now + 3000)
        # Only active cooldowns are useful, and no credentials go to disk.
        for key in list(_AUTH_RETRY_AFTER):
            if _AUTH_RETRY_AFTER[key] <= now:
                del _AUTH_RETRY_AFTER[key]
        return credential


# ---- NapCat WebUI 配置与调用 ------------------------------------------------


def webui_config_path() -> Path | None:
    access = napcat_webui_access()
    raw = str(access.get("config_path") or "").strip()
    return Path(raw) if raw else None


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8"
    )
    os.replace(temporary, path)


def _napcat_base() -> tuple[str, str] | None:
    """返回 ``(base_url, token)``；配置缺失时返回 ``None``。"""

    access = napcat_webui_access()
    config = _read_json(webui_config_path())
    token = str(config.get("token") or "").strip()
    host = str(access.get("host") or "127.0.0.1")
    local_host = "127.0.0.1" if host in {"::", "0.0.0.0", "localhost"} else host
    port = int(access.get("port") or 6099)
    if not token:
        return None
    return f"http://{local_host}:{port}", token


def _post_json(url: str, payload: dict[str, Any], token: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        payload_out = json.loads(response.read().decode("utf-8", errors="replace"))
    return payload_out if isinstance(payload_out, dict) else {}


def _napcat_call(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用 NapCat WebUI 的 ``/api`` 接口（先拿 Credential 再带 Bearer）。"""

    target = _napcat_base()
    if target is None:
        raise RuntimeError("找不到 NapCat WebUI 配置（webui.json 或 token 缺失）")
    base, _ = target
    credential = _credential(target)
    for attempt in range(2):
        try:
            result = _post_json(f"{base}/api{path}", payload or {}, credential)
            unauthorized = str(result.get("message") or "").lower() == "unauthorized"
            if not unauthorized:
                return result
        except HTTPError as exc:
            if exc.code not in {401, 403}:
                raise RuntimeError(f"NapCat 接口 {path} 调用失败：{exc}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"NapCat 接口 {path} 调用失败：{exc}") from exc
        if attempt == 0:
            credential = _credential(target, rejected=credential)
    with _AUTH_LOCK:
        cached = _CREDENTIALS.get(target)
        if cached and cached[0] == credential:
            _CREDENTIALS.pop(target, None)
            _AUTH_RETRY_AFTER[target] = time.monotonic() + 60
    raise RuntimeError("NapCat 状态认证已失效，请检查连接配置")


# ---- 快速登录覆盖文件 -------------------------------------------------------


def quick_account_override() -> str | None:
    try:
        raw = QUICK_ACCOUNT_FILE.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not raw:
        return None
    if raw.casefold() in {"off", "manual", "none", "-"}:
        return MANUAL_LOGIN
    return raw if raw.isdigit() else None


def set_quick_account_override(value: str | None) -> None:
    if value is None:
        QUICK_ACCOUNT_FILE.unlink(missing_ok=True)
        return
    QUICK_ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUICK_ACCOUNT_FILE.write_text(f"{value}\n", encoding="utf-8")


# ---- NapCat 自带配置里的自动登录/快速登录 -----------------------------------


def _set_webui_auto_login(uin: str) -> None:
    path = webui_config_path()
    if path is None:
        return
    config = _read_json(path)
    if not config:
        return
    config["autoLoginAccount"] = uin
    _write_json(path, config)


def _set_napcat_env_quick_account(uin: str) -> None:
    """改 NapCat ``config/.env`` 的 ``NAPCAT_QUICK_ACCOUNT``（保留其余内容）。"""

    path = webui_config_path()
    if path is None:
        return
    env_path = path.parent / ".env"
    lines: list[str] = []
    try:
        lines = env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        lines = []
    replaced = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("NAPCAT_QUICK_ACCOUNT="):
            output.append(f"NAPCAT_QUICK_ACCOUNT={uin}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"NAPCAT_QUICK_ACCOUNT={uin}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


# ---- 状态 -------------------------------------------------------------------


def _int_or_empty(value: Any) -> str:
    text = str(value or "").strip()
    return text if text.isdigit() else ""


def napcat_login_state(*, lightweight: bool = False) -> dict[str, Any]:
    """NapCat 登录状态 + 本项目的自动登录设置（面板据此渲染）。"""

    access = napcat_webui_access()
    webui_path = webui_config_path()
    config = _read_json(webui_path)
    override = quick_account_override()
    state: dict[str, Any] = {
        "ok": True,
        "configured": bool(access.get("configured")),
        "reachable": bool(access.get("reachable")),
        "webui_url": str(access.get("url") or ""),
        "config_path": str(webui_path or ""),
        "token_configured": bool(config.get("token")),
        "auto_login_account": _int_or_empty(config.get("autoLoginAccount")),
        "quick_account_override": override or "",
        "manual_login_pending": override == MANUAL_LOGIN,
        "is_login": False,
        "status_known": False,
        "qr_login_accepted": False,
        "core_ready": False,
        "is_offline": False,
        "online": False,
        "uin": "",
        "nick": "",
        "phase": "",
        "login_error": "",
        "qrcode_url": "",
        "quick_login_account": "",
        "auto_finish_ready": False,
        "error": "",
    }
    if not state["reachable"]:
        state["error"] = "NapCat WebUI 未监听（NapCat 可能没在运行）"
        return state
    try:
        response = _napcat_call("/QQLogin/CheckLoginStatus")
        status = response.get("data")
        if response.get("code", 0) != 0 or not isinstance(status, dict) or not isinstance(status.get("isLogin"), bool):
            raise RuntimeError("NapCat 登录状态暂不可用，正在重试")
    except RuntimeError as exc:
        state["error"] = str(exc)
        return state
    state.update(
        {
            "is_login": bool(status.get("isLogin")),
            "status_known": True,
            "qr_login_accepted": bool(status.get("qrLoginAccepted")),
            "core_ready": bool(status.get("coreReady")),
            "is_offline": bool(status.get("isOffline")),
            "online": bool(status.get("isLogin")),
            "phase": str(status.get("loginPhase") or ""),
            "login_error": str(status.get("loginError") or ""),
            "qrcode_url": str(status.get("qrcodeurl") or ""),
        }
    )
    if not lightweight or state["is_login"] or state["qr_login_accepted"]:
        try:
            response = _napcat_call("/QQLogin/GetQQLoginInfo")
            info = response.get("data")
            if response.get("code", 0) == 0 and isinstance(info, dict):
                state.update(uin=_int_or_empty(info.get("uin")), nick=str(info.get("nick") or ""))
        except RuntimeError:
            pass  # Optional account details cannot undo an authoritative login.
    if not lightweight:
        try:
            quick = _napcat_call("/QQLogin/GetQuickLoginQQ").get("data")
            state["quick_login_account"] = _int_or_empty(quick if isinstance(quick, str) else "")
        except RuntimeError:
            pass
    # 处于"要求手动登录"且已经有账号登进来 → 可以自动收尾（改成快速登录 + 确认账号）。
    state["auto_finish_ready"] = bool(
        state["manual_login_pending"] and state["is_login"] and state["uin"]
    )
    return state


# ---- 两个动作 ---------------------------------------------------------------


def login_history(config: Any) -> list[dict[str, Any]]:
    """Read previously logged-in identities from the existing account registry."""
    path = getattr(config, "accounts_db_path", None)
    if not getattr(config, "account_system_enabled", False) or not path or not Path(path).is_file():
        return []
    accounts = registry_for_config(config).list_all()
    keys = {"account_id", "qq", "display_name", "enabled", "confirmed", "last_login_at"}
    return [{key: value for key, value in row.public_dict().items() if key in keys}
            for row in sorted(accounts, key=lambda row: row.last_login_at or 0, reverse=True)
            if row.last_login_at is not None]


def remember_login(config: Any, state: dict[str, Any]) -> None:
    """Keep a confirmed NapCat session even if AI setup has not finished yet."""
    uin = _int_or_empty(state.get("uin"))
    if state.get("status_known") is False or not state.get("is_login") or not uin:
        raise ValueError("NapCat 登录尚未确认，无法保存账号")
    if quick_account_override() != uin:
        set_quick_account_override(uin)
        _set_webui_auto_login(uin)
        _set_napcat_env_quick_account(uin)
    if getattr(config, "account_system_enabled", False):
        registry_for_config(config).observe_from_napcat(uin, display_name=str(state.get("nick") or ""))


def _launcher_command(mode: str) -> list[str] | None:
    pass
    if not LAUNCHER.is_file():
        return None
    candidates = (
        PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
    )
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        return None
    return [str(executable), str(LAUNCHER), mode]


def _spawn_launcher(mode: str) -> None:
    command = _launcher_command(mode)
    if command is None:
        raise RuntimeError(f"找不到隐藏启动器：{LAUNCHER}")
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


def begin_account_switch() -> dict[str, Any]:
    """退出当前账号并准备手动登录：清自动登录 → 重启 NapCat。"""

    before = napcat_login_state()
    set_quick_account_override(MANUAL_LOGIN)
    _set_webui_auto_login("")
    _set_napcat_env_quick_account("")
    _spawn_launcher("napcat-restart")
    return {
        "ok": True,
        "action": "logout",
        "previous_uin": before.get("uin", ""),
        "previous_nick": before.get("nick", ""),
        "webui_url": before.get("webui_url", ""),
        "message": (
            "已清除自动登录并重启 NapCat；请在打开的 NapCat 页面用新账号的手机 QQ "
            "扫码，或在该页面选择账号密码 / 验证码登录。"
        ),
    }


def _confirm_account(config: Any, uin: str) -> dict[str, Any]:
    """在 ATRI 账号系统里登记并确认这个号（账号系统没启用就跳过）。"""

    if not bool(getattr(config, "account_system_enabled", False)):
        return {"account_id": "", "skipped": "账号系统未启用"}
    registry = registry_for_config(config)
    account_id = account_id_for(uin)
    account = registry.get(account_id)
    created = False
    if account is None:
        account = registry.register(
            uin,
            display_name=f"QQ {uin}",
            is_default=False,
            enabled=True,
            confirmed=True,
            notes="切换 NapCat 账号时由 WebUI 自动登记",
        )
        created = True
    elif not account.confirmed:
        account = registry.mark_confirmed(account_id, enabled=True)
    if account is not None:
        ensure_account_layout(config, account)
    return {
        "account_id": account_id,
        "created": created,
        "confirmed": bool(account is not None and account.confirmed),
    }


def finish_account_switch(config: Any) -> dict[str, Any]:
    """新号已登录后收尾：设快速登录 + 在 ATRI 侧确认该账号。"""

    state = napcat_login_state()
    if not state.get("is_login") or not state.get("uin"):
        raise ValueError("NapCat 还没有登录任何账号，请先在 NapCat 页面扫码/登录")
    uin = str(state["uin"])
    remember_login(config, state)
    account = _confirm_account(config, uin)
    nick = str(state.get("nick") or "")
    return {
        "ok": True,
        "action": "finish",
        "uin": uin,
        "nick": nick,
        "account": account,
        "message": (
            f"已切到 {nick or '新账号'}（QQ {uin}）：快速登录已设为该号，"
            "ATRI 会在下一次探测时跟随它。"
        ),
    }


def cancel_account_switch() -> dict[str, Any]:
    """放弃切换：恢复"按 BOT_QQ 快速登录"的历史行为。"""

    set_quick_account_override(None)
    return {
        "ok": True,
        "action": "cancel",
        "message": "已取消切换准备，恢复为按 BOT_QQ 自动登录。",
    }


__all__ = [
    "MANUAL_LOGIN",
    "QUICK_ACCOUNT_FILE",
    "begin_account_switch",
    "cancel_account_switch",
    "finish_account_switch",
    "napcat_login_state",
    "login_history",
    "remember_login",
    "quick_account_override",
    "set_quick_account_override",
]
