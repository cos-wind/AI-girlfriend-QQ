"""Explicit entry for an existing MaiBot installation, independent of ATRI routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
from threading import Lock
import time
import tomllib
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import webbrowser

from dotenv import dotenv_values
from atrium_runtime import resource_root


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _dashboard_ready(url: str) -> bool:
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(
                url + 'api/webui/health', timeout=1) as response:
            data = json.loads(response.read(8192))
            return data.get('status') == 'healthy' and data.get('service') == 'MaiBot WebUI'
    except (OSError, ValueError, AttributeError):
        return False


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


class MaiBotLauncher:
    """Construction and snapshots are inert; open() reuses the installed launcher."""

    def __init__(self, *, root: Path | None = None, source: Path | None = None, timeout: float = 40):
        self._root = root
        self._source = source
        self._timeout = timeout
        self._lock = Lock()
        self._process = None

    def _installation(self) -> Path:
        if self._source is not None:
            candidates = [self._source]
        else:
            root = self._root if self._root is not None else resource_root()
            configured = dotenv_values(root / '.env').get('MAIBOT_ROOT') or os.environ.get('MAIBOT_ROOT', '')
            candidates = [Path(configured)] if configured else [
                root.parent / 'QQ_Backends/MaiBot', Path(r'D:\MaiBot-install'), root.parent / 'MaiBot-install']
        for source in candidates:
            if (source / 'bot.py').is_file():
                return source
        raise ValueError('未找到 MaiBot，请检查 QQ_Backends/MaiBot 或旧 MaiBot-install，或设置 MAIBOT_ROOT。')

    def _panel(self):
        source = self._installation()
        config = source / 'config/bot_config.toml'
        if not config.is_file():
            raise ValueError('MaiBot 配置不存在，请先完成 MaiBot 初始配置。')
        panel = tomllib.loads(config.read_text(encoding='utf-8-sig')).get('webui', {})
        if not panel.get('enabled', True):
            raise ValueError('MaiBot 管理面板已禁用，请先在 MaiBot 配置中启用。')
        hosts = panel.get('host', ['127.0.0.1', '::1'])
        hosts = [hosts] if isinstance(hosts, str) else hosts
        if not any(host in hosts for host in ('127.0.0.1', '0.0.0.0', 'localhost')):
            raise ValueError('MaiBot 未监听本机 IPv4 地址，请使用原管理入口。')
        port = int(panel.get('port', 8001))
        if not 1 <= port <= 65535:
            raise ValueError('MaiBot 管理端口无效，请检查配置。')
        return source, port, f'http://127.0.0.1:{port}/'

    def snapshot(self) -> dict:
        _, port, url = self._panel()
        ready = _dashboard_ready(url)
        starting = self._lock.locked() or (self._process is not None and self._process.poll() is None)
        return {'phase': 'ready' if ready else 'starting' if starting else
                'conflict' if _port_open(port) else 'stopped', 'port': port}

    def open_log(self) -> dict:
        log = self._installation() / 'logs/startup.log'
        if not log.is_file():
            raise ValueError('还没有 MaiBot 启动日志，请先打开 MaiBot。')
        os.startfile(str(log))
        return {'ok': True, 'message': '已打开 MaiBot 启动日志。'}

    def open(self) -> dict:
        return self.start(open_panel=True)

    def start(self, *, open_panel=False) -> dict:
        if not self._lock.acquire(blocking=False):
            raise ValueError('MaiBot 正在启动，请稍候。')
        try:
            return self._open(open_panel=open_panel)
        finally:
            self._lock.release()

    def stop(self) -> dict:
        from .service_process import stop_entry
        if not self._lock.acquire(blocking=False):
            raise ValueError('MaiBot 正在操作，请稍候。')
        try:
            source, port, url = self._panel()
            stop_entry(source / 'bot.py', port=port, process=self._process,
                       wrapper=source / 'start_maibot.ps1')
            if _dashboard_ready(url):
                raise ValueError('MaiBot 尚未关闭，请刷新后重试。')
            self._process = None
            return {'ok': True, 'message': 'MaiBot 已关闭。'}
        finally:
            self._lock.release()

    def _open(self, *, open_panel=True) -> dict:
        source, port, url = self._panel()
        if not _dashboard_ready(url):
            running = self._process is not None and self._process.poll() is None
            if not running:
                if _port_open(port):
                    raise ValueError(f'{port} 端口已占用，尚未确认是 MaiBot 面板，请检查后重试。')
                script = source / 'start_maibot.ps1'
                if not script.is_file() or not (source / '.venv/Scripts/python.exe').is_file():
                    raise ValueError('MaiBot 启动脚本或独立 Python 环境缺失，请检查安装。')
                env = os.environ.copy()
                for name in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
                    env.pop(name, None)
                # The installed script owns its startup mutex and logs. Do not
                # bypass it or spawn another bot.py while legacy startup is busy.
                self._process = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                     'Bypass', '-File', str(script)], cwd=str(source), env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + self._timeout
            while not _dashboard_ready(url):
                code = self._process.poll()
                if code is not None and code != 0:
                    raise ValueError('MaiBot 启动失败，请打开“启动日志”查看原因。')
                # Exit 0 can mean the installed startup mutex is already held
                # by another entry; wait for its health instead of duplicating it.
                if time.monotonic() >= deadline:
                    raise ValueError('MaiBot 仍在启动，可稍后再次点击；详情见“启动日志”。')
                time.sleep(0.3)
        if open_panel and not webbrowser.open(url):
            raise ValueError(f'MaiBot 已就绪，浏览器未打开，请访问 {url}')
        return {'ok': True, 'message': '已打开 MaiBot 管理面板；登录令牌见启动日志。' if open_panel else 'MaiBot 已启动。', 'data': {'url': url}}
