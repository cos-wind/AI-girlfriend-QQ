"""Explicit, isolated SnowLuma → AstrBot → shared full QQ application.

Construction and status are read-only. Explicit start connects the dedicated
client automatically; stop never closes QQ or changes NapCat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
import webbrowser

from atrium_runtime import resource_root, user_root, is_packaged
from . import qq_astrbot as host
from .snowluma_qq import SnowLumaQQ
from .backend_isolation import transition
from .plugin_layout import runtime_directory, managed
from .astrbot_launcher import astrbot_source


def trial_directory() -> Path:
    return runtime_directory()


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('本地试用配置格式错误，请检查配置文件。')
    return data


def active(directory: Path | None = None) -> bool:
    """A stale heartbeat must not permit a second reply chain over live ports."""
    directory = directory or trial_directory()
    path = directory / 'connection.json'
    if path.exists() and _read(path).get('plugin_host_only') is True:
        # A plugin service has no full-chat core and cannot compete with it.
        return False
    if host.process_state(directory=directory)['phase'] in {'starting', 'running'}:
        return True
    path = directory / 'connection.json'
    if not path.exists():
        return False
    settings = _read(path)
    keys = ('core_port', 'ws_port') + (('onebot_port',) if settings.get('full_chat') else ())
    return any(host.listening(int(settings[key])) for key in keys)


def configure_snowluma(source: Path, settings: dict) -> None:
    """Seed the next attached account; never rewrite live accounts.

    SnowLuma v2.2 reads the global file on attachment, but per-account snapshots
    override it. Refuse that case instead of claiming an unapplied edit worked.
    """
    folder = source / 'config'
    if not (source / 'index.mjs').is_file():
        raise ValueError('SnowLuma 尚未安装完整。')
    if any(folder.glob('onebot_*.json')):
        # Existing accounts require a live authenticated reload. Do not silently
        # alter a running account or its unrelated OneBot connections.
        expected = f"ws://127.0.0.1:{settings['ws_port']}/ws"
        for path in folder.glob('onebot_*.json'):
            data = _read(path)
            clients = data.get('networks', {}).get('wsClients', [])
            if not any(row.get('name') == 'atri-snowluma' and row.get('url') == expected
                       and row.get('accessToken') == settings['ws_token']
                       and row.get('enabled', True) is True for row in clients):
                raise ValueError('SnowLuma 已有账号配置，未改动。请在该账号网络设置中添加试用目录 connection.json 对应的反向 WS，再重试。')
    path = folder / 'onebot.json'
    data = _read(path) if path.exists() else {
        'networks': {'httpServers': [], 'httpClients': [], 'wsServers': [], 'wsClients': []},
        'statusCommand': {'enabled': False, 'swallow': False, 'cooldownSeconds': 30, 'trigger': '/status'},
        'historySync': {'enabled': False}, 'notifications': {'channelIds': []},
    }
    nets = data.setdefault('networks', {})
    clients = nets.setdefault('wsClients', [])
    if not isinstance(clients, list) or not all(isinstance(row, dict) for row in clients):
        raise ValueError('SnowLuma 网络配置格式异常，未改动。')
    row = {'name': 'atri-snowluma', 'enabled': True,
           'url': f"ws://127.0.0.1:{settings['ws_port']}/ws",
           'accessToken': settings['ws_token'], 'role': 'Universal',
           'messageFormat': 'array', 'reportSelfMessage': False, 'reconnectIntervalMs': 1000}
    merged = [item for item in clients if item.get('name') != 'atri-snowluma'] + [row]
    if clients == merged:
        return
    if path.exists():
        backup = folder / 'onebot.atri-backup.json'
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    nets['wsClients'] = merged
    host.atomic_json(path, data)


class SnowLumaTrial:
    def __init__(self, *, root: Path | None = None, directory: Path | None = None,
                 config_loader=None, qq=None):
        self._root = root or resource_root()
        self._directory = directory or trial_directory()
        self._config_loader = config_loader
        self._qq = qq if qq is not None else SnowLumaQQ(root=root)
        self._lock = Lock()

    def _config(self):
        if self._config_loader:
            return self._config_loader()
        from atri_shared.config import load_config
        return load_config()

    def _settings(self):
        return _read(self._directory / 'connection.json')

    def snapshot(self) -> dict:
        process = host.process_state(directory=self._directory)
        phase = process['phase']
        connection = host.connection_state(directory=self._directory)
        # Only a fresh plugin observation can say QQ is online.
        online = phase == 'running' and connection.get('online') is True
        return {'phase': phase, 'online': online,
                'uin': connection.get('uin', '') if online else '',
                'message': process.get('message', '')}

    def prepare(self, *, configure_qq: bool = True) -> dict:
        if is_packaged():
            raise ValueError('此文字试用需要本机 AstrBot 源码环境，原有 QQ 功能仍可使用。')
        source = astrbot_source(self._root)
        python = self._root / 'dev/workspace/qq-trial/.venv/Scripts/python.exe'
        if not python.is_file():
            raise ValueError('未找到 AstrBot 独立环境，未启动或改动 QQ。')
        config = self._config()
        if host.listening(config.port):
            raise ValueError('请先停止原有 QQ 聊天，再启动文字试用；保留 QQ 登录。')
        if not all((config.openai_model, config.openai_base_url, config.openai_api_key)):
            raise ValueError('请先在聊天设置中配置模型。')
        settings = host.prepare(source, directory=self._directory, ports=(8796, 6200, 6186))
        settings['python'] = str(python)
        settings['full_chat'] = True
        settings['background_qq'] = True
        settings.setdefault('onebot_port', 6201)
        if any(host.listening(int(settings[key])) for key in host.service_ports(settings)):
            raise ValueError('试用端口被占用，未启动服务；不会关闭占用端口的程序。')
        plugin_path = self._directory / 'host/data/config/astrbot_plugin_atri_bridge_config.json'
        plugin = _read(plugin_path)
        plugin['allow_groups'] = config.reply_mode == 'mention'
        plugin['onebot_url'] = f"ws://127.0.0.1:{settings['onebot_port']}/onebot"
        plugin['onebot_token'] = settings['core_api_key']
        host.atomic_json(plugin_path, plugin)
        # The AstrBot service card starts only this host and its core. Account
        # snapshots belong to QQ/DSH and must neither gate nor change that action.
        if configure_qq:
            configure_snowluma(self._root / 'data/runtime/snowluma', settings)
        host.atomic_json(self._directory / 'connection.json', settings)
        return settings

    def execute(self, payload: dict) -> dict:
        action = payload.get('action', 'status')
        if action == 'status':
            return {'ok': True, 'data': self.snapshot()}
        if action not in {'start', 'host-start', 'stop', 'qq', 'panel', 'log'}:
            raise ValueError('不支持的文字试用操作。')
        if not self._lock.acquire(blocking=False):
            raise ValueError('文字试用操作正在进行，请稍候。')
        try:
            message = ''
            if action in {'start', 'host-start'}:
                if (self._directory / 'connection.json').exists() and self._settings().get('plugin_host_only') is True:
                    if action != 'host-start':
                        raise ValueError('请从对应账号卡片启动聊天；此 AstrBot 仅提供共享插件服务。')
                    host.start_managed(self._settings())
                    return {'ok': True, 'data': self.snapshot()}
                with transition(None if managed(self._directory) else self._directory.parent):
                    # Recovery of a missing QQ must obey the same exclusion
                    # as a cold start, even when our host is already running.
                    if host.listening(self._config().port):
                        raise ValueError('请先停止原有 QQ 聊天，未打开或修改 QQ。')
                    if host.process_state(directory=self._directory)['phase'] not in {'starting', 'running'}:
                        host.start_managed(self.prepare(configure_qq=action == 'start'))
                    if action == 'start' and not self.snapshot()['online']:
                        # The launcher reuses only our exact executable and
                        # persistent profile. Launching never implies online.
                        message = self._qq.connect()
            elif action == 'stop':
                host.stop_managed(directory=self._directory)
                if active(self._directory):
                    raise ValueError('试用服务尚有端口占用，暂不能启动另一条回复链路。')
            elif action == 'qq':
                if host.process_state(directory=self._directory)['phase'] != 'running':
                    raise ValueError('请先启动文字试用，服务就绪后再打开机器人 QQ。')
                if host.listening(self._config().port):
                    raise ValueError('请先停止原有 QQ 聊天，未打开或修改 QQ。')
                message = self._qq.connect()
            elif action == 'panel':
                settings = self._settings()
                from .astrbot_launcher import _dashboard_ready
                url = f"http://127.0.0.1:{int(settings['dashboard_port'])}/"
                if not _dashboard_ready(url):
                    raise ValueError('试用面板尚未就绪，请稍后重试或查看启动日志。')
                if not webbrowser.open(url):
                    raise ValueError(f'浏览器未打开，请访问 {url}')
            else:
                # The new host prints its initial panel password here. Never
                # expose connection.json, provider keys or log text to the UI.
                log = self._directory / 'astrbot.log'
                if not log.is_file():
                    log = self._directory / 'supervisor.log'
                if not log.is_file():
                    raise ValueError('暂无试用日志，请先启动文字试用。')
                os.startfile(str(log))
            data = self.snapshot()
            if message:
                data['message'] = message
            return {'ok': True, 'data': data}
        finally:
            self._lock.release()
