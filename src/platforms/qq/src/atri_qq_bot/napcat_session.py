"""Prepare a QR login without disturbing the active dedicated QQ session.

Only the candidate's PID, profile and NapCat work directory are persisted.
The active session is retired after the new core has started successfully.
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
from pathlib import Path
import secrets
import socket
import webbrowser
from functools import lru_cache

from atri_shared import config_admin
from atri_shared.runtime.paths import PROJECT_ROOT
from . import napcat_account as login
from .runtime.observability import napcat_webui_access


@lru_cache(maxsize=1)
def launcher():
    spec = importlib.util.spec_from_file_location("atri_qq_session_launcher", login.LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def process_stamp(pid):
    """Creation time guards against terminating a reused Windows PID."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return ""
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            return ""
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


class LoginSession:
    def __init__(self, root=None):
        self.root = Path(root or PROJECT_ROOT / "data" / "runtime" / "qq-login")
        self.path = self.root / "pending.json"

    @property
    def pending(self):
        return login._read_json(self.path)

    def _alive(self, row):
        return bool(row.get("stamp") and process_stamp(row["pid"]) == row["stamp"])

    def begin(self):
        pending = self.pending
        if pending and self._alive(pending):
            return {"ok": True, "message": "新账号登录页已就绪，原账号继续使用。"}
        module = launcher()
        required = module.required_napcat_files()
        if not required:
            raise ValueError("NapCat 组件不完整，请修复后重试。")
        boot, hook, main, load, patch = required
        saved = config_admin.read_env()
        active = str(saved.get("NAPCAT_WORKDIR") or "")
        # Two persistent slots bound disk usage and retain QQ login data.
        work = next(self.root / name for name in ("a", "b")
                    if str((self.root / name).resolve()).casefold() != str(Path(active).resolve()).casefold())
        profile = work / "qq-profile"
        directory = work / "config"
        directory.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        login._write_json(directory / "webui.json", {
            "host": "127.0.0.1", "port": port, "token": secrets.token_urlsafe(32),
            "autoLoginAccount": "", "disableWebUI": False,
        })
        (directory / ".env").write_text("NAPCAT_QUICK_ACCOUNT=\n", encoding="utf-8")
        # A scanned candidate cannot connect to any bot before promotion.
        for path in {directory / "onebot11.json", *directory.glob("onebot11_*.json")}:
            login._write_json(path, {"network": {"websocketClients": [], "websocketServers": [], "httpServers": [], "httpClients": []}})
        uri = main.resolve().as_uri()
        load.write_text(f'(async () => {{await import("{uri}")}})()\n', encoding="utf-8")
        env = os.environ.copy()
        env.update(NAPCAT_WORKDIR=str(work), NAPCAT_QUICK_ACCOUNT="",
                   NAPCAT_PATCH_PACKAGE=str(patch), NAPCAT_LOAD_PATH=str(load),
                   NAPCAT_INJECT_PATH=str(hook), NAPCAT_LAUNCHER_PATH=str(boot), NAPCAT_MAIN_PATH=str(main))
        # Record only this project's QQ roots, never the user's desktop QQ.
        old = []
        pids = set(module.project_qq_pids())
        for row in module.process_rows():
            pid = int(row["pid"])
            parent = int(row.get("parent_pid") or row.get("ppid") or 0)
            if pid in pids and parent not in pids:
                stamp = process_stamp(pid)
                if stamp:
                    old.append({"pid": pid, "stamp": stamp})
        pid = module.launch_napcat_boot_process(launcher=boot, hook=hook, qq_exe=module.qq_executable(),
            qq_uin="", profile_dir=profile, cwd=boot.parent, env=env)
        pending = {"pid": pid, "stamp": process_stamp(pid), "workdir": str(work),
                   "profile": str(profile), "previous": old}
        login._write_json(self.path, pending)
        return {"ok": True, "message": "正在准备新账号二维码；扫码确认前保留原账号。"}

    def access(self):
        pending = self.pending
        if not pending:
            raise ValueError("没有待确认的登录。")
        return napcat_webui_access(Path(pending["workdir"]) / "config" / "webui.json")

    def _napcat_call(self, path, payload=None):
        access = self.access()
        config = login._read_json(Path(access["config_path"]))
        return login._napcat_call(path, payload, target=(f'http://127.0.0.1:{access["port"]}', config["token"]))

    def napcat_login_state(self, *, lightweight=True):
        return login.napcat_login_state(lightweight=lightweight, access=self.access(), call=self._napcat_call)

    def open(self):
        access = self.access()
        if not access.get("reachable"):
            raise ValueError("登录页正在准备，请稍候。")
        if not webbrowser.open(access["url"]):
            raise ValueError("无法打开系统浏览器。")
        return {"ok": True, "message": "已打开新账号的 NapCat 登录页。"}

    def activate(self, writer):
        pending = self.pending
        if not pending or not self._alive(pending):
            raise ValueError("新账号登录进程已退出，请重新获取二维码。")
        writer({"NAPCAT_WORKDIR": pending["workdir"], "QQ_PROFILE_DIR": pending["profile"]})

    def disconnect(self):
        """Prevent a failed candidate from joining the restored core."""
        result = self._napcat_call("/OB11Config/GetConfig")
        config = result.get("data")
        if result.get("code") != 0 or not isinstance(config, dict):
            # Stopping only the candidate is the safe fallback on API failure.
            self.cancel()
            return
        for row in config.get("network", {}).get("websocketClients", []):
            if row.get("name") == "atri-qq-bot":
                row["enable"] = False
        import json
        result = self._napcat_call("/OB11Config/SetConfig", {"config": json.dumps(config, ensure_ascii=False)})
        if result.get("code") != 0:
            self.cancel()

    def _stop(self, row):
        if self._alive(row):
            launcher().taskkill_process_tree(int(row["pid"]))

    def cancel(self):
        pending = self.pending
        if pending:
            self._stop(pending)
            self.path.unlink(missing_ok=True)
        return {"ok": True, "message": "已取消切换，原账号保留。"}

    def finish(self):
        pending = self.pending
        if pending:
            for row in pending.get("previous", []):
                self._stop(row)
            self.path.unlink(missing_ok=True)
