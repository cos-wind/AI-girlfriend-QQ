"""Current panel login information, read only on an explicit local log request.

Never import upstream auth managers: some generate credentials on construction.
Password hashes and unrelated OneBot/API secrets are never presented as logins.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import tomllib


def _config_path(service: str) -> Path | None:
    if service == 'napcat':
        from .napcat_session import LoginSession
        from .runtime.observability import _find_napcat_webui_config
        pending = LoginSession().pending
        if pending.get('workdir'):
            return Path(pending['workdir']) / 'config/webui.json'
        return _find_napcat_webui_config()
    if service == 'snowluma':
        from .snowluma_launcher import SnowLumaLauncher
        source, _ = SnowLumaLauncher()._paths()
        return source / 'config/webui.json'
    if service == 'maibot':
        from .maibot_launcher import MaiBotLauncher
        return MaiBotLauncher()._installation() / 'data/webui.json'
    if service == 'astrbot':
        from atrium_runtime import resource_root, user_root
        from .astrbot_launcher import astrbot_source
        runtime = user_root() / 'data/runtime/astrbot'
        source = runtime if runtime.exists() else astrbot_source(resource_root())
        return source / 'data/cmd_config.json'
    if service == 'astrbot-trial':
        from .snowluma_trial import trial_directory
        return trial_directory() / 'host/data/cmd_config.json'
    return None


def _read(path: Path) -> dict:
    with path.open('rb') as stream:
        data = stream.read(262_145)
    if len(data) > 262_144:
        raise ValueError('配置过大')
    value = (tomllib.loads(data.decode('utf-8-sig')) if path.suffix == '.toml'
             else json.loads(data.decode('utf-8-sig')))
    if not isinstance(value, dict):
        raise ValueError('配置格式错误')
    return value


def _text(value) -> str:
    return value if isinstance(value, str) and value.isprintable() else ''


def _url(port, default: int, *, tls: bool = False, path: str = '/') -> str:
    port = int(port if port is not None else default)
    if not 1 <= port <= 65535:
        raise ValueError('端口无效')
    return f'{"https" if tls else "http"}://127.0.0.1:{port}{path}'


def _verified_trial_password(path: Path, panel: dict) -> str:
    """Only reveal the saved initial password while its current hash matches.

    No upstream imports: constructing an auth/config manager can write state.
    PBKDF2 takes precedence over the legacy MD5 field, as in AstrBot login.
    """
    try:
        candidate = _text(_read(path.parents[2] / 'connection.json').get('dashboard_password'))
        if not candidate:
            return ''
        stored = _text(panel.get('pbkdf2_password'))
        if stored:
            algorithm, iterations, salt, digest = stored.split('$')
            count = int(iterations)
            if algorithm != 'pbkdf2_sha256' or not 1 <= count <= 2_000_000:
                return ''
            salt_bytes, expected = bytes.fromhex(salt), bytes.fromhex(digest)
            if not salt_bytes or len(expected) != 32:
                return ''
            actual = hashlib.pbkdf2_hmac('sha256', candidate.encode('utf-8'), salt_bytes, count)
        else:
            stored = _text(panel.get('password'))
            if len(stored) != 32:
                return ''
            expected = bytes.fromhex(stored)
            actual = hashlib.md5(candidate.encode('utf-8')).digest()
        return candidate if hmac.compare_digest(actual, expected) else ''
    except (OSError, ValueError, TypeError, AttributeError, IndexError):
        return ''


def login_info(service: str) -> str:
    """Use the same installation/data selection as each launcher, without probes."""
    lines = []
    try:
        path = _config_path(service)
        if path is None or not path.is_file():
            return ''
        config = _read(path)
        lines = [f'登录配置：{path}']
        if service == 'napcat':
            token = _text(config.get('token'))
            lines.append('Access Token: ' + token if token else 'Access Token：配置中未找到令牌')
            lines.append('面板地址：' + _url(config.get('port'), 6099, path='/webui'))
            if config.get('disableWebUI'):
                lines.append('管理面板已在配置中禁用')
        elif service == 'snowluma':
            lines.append('登录方式：面板密码（不是 OneBot 访问令牌）')
            lines.append('密码：加密保存，无法还原明文；请使用你设置的密码。'
                         if _text(config.get('passwordHash')) else '密码：尚未找到有效的密码配置。')
            entry = path.parent.parent / 'index.mjs'
            persistent = False
            try:
                with entry.open('rb') as source:
                    persistent = (b'// ATRI_WEBUI_PERSISTENT_SESSIONS_V1' in source.read(256)
                                  and (entry.parent / 'atri-webui-sessions.mjs').is_file())
            except OSError:
                pass
            lines.append('QQ 在线与面板登录独立；此安装支持同一浏览器保留登录，'
                         '使用时自动续期，连续 30 天未使用、主动退出或改密后需重新登录。'
                         '会话保存在本机，服务重启不会清空；已运行的旧服务需重启一次加载补丁。'
                         if persistent else
                         'QQ 在线不代表面板已登录；当前版本网页登录有效期 24 小时，'
                         'SnowLuma 服务重启后立即失效，需要重新输入面板密码。')
            if config.get('mustChangePassword'):
                lines.append('首次登录密码仅在首次启动记录中提供，登录后需修改。')
            runtime_path = path.parent / 'runtime.json'
            runtime = _read(runtime_path) if runtime_path.is_file() else {}
            lines.append('面板地址：' + _url(runtime.get('webuiPort'), 5099,
                                            tls=bool(runtime.get('webuiTls', {}).get('enabled'))))
        elif service in {'astrbot', 'astrbot-trial'}:
            panel = config.get('dashboard', {})
            lines.append('实例：ATRI 接入实例（账号与独立实例不共用）'
                         if service == 'astrbot-trial' else '实例：独立实例（账号与 ATRI 接入实例不共用）')
            lines.append('用户名：' + (_text(panel.get('username')) or 'astrbot'))
            initial = _verified_trial_password(path, panel) if service == 'astrbot-trial' else ''
            if initial:
                lines.append('当前有效的初始密码：' + initial)
            else:
                lines.append('密码：加密保存，无法还原明文；请使用此实例设置的密码。'
                             if _text(panel.get('password')) or _text(panel.get('pbkdf2_password'))
                             else '密码：尚未找到有效的密码配置。')
            lines.append('面板地址：' + _url(panel.get('port'), 6186 if service == 'astrbot-trial' else 6185,
                                            tls=bool(panel.get('ssl', {}).get('enable'))))
            if not panel.get('enable', True):
                lines.append('管理面板已在配置中禁用')
        elif service == 'maibot':
            token = _text(config.get('access_token'))
            lines.append('Access Token: ' + token if token else 'Access Token：配置中未找到令牌')
            panel = _read(path.parent.parent / 'config/bot_config.toml').get('webui', {})
            lines.append('面板地址：' + _url(panel.get('port'), 8001))
            if not panel.get('enabled', True):
                lines.append('管理面板已在配置中禁用')
        return '\n'.join(lines)
    except (OSError, ValueError, TypeError, AttributeError):
        # Don't include exception text: JSON errors or filenames may carry secrets.
        return '\n'.join(lines + ['部分登录信息读取失败，请检查此服务的配置；原日志仍可查看。'])
