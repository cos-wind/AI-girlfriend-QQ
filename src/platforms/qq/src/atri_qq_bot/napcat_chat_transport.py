"""Pause only ATRI reverse WS before its listener stops; QQ stays logged in."""
import json
from urllib.parse import urlsplit

from atrium_runtime import user_root
from .backend_isolation import transition


def set_paused(paused, port, *, login=None, directory=None):
    from . import napcat_account
    login = login or napcat_account
    directory = directory if directory is not None else user_root() / 'data/runtime'
    marker = directory / 'napcat-chat-pause.json'
    # Startup, including a cold first login, never enables manually disabled clients.
    if not paused and not marker.exists():
        return False
    with transition(directory, name='napcat-chat-transport.lock'):
        saved = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else None
        target = login._napcat_base()
        if target is None:
            if saved:
                raise ValueError('NapCat 管理服务未就绪，尚未恢复聊天连接。')
            return False
        def call(route, payload=None):
            result = login._napcat_call(route, payload, target=target)
            if result.get('code') != 0:
                raise ValueError('NapCat 聊天连接设置失败，请查看管理服务状态。')
            return result.get('data')
        info = call('/QQLogin/GetQQLoginInfo')
        uin = str(info.get('uin') or '') if isinstance(info, dict) else ''
        if not uin.isdigit():
            raise ValueError('尚未确认 NapCat 登录账号，连接配置保持不变。')
        identity = {'uin': uin, 'port': int(port), 'base': target[0]}
        if saved and any(saved.get(k) != v for k, v in identity.items()):
            raise ValueError('NapCat 账号或连接目标已改变，未恢复其他账号的配置。')
        config = call('/OB11Config/GetConfig')
        rows = config.get('network', {}).get('websocketClients') if isinstance(config, dict) else None
        if not isinstance(rows, list):
            raise ValueError('NapCat 网络配置格式异常，未改变连接。')
        def matches(row):
            if not isinstance(row, dict):
                return False
            try:
                url = urlsplit(str(row.get('url', '')))
                return (url.scheme == 'ws' and url.hostname in {'127.0.0.1', 'localhost'}
                        and url.port == int(port) and url.path == '/onebot')
            except ValueError:
                return False
        if paused:
            names = {r.get('name') for r in rows if matches(r) and r.get('enable') is True}
            if saved:
                names.update(saved['names'])
            if not names:
                return False
            if not all(isinstance(name, str) and name for name in names):
                raise ValueError('NapCat 连接名称无效，未改变连接。')
            # Persist intent before the hot update, so an interrupted stop can recover.
            from .qq_astrbot import atomic_json
            atomic_json(marker, {**identity, 'names': sorted(names)})
        else:
            names = set(saved['names'])
            if not names.issubset({r.get('name') for r in rows if matches(r)}):
                raise ValueError('原 NapCat 聊天连接已改变，保留暂停记录，未启用其他连接。')
        changed = False
        for row in rows:
            if matches(row) and row.get('name') in names and row.get('enable') is not (not paused):
                row['enable'] = not paused
                changed = True
        if changed:
            call('/OB11Config/SetConfig', {'config': json.dumps(config, ensure_ascii=False)})
        if not paused:
            marker.unlink(missing_ok=True)
        return changed
