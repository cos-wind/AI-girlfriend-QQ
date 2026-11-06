"""Explicit SnowLuma panel launcher; never starts or attaches to QQ itself."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
from threading import Lock
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import webbrowser

from atrium_runtime import user_root


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _dashboard_ready(url: str) -> bool:
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(url, timeout=1) as response:
            return b'<title>SnowLuma ' in response.read()
    except (OSError, ValueError):
        return False


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


class SnowLumaLauncher:
    """Construction is inert. Only an explicit open starts the independent host."""

    def __init__(self, *, root: Path | None = None, timeout: float = 25):
        self._root = root
        self._timeout = timeout
        self._lock = Lock()
        self._process = None

    def _paths(self) -> tuple[Path, Path]:
        root = self._root if self._root is not None else user_root()
        return root / 'data/runtime/snowluma', root / 'data/runtime/snowluma-startup.log'

    def open_log(self) -> dict:
        _, log = self._paths()
        if not log.is_file():
            raise ValueError('还没有启动日志，请先打开 SnowLuma。')
        os.startfile(str(log))
        return {'ok': True, 'message': '已打开启动日志；首次登录密码见最新一次启动记录。'}

    def open(self) -> dict:
        return self.start(open_panel=True)

    def start(self, *, open_panel=False) -> dict:
        """Explicit service startup can be composed without opening a browser."""
        if not self._lock.acquire(blocking=False):
            raise ValueError('SnowLuma 正在启动，请稍候。')
        try:
            return self._open(open_panel=open_panel)
        finally:
            self._lock.release()

    def stop(self) -> dict:
        from .service_process import stop_entry
        if not self._lock.acquire(blocking=False):
            raise ValueError('SnowLuma 正在操作，请稍候。')
        try:
            source, _, port, url = self._panel()
            stop_entry(source / 'index.mjs', port=port, process=self._process)
            if _dashboard_ready(url):
                raise ValueError('SnowLuma 尚未关闭，请刷新后重试。')
            self._process = None
            return {'ok': True, 'message': 'SnowLuma 管理服务已关闭；已加载 QQ 中的连接需在后端卸载。'}
        finally:
            self._lock.release()

    def _panel(self):
        source, log = self._paths()
        if not (source / 'index.mjs').is_file() or not (source / 'node.exe').is_file():
            raise ValueError(f'未找到 SnowLuma 完整安装，请检查 {source}。')
        config_file = source / 'config/runtime.json'
        config = json.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {}
        if config.get('webuiTls', {}).get('enabled', False):
            raise ValueError('此快捷入口支持本机 HTTP 面板；当前 SnowLuma 已启用 HTTPS，请使用原启动方式。')
        port = int(config.get('webuiPort', 5099))
        if not 1 <= port <= 65535:
            raise ValueError('SnowLuma 管理端口无效，请检查配置。')
        url = f'http://127.0.0.1:{port}/'
        return source, log, port, url

    def snapshot(self) -> dict:
        source, log, port, url = self._panel()
        ready = _dashboard_ready(url)
        starting = self._lock.locked() or (self._process is not None and self._process.poll() is None)
        return {'phase': 'ready' if ready else 'starting' if starting else
                'conflict' if _port_open(port) else 'stopped', 'port': port}

    def _open(self, *, open_panel=True) -> dict:
        source, log, port, url = self._panel()
        if not _dashboard_ready(url):
            running = self._process is not None and self._process.poll() is None
            if not running:
                if _port_open(port):
                    raise ValueError(f'{port} 端口已占用，尚未确认是 SnowLuma 面板，请检查后重试。')
                env = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith('SNOWLUMA_') and key.upper() not in {'NODE_OPTIONS', 'NODE_PATH'}}
                # Never globally attach discovered QQs. Explicit connection uses
                # the native helper targeting only our dedicated executable.
                env.update(SNOWLUMA_HOOK_AUTOLOAD='0', SNOWLUMA_WEBUI_HOST='127.0.0.1',
                           SNOWLUMA_WEBUI_PORT=str(port))
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open('ab') as output:
                    output.write(f'\n--- SnowLuma {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n'.encode())
                    output.flush()
                    self._process = subprocess.Popen(
                        [str(source / 'node.exe'), str(source / 'index.mjs')],
                        cwd=str(source), env=env, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + self._timeout
            while not _dashboard_ready(url):
                if self._process.poll() is not None:
                    raise ValueError('SnowLuma 启动失败，请打开“启动日志”查看原因。')
                if time.monotonic() >= deadline:
                    raise ValueError('SnowLuma 仍在启动，可稍后再次点击；详情见“启动日志”。')
                time.sleep(0.3)
        if open_panel and not webbrowser.open(url):
            raise ValueError(f'SnowLuma 已就绪，浏览器未打开，请访问 {url}')
        return {'ok': True, 'message': '面板已打开；请使用面板密码登录，登录说明见 SnowLuma + DSH 日志顶部。' if open_panel else 'SnowLuma 服务已就绪。', 'data': {'url': url}}
