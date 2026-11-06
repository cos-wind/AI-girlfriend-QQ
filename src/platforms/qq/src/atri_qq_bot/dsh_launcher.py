"""Explicit DSH QQ lifecycle, isolated from the NapCat account."""
import json
from pathlib import Path
import subprocess
from threading import Lock
from urllib.request import Request, ProxyHandler, build_opener
from urllib.parse import urlencode
import webbrowser
import time

from atrium_runtime import resource_root


class DSHLauncher:
    def __init__(self, root=None, *, runner=None, request=None, opener=None):
        self.root = Path(root) if root else resource_root()
        self.backend = self.root.parent / 'QQ_Backends/DSH-QQ'
        self._run = runner or subprocess.run
        self._request = request or self._http
        self._open = opener or webbrowser.open
        self._lock = Lock()
        self._stage = ''
        self._since = 0

    @staticmethod
    def _http(url, token):
        req = Request(url, headers={'Authorization': 'Bearer ' + token,
                                    'x-console-token': token})
        with build_opener(ProxyHandler({})).open(req, timeout=1.5) as response:
            return json.loads(response.read(512_000))

    def snapshot(self):
        result = {'phase': 'stopped', 'port': 6310, 'online': False,
                  'dsh_ready': False, 'bridge_ready': False}
        from .dsh_qq import target_account
        try:
            expected = target_account(self.root)
        except ValueError as error:
            expected = ''
            result['account_error'] = str(error)
        if self._stage:
            result['progress'] = {'stage': self._stage, 'elapsed': int(time.monotonic() - self._since)}
        try:
            config = json.loads((self.backend / 'config.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {**result, 'phase': 'unknown'}
        try:
            status = self._request('http://127.0.0.1:6310/api/status', config.get('consoleToken', ''))
            # Never expose activity, roles or credentials through status polling.
            if status.get('mode') in {'chat', 'reserved', 'reserved2', 'closed-agent'}:
                result.update(bridge_ready=True, dsh_ready=status.get('dshReady') is True)
                result['phase'] = 'ready' if result['dsh_ready'] else 'starting'
        except (OSError, ValueError):
            pass
        try:
            if config.get('snowluma', {}).get('httpUrl') != 'http://127.0.0.1:6300':
                return result
            login = self._request('http://127.0.0.1:6300/get_login_info', config['snowluma'].get('accessToken', ''))
            if login.get('status') == 'ok' and login.get('data', {}).get('user_id'):
                actual = str(login['data']['user_id'])
                if expected and actual == expected:
                    status = self._request('http://127.0.0.1:6300/get_status', config['snowluma'].get('accessToken', ''))
                    if (status.get('status') == 'ok' and status.get('data', {}).get('online') is True
                            and status['data'].get('good') is not False):
                        result.update(online=True, account=actual)
                else:
                    result['account_error'] = 'SnowLuma 在线账号与 DSH 绑定账号不符，已阻止启动；未操作该 QQ。'
        except (OSError, ValueError):
            pass
        return result

    def start(self):
        return self._action('start')

    def stop(self):
        return self._action('stop')

    def _action(self, action):
        if not self._lock.acquire(blocking=False):
            return {'ok': False, 'error': 'DSH QQ 正在启停，请稍候。'}
        try:
            if action == 'start':
                current = self.snapshot()
                if current.get('account_error'):
                    return {'ok': False, 'error': current['account_error']}
            self._since = time.monotonic()
            self._stage = 'core' if action == 'start' else 'stopping'
            script = self.root / 'dev/tools/launch/qq_legacy/dsh-qq.ps1'
            if not script.is_file():
                return {'ok': False, 'error': 'DSH QQ 启动脚本不存在。'}
            try:
                outcome = self._run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                     '-File', str(script), '-Action', action],
                                    # Spawned Node daemons can inherit captured pipe handles:
                                    # communicate() then waits for their exit after PowerShell
                                    # has finished. The script redirects service logs to files.
                                    cwd=str(self.root), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=390,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired):
                return {'ok': False, 'error': '启停尚未确认，请刷新状态；QQ 登录保留。'}
            if outcome.returncode:
                return {'ok': False, 'error': 'DSH QQ 启停未完成，请刷新状态并查看本地启动日志。'}
            data = self.snapshot()
            if action == 'stop':
                return {'ok': not data['bridge_ready'], 'data': data,
                        'message': 'DSH QQ 已停止，QQ 登录与 NapCat 原账号保留。',
                        **({'error': '桥接仍在运行，请刷新并重试停止。'} if data['bridge_ready'] else {})}
            # The bridge opens its console before the first authenticated DSH
            # handshake completes. Observe that handshake instead of treating
            # an open console as either full readiness or an immediate failure.
            until = time.monotonic() + 8
            while (data['bridge_ready'] and not data['dsh_ready']
                   and not data.get('account_error') and time.monotonic() < until):
                time.sleep(0.2)
                data = self.snapshot()
            if data.get('account_error'):
                return {'ok': False, 'error': data['account_error'], 'data': data}
            if not data['bridge_ready'] or not data['dsh_ready']:
                return {'ok': False, 'data': data, 'error': 'DSH 或桥接未就绪，请刷新状态并查看启动日志。'}
            # QQ login and injection are manual. Never select a desktop QQ
            # process, open a client, or call the legacy connect action here.
            return {'ok': True, 'data': data, 'message': 'DSH 与桥接已就绪。' +
                    ('SnowLuma 当前账号：' + data['account'] if data['online'] else
                     '请手动登录指定机器人 QQ，并在 SnowLuma 登录管理中挂载该账号的进程。')}
        finally:
            self._stage = ''
            self._lock.release()

    def open(self):
        if not self.snapshot()['bridge_ready']:
            return {'ok': False, 'error': '请先启动 DSH QQ，再打开控制台。'}
        from .service_login import _read, _text
        try:
            token = _text(_read(self.backend / 'config.json').get('consoleToken'))
        except (OSError, ValueError, TypeError):
            token = ''
        if not token:
            return {'ok': False, 'error': '无法读取控制台访问令牌，请查看本机日志中的登录信息。'}
        # Upstream accepts ?token=, saves it in localStorage and clears the query.
        # Only pass it to the browser; never include it in status/action replies.
        if not self._open('http://127.0.0.1:6310/?' + urlencode({'token': token})):
            return {'ok': False, 'error': '浏览器未打开，请查看本机日志中的控制台登录信息。'}
        return {'ok': True, 'message': '控制台已打开并携带当前登录令牌。'}

    def log(self):
        # Explicit read only, fixed files, bounded tail and exact secret redaction.
        from .dsh_logs import combined_tail
        from .service_login import _read, _text, login_info
        path = self.backend / 'config.json'
        try:
            config = _read(path)
            token = _text(config.get('consoleToken'))
            login = 'Access Token: ' + token if token else 'Access Token：配置中未找到令牌'
        except (OSError, ValueError, TypeError):
            config = {}
            login = '控制台登录信息读取失败，请检查此服务的配置；原日志仍可查看。'
        header = f'DSH 控制台当前登录信息\n登录配置：{path}\n面板地址：http://127.0.0.1:6310/\n{login}'
        snow_login = login_info('snowluma')
        header += '\n\nSnowLuma 登录管理\n' + (snow_login or '登录配置尚不可用，请检查 SnowLuma 安装。')
        header += '\nQQ 登录与管理面板登录相互独立；5099 使用面板密码，6310 使用上方控制台令牌。'
        text = combined_tail(self.backend)
        secrets = [config.get('consoleToken')]
        for name, key in [('snowluma', 'accessToken'), ('dsh', 'authToken')]:
            section = config.get(name)
            if isinstance(section, dict):
                secrets.append(section.get(key))
        for secret in secrets:
            if isinstance(secret, str) and secret:
                text = text.replace(secret, '[redacted]')
        return {'ok': True, 'available': True, 'has_login_info': True,
                'text': header + '\n\n启动与聊天日志（从新到旧）：\n' + (text or '暂无 SnowLuma + DSH 启动或聊天日志。')}
