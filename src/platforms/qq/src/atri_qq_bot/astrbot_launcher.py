"""Explicit standalone AstrBot launcher; independent of QQ sessions and routing."""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import subprocess
import tempfile
from threading import Lock
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import webbrowser

from atrium_runtime import resource_root, user_root


def astrbot_temp_environment(runtime: Path, *, root: Path | None = None) -> dict[str, str]:
    """Give pip a writable, instance-scoped temp home, independent of its cwd.

    Windows' system TEMP can reject the independent interpreter. Keep temporary
    installs in the workspace cache without changing the caller or global ACLs.
    """
    identity = os.path.normcase(str(runtime.resolve()))
    key = sha256(identity.encode('utf-8')).hexdigest()[:16]
    cache = (root if root is not None else user_root()) / 'dev/workspace/cache/astrbot-temp' / key
    cache.mkdir(parents=True, exist_ok=True)
    # Fail before spawning a partial service if the cache itself is unwritable.
    with tempfile.TemporaryFile(dir=cache):
        pass
    return {name: str(cache) for name in ('TEMP', 'TMP', 'TMPDIR')}


def astrbot_source(root: Path) -> Path:
    """Prefer the unified installation; keep old checkouts usable."""
    source = root.parent / 'QQ_Backends' / 'AstrBot'
    legacy = root.parent / 'AstrBot'
    if not (source / 'main.py').is_file() and (legacy / 'main.py').is_file():
        return legacy
    return source


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _dashboard_ready(url: str) -> bool:
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(url, timeout=1) as response:
            # Drain the HTML response before closing: early disconnects cause
            # Hypercorn to report a truncated Content-Length on large pages.
            return b'AstrBot Dashboard' in response.read()
    except (OSError, ValueError):
        return False


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


def _prepare_runtime(source: Path, runtime: Path) -> None:
    """Import saved data once into a writable home, including committed WAL data."""
    if runtime.exists():
        return
    runtime.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete import; a failed copy must remain retryable.
    with tempfile.TemporaryDirectory(prefix='astrbot-import-', dir=runtime.parent) as folder:
        staged = Path(folder) / 'astrbot'
        data = source / 'data'
        if data.is_dir():
            shutil.copytree(data, staged / 'data', copy_function=shutil.copyfile,
                            ignore=lambda path, names: [name for name in names
                                if Path(path) == data and name in
                                {'data_v4.db', 'data_v4.db-wal', 'data_v4.db-shm'}])
            database = data / 'data_v4.db'
            if database.is_file():
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as original:
                    with closing(sqlite3.connect(staged / 'data' / database.name)) as imported:
                        original.backup(imported)
        else:
            (staged / 'data').mkdir(parents=True)
        staged.replace(runtime)


class AstrBotLauncher:
    """Construction is inert. Only open() checks or starts the standalone host."""

    def __init__(self, *, root: Path | None = None, timeout: float = 40):
        self._root = root
        self._timeout = timeout
        self._lock = Lock()
        self._process = None

    def _log_path(self) -> Path:
        root = self._root if self._root is not None else resource_root()
        return root / 'dev/workspace/logs/astrbot-standalone.log'

    def open_log(self) -> dict:
        log = self._log_path()
        if not log.is_file():
            raise ValueError('还没有 AstrBot 启动日志，请先打开 AstrBot。')
        os.startfile(str(log))
        return {'ok': True, 'message': '已打开 AstrBot 启动日志。'}

    def open(self) -> dict:
        return self.start(open_panel=True)

    def start(self, *, open_panel=False) -> dict:
        if not self._lock.acquire(blocking=False):
            raise ValueError('AstrBot 正在启动，请稍候。')
        try:
            return self._open(open_panel=open_panel)
        finally:
            self._lock.release()

    def stop(self) -> dict:
        from .service_process import stop_entry
        if not self._lock.acquire(blocking=False):
            raise ValueError('AstrBot 正在操作，请稍候。')
        try:
            _, source, _, port, url = self._panel()
            stop_entry(source / 'main.py', port=port, process=self._process, standalone=True)
            if _dashboard_ready(url):
                raise ValueError('独立 AstrBot 尚未关闭，请刷新后重试。')
            self._process = None
            return {'ok': True, 'message': '独立 AstrBot 已关闭。'}
        finally:
            self._lock.release()

    def _panel(self):
        root = self._root if self._root is not None else resource_root()
        source = astrbot_source(root)
        runtime = (self._root if self._root is not None else user_root()) / 'data/runtime/astrbot'
        if not (source / 'main.py').is_file():
            raise ValueError(f'未找到 AstrBot：请将它放在 {source}。')
        config_file = (runtime if runtime.exists() else source) / 'data' / 'cmd_config.json'
        config = json.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {}
        dashboard = config.get('dashboard', {})
        if not dashboard.get('enable', True):
            raise ValueError('AstrBot 管理面板已禁用，请先在 AstrBot 配置中启用。')
        if dashboard.get('ssl', {}).get('enable', False):
            raise ValueError('当前快捷入口支持本机 HTTP 面板；此 AstrBot 配置启用了 HTTPS，请使用原启动方式。')
        port = int(dashboard.get('port', 6185))
        if not 1 <= port <= 65535:
            raise ValueError('AstrBot 管理端口无效，请检查 AstrBot 配置。')
        url = f'http://127.0.0.1:{port}/'
        return root, source, runtime, port, url

    def snapshot(self) -> dict:
        root, source, runtime, port, url = self._panel()
        ready = _dashboard_ready(url)
        starting = self._lock.locked() or (self._process is not None and self._process.poll() is None)
        return {'phase': 'ready' if ready else 'starting' if starting else
                'conflict' if _port_open(port) else 'stopped', 'port': port}

    def _open(self, *, open_panel=True) -> dict:
        root, source, runtime, port, url = self._panel()
        log = self._log_path()
        if not _dashboard_ready(url):
            running = self._process is not None and self._process.poll() is None
            if not running:
                if _port_open(port):
                    raise ValueError(f'{port} 端口已占用，尚未确认是 AstrBot 管理面板，请检查后重试。')
                candidates = [source / '.venv' / 'Scripts' / 'python.exe',
                              root / 'dev' / 'workspace' / 'qq-trial' / '.venv' / 'Scripts' / 'python.exe']
                python = next((path for path in candidates if path.is_file()), None)
                if python is None:
                    raise ValueError('未找到 AstrBot 的独立 Python 环境，请先安装 AstrBot 依赖。')
                _prepare_runtime(source, runtime)
                env = os.environ.copy()
                for name in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
                    env.pop(name, None)
                env.update(astrbot_temp_environment(runtime, root=self._root))
                env.update(ASTRBOT_ROOT=str(runtime), PYTHONUNBUFFERED='1',
                           PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
                           DASHBOARD_HOST='127.0.0.1', DASHBOARD_PORT=str(port),
                           DASHBOARD_SSL_ENABLE='false')
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open('ab') as output:
                    self._process = subprocess.Popen(
                        [str(python), str(source / 'main.py')], cwd=str(source), env=env,
                        stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + self._timeout
            while not _dashboard_ready(url):
                if self._process.poll() is not None:
                    raise ValueError(f'AstrBot 启动失败，请查看日志：{log}')
                if time.monotonic() >= deadline:
                    raise ValueError(f'AstrBot 仍在启动，可稍后再次点击；日志：{log}')
                time.sleep(0.5)
        if open_panel and not webbrowser.open(url):
            raise ValueError(f'AstrBot 已就绪，浏览器未打开，请手动访问 {url}')
        return {'ok': True, 'message': '已打开 AstrBot 管理面板' if open_panel else '独立 AstrBot 已启动。', 'data': {'url': url}}
