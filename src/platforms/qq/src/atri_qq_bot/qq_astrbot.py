"""Prepare and run an isolated AstrBot trial; never manages QQ login sessions."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from importlib.resources import files
from urllib.request import ProxyHandler, build_opener

from atrium_runtime import resource_root, source_python, user_root
from .astrbot_launcher import astrbot_source, astrbot_temp_environment
from . import plugin_layout

ROOT = resource_root()
SHARED_PYTHON = user_root() / 'dev/workspace/qq-trial/.venv/Scripts/python.exe'
TRIAL = Path(os.environ.get('ATRI_QQ_TRIAL_DIR') or plugin_layout.runtime_directory())
PLUGIN = 'astrbot_plugin_atri_bridge'
INSTANCE = 'atri-qq-trial'


def bridge_source() -> Path:
    """Locate the deployable plugin in a checkout or installed distribution."""
    return Path(str(files(PLUGIN)))


def prepare(astrbot: Path, *, directory: Path = TRIAL,
            ports: tuple[int, int, int] = (8795, 6199, 6185)) -> dict:
    """Create private trial settings once, preserving subsequent user edits."""
    astrbot = astrbot.resolve()
    if not (astrbot / 'main.py').is_file() or not (astrbot / 'astrbot').is_dir():
        raise ValueError('请用 --astrbot 指定 AstrBot 源码目录')
    directory.mkdir(parents=True, exist_ok=True)
    settings_path = directory / 'connection.json'
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
        settings['astrbot'] = str(astrbot)
    else:
        settings = dict(astrbot=str(astrbot), core_port=ports[0], ws_port=ports[1],
                        dashboard_port=ports[2], core_api_key=secrets.token_urlsafe(32),
                        ws_token=secrets.token_urlsafe(32),
                        dashboard_password='Atri9_' + secrets.token_urlsafe(18))
    settings['directory'] = str(directory.resolve())
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    plugin_layout.prepare_state(directory)
    data = directory / 'host/data'
    (data / 'config').mkdir(parents=True, exist_ok=True)
    destination = data / 'plugins' / PLUGIN
    if plugin_layout.managed(directory):
        plugin_layout.junction(destination, bridge_source())
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for source in bridge_source().iterdir():
            if source.is_file() and source.suffix in {'.py', '.json', '.yaml'}:
                shutil.copy2(source, destination / source.name)
    host_config = data / 'cmd_config.json'
    plugin_config = data / 'config' / f'{PLUGIN}_config.json'
    if not host_config.exists():
        host_config.write_text(json.dumps({
            'platform': [{'id': INSTANCE, 'type': 'aiocqhttp', 'enable': True,
                          'ws_reverse_host': '127.0.0.1', 'ws_reverse_port': settings['ws_port'],
                          'ws_reverse_token': settings['ws_token']}],
            'platform_settings': {'enable_id_white_list': False, 'ignore_bot_self_message': True,
                                  'ignore_at_all': True},
            'provider_settings': {'enable': False},
            'provider': [], 'provider_sources': [], 'plugin_set': ['atri_bridge'],
            'dashboard': {'enable': True, 'host': '127.0.0.1', 'port': settings['dashboard_port']},
            'disable_builtin_commands': True, 'disable_metrics': True, 't2i': False,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    if not plugin_config.exists():
        plugin_config.write_text(json.dumps({
            'enabled': True, 'platform_ids': [INSTANCE],
            'core_url': f"http://127.0.0.1:{settings['core_port']}",
            'core_api_key': settings['core_api_key'],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    return settings


def listening(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def core(settings: dict) -> None:
    sys.path.insert(0, str(ROOT / 'src'))
    from atri_workspace import activate
    activate()
    if settings.get('full_chat'):
        from .full_chat import serve_full_chat
        asyncio.run(serve_full_chat(settings))
        return
    from atri_shared.config import load_config
    from atri_bot.runtime import serve
    config = load_config(overrides={
        'CORE_API_ENABLED': 'true', 'CORE_API_HOST': '127.0.0.1',
        'CORE_API_PORT': settings['core_port'], 'CORE_API_KEY': settings['core_api_key'],
    })
    asyncio.run(serve(config))


def run(settings: dict, *, managed: bool = False) -> None:
    directory = Path(settings.get('directory', TRIAL))
    # Check the configured legacy listener without exposing model credentials.
    sys.path.insert(0, str(ROOT / 'src'))
    from atri_workspace import activate
    activate()
    from atri_shared.config import load_config
    legacy_port = load_config().port
    host_only = settings.get('plugin_host_only') is True
    if not host_only and listening(legacy_port):
        raise ValueError('旧 QQ 直连服务仍在运行，请先在桌面停止 QQ 回复服务；保留 QQ 登录')
    if any(listening(settings[key]) for key in service_ports(settings)):
        raise ValueError('试用端口已被占用，请先关闭此前的试用进程或调整 connection.json')
    python = Path(settings.get('python') or SHARED_PYTHON)
    if not python.is_file():
        raise ValueError('尚未安装 AstrBot 的独立环境，请按同目录 README.md 安装')
    _apply_pending_plugins(directory)
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                       ASTRBOT_ROOT=str(directory / 'host'),
                       ATRI_QQ_TRIAL_DIR=str(directory),
                       ASTRBOT_DASHBOARD_INITIAL_PASSWORD=settings['dashboard_password'])
    # Do not inherit desktop/Python paths into AstrBot's independent environment.
    for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__'):
        environment.pop(name, None)
    environment.update(astrbot_temp_environment(directory / 'host'))
    children = []
    background = None
    qq_client = Path(settings.get('qq_client') or (user_root() / 'data/runtime/qq-snowluma/client/QQ.exe'
                     if plugin_layout.managed(directory) else directory / 'client/QQ.exe'))
    if not host_only and settings.get('background_qq') is True:
        from .snowluma_windows import QQBackground
        background = QQBackground(qq_client)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (directory / 'core.log').open('a', encoding='utf-8') as core_log, \
            (directory / 'astrbot.log').open('a', encoding='utf-8') as host_log:
        try:
            if managed:
                write_state('starting', directory=directory)
            if not host_only:
                children.append(subprocess.Popen([sys.executable, '-m', 'atri_qq_bot.qq_astrbot', 'core'],
                                              cwd=ROOT, stdout=core_log, stderr=core_log,
                                              env=dict(os.environ, ATRI_QQ_TRIAL_DIR=str(directory), PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                                                       PYTHONPATH=str(ROOT / 'src/shared') + os.pathsep + str(ROOT / 'src')),
                                              creationflags=flags))
            for _ in range(0 if host_only else 150):
                if children[0].poll() is not None:
                    raise RuntimeError(f'核心启动失败，请查看 {directory / "core.log"}')
                if status(settings)['core'] and (not settings.get('full_chat') or listening(settings['onebot_port'])):
                    break
                if managed:
                    write_state('starting', directory=directory)
                    if (directory / 'stop').exists():
                        return
                time.sleep(0.2)
            else:
                if not host_only:
                    raise RuntimeError('核心未在 30 秒内开始监听，请查看 core.log')
            command = ([str(python), str(Path(__file__).with_name('shared_plugin_profiles.py')), settings['astrbot']]
                       if host_only else [str(python), str(Path(settings['astrbot']) / 'main.py'),
                                          '--webui-dir', str(Path(settings['astrbot']) / 'data/dist')])
            children.append(subprocess.Popen(command,
                                              cwd=settings['astrbot'], env=environment,
                                              stdout=host_log, stderr=host_log, creationflags=flags))
            from .astrbot_launcher import _dashboard_ready
            deadline = time.monotonic() + 90
            while all(child.poll() is None for child in children):
                if managed:
                    write_state('starting', directory=directory)
                    if (directory / 'stop').exists():
                        return
                listeners = settings['ingress_ports'] if host_only else [settings['ws_port']]
                if all(listening(port) for port in listeners) and _dashboard_ready(
                        f"http://127.0.0.1:{settings['dashboard_port']}/"):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('试用宿主启动超时，请查看试用 astrbot.log')
                time.sleep(0.5)
            else:
                raise RuntimeError('试用宿主启动失败，请查看试用 astrbot.log')
            print('ATRI + AstrBot 试用已启动，按 Ctrl+C 停止这两个试用进程。', flush=True)
            print(f"AstrBot: http://127.0.0.1:{settings['dashboard_port']}", flush=True)
            print(f"反向 WS: ws://127.0.0.1:{settings['ws_port']}/ws", flush=True)
            print(f'本地连接配置：{directory / "connection.json"}（不要分享）', flush=True)
            while all(child.poll() is None for child in children):
                if managed:
                    write_state('running', directory=directory)
                    if (directory / 'stop').exists():
                        return
                if background is not None:
                    background.update(connection_state(directory=directory).get('online') is True)
                time.sleep(0.5)
            raise RuntimeError(f'试用进程已退出，请查看 {directory} 下的日志')
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                                       creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            if managed:
                write_state('stopped', directory=directory)


def status(settings: dict) -> dict:
    result = {'core': False, 'astrbot': listening(settings['dashboard_port']),
              'onebot_listener': listening(settings['ws_port'])}
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{settings['core_port']}/api/v1/health", timeout=2) as response:
            health = json.load(response)
        result['core'] = health.get('ok') is True and health.get('service') == 'atri-core'
    except (OSError, ValueError):
        pass
    # A listening WebSocket is not proof of QQ login or a successful reply.
    return result


def service_ports(settings: dict) -> tuple:
    if settings.get('plugin_host_only') is True:
        return ('dashboard_port',) + (('capability_port',) if settings.get('capability_port') else ())
    return (('core_port', 'ws_port', 'dashboard_port')
            + (('onebot_port',) if settings.get('full_chat') else ())
            + (('capability_port',) if settings.get('capability_port') else ()))



def write_state(phase: str, message: str = '', *, directory: Path = TRIAL) -> None:
    atomic_json(directory / 'process.json', {'phase': phase, 'message': message,
                                       'updated': time.time()})


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    # Windows readers briefly deny delete/replace sharing. Keep the atomic
    # snapshot, allowing a short reader to close without killing the supervisor.
    for attempt in range(21):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(0.05)


def _read_snapshot(path: Path) -> dict:
    for attempt in range(6):
        try:
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.01)


def process_state(*, directory: Path = TRIAL) -> dict:
    try:
        state = _read_snapshot(directory / 'process.json')
    except (FileNotFoundError, ValueError):
        return {'phase': 'stopped'}
    except OSError:
        return {'phase': 'failed', 'message': '无法读取试用状态，请查看日志；不要同时启动其他回复链路。'}
    if state.get('phase') in {'starting', 'running'} and time.time() - state.get('updated', 0) > 8:
        return {'phase': 'failed', 'message': '试用服务意外退出，请重新启动。'}
    return state


def _apply_pending_plugins(directory: Path) -> None:
    # Also called in the fresh supervisor: a long-lived desktop may still
    # hold the previous start_managed implementation after a code update.
    resolved = directory.resolve()
    pending_root = resolved.parents[3] if resolved.parts[-4:] == ('dev', 'workspace', 'runtimes', 'astrbot-atri') else None
    pending = pending_root / 'data/plugins/astrbot/atri/pending-qzone.json' if pending_root else None
    if pending is not None and pending.exists():
        from .qzone_install import apply_pending
        if any(listening(port) for port in (6186, 6281, 6282)):
            raise ValueError('QQ空间等待宿主正常停止后安装，不修改在线插件')
        apply_pending(pending_root)


def start_managed(settings: dict) -> None:
    directory = Path(settings.get('directory', TRIAL))
    if process_state(directory=directory)['phase'] in {'starting', 'running'}:
        return
    _apply_pending_plugins(directory)
    (directory / 'stop').unlink(missing_ok=True)
    atomic_json(directory / 'host/data/plugin_data/atri_bridge/connection.json',
                {'online': False, 'updated': time.time()})
    write_state('starting', directory=directory)
    command, environment = source_python('-m', 'atri_qq_bot.qq_astrbot', 'managed')
    environment.update(ATRI_QQ_TRIAL_DIR=str(directory), PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                       PYTHONPATH=str(ROOT / 'src/shared') + os.pathsep + str(ROOT / 'src'))
    with (directory / 'supervisor.log').open('a', encoding='utf-8') as log:
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] AstrBot supervisor starting', file=log, flush=True)
        try:
            subprocess.Popen(command, cwd=ROOT,
                             env=environment, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except OSError:
            write_state('failed', '试用服务启动失败，请查看日志。', directory=directory)
            raise


def stop_managed(*, directory: Path = TRIAL) -> None:
    if process_state(directory=directory)['phase'] not in {'starting', 'running'}:
        return
    (directory / 'stop').touch()
    deadline = time.monotonic() + 12
    while process_state(directory=directory)['phase'] in {'starting', 'running'}:
        if time.monotonic() >= deadline:
            raise ValueError('试用服务尚未停止，请稍后重试；暂不启动另一条回复链路。')
        time.sleep(0.1)


def connection_state(*, directory: Path = TRIAL) -> dict:
    try:
        data = _read_snapshot(directory / 'host/data/plugin_data/atri_bridge/connection.json')
        if time.time() - data.get('updated', 0) <= 12:
            return {key: data[key] for key in ('online', 'uin') if key in data}
    except (OSError, ValueError):
        pass
    return {'online': False}


def main() -> None:
    parser = argparse.ArgumentParser(description='QQ → SnowLuma/NapCat → AstrBot → ATRI 试用')
    parser.add_argument('action', choices=('prepare', 'run', 'managed', 'core', 'status'))
    parser.add_argument('--astrbot', type=Path, default=astrbot_source(ROOT))
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare(args.astrbot)
            print('试用配置已准备好；原 QQ 登录、主 .env 和 AstrBot 原数据均保留。')
            return
        settings = json.loads((TRIAL / 'connection.json').read_text(encoding='utf-8-sig'))
        if args.action == 'core':
            core(settings)
        elif args.action in {'run', 'managed'}:
            run(settings, managed=args.action == 'managed')
        else:
            print(json.dumps(status(settings), ensure_ascii=False))
    except KeyboardInterrupt:
        print('试用已停止，QQ 登录会话保留。')
    except (OSError, ValueError, RuntimeError) as exc:
        if args.action == 'managed':
            write_state('failed', str(exc))
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
