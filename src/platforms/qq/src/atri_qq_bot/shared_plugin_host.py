"""Account-isolated AstrBot hosts loading one maintained plugin installation.

Only explicit chat startup calls ensure_started. Status/config reads are inert.
No QQ process is started, stopped, reconfigured or logged out by this module.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time

from atrium_runtime import user_root
from .astrbot_launcher import astrbot_source, astrbot_temp_environment, _port_open
from .plugin_layout import junction
from .qq_astrbot import atomic_json
from .backend_isolation import transition

ACCOUNTS = {'napcat': (6281, 6283), 'dsh': (6282, 6284)}
PLUGINS = ('astrbot_plugin_qqadmin', 'astrbot_plugin_qq_group_daily_analysis')


def _runtime(root):
    return Path(root) / 'dev/workspace/runtimes/astrbot-atri'


def prepare(root, accounts):
    """Use one dashboard, with distinct authenticated account transports.

    Existing plugin state and dashboard credentials stay in place. Retired
    account hosts are retained on disk; migration stops them explicitly.
    """
    root = Path(root)
    manifest = root / 'data/plugins/astrbot/shared/ingress.json'
    previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    settings = dict(previous, enabled=True, host='atri')
    canonical = root / 'src/platforms/qq/plugins/astrbot'
    runtime = _runtime(root)
    seed = runtime / 'host/data'
    original = json.loads((seed / 'cmd_config.json').read_text(encoding='utf-8-sig'))
    # Validate all identities before writing anything.
    for name, account in accounts.items():
        if name not in ACCOUNTS or not str(account).isdigit():
            raise ValueError('Unknown plugin account')
        if name in previous and str(previous[name]['account']) != str(account):
            raise ValueError('Plugin account binding changed; use a separate state directory')
    for name, account in accounts.items():
        if name not in ACCOUNTS or not str(account).isdigit():
            raise ValueError('Unknown plugin account')
        ws_port, dashboard_port = ACCOUNTS[name]
        row = previous.get(name) or {'url': f'ws://127.0.0.1:{ws_port}/ws',
                                   'token': secrets.token_urlsafe(32), 'account': str(account)}
        if str(row['account']) != str(account):
            raise ValueError('Plugin account binding changed; use a separate state directory')
        settings[name] = row
    platforms = original.setdefault('platform', [])
    for name in ACCOUNTS:
        if name not in settings:
            continue
        row = settings[name]
        platform_id = 'atri-plugin-' + name
        found = next((p for p in platforms if p.get('id') == platform_id), None)
        if found is None:
            platforms.append({'id': platform_id, 'type': 'aiocqhttp', 'enable': True,
                'ws_reverse_host': '127.0.0.1', 'ws_reverse_port': ACCOUNTS[name][0],
                'ws_reverse_token': row['token']})
        elif found.get('ws_reverse_port') != ACCOUNTS[name][0] or found.get('ws_reverse_token') != row['token']:
            raise ValueError('Existing plugin transport differs; refusing to overwrite')
    # The old full-chat transport is superseded by the two explicit chat cards.
    for platform in platforms:
        if platform.get('id') == 'atri-qq-trial':
            platform['enable'] = False
    original.setdefault('dashboard', {}).update(enable=True, host='127.0.0.1', port=6186)
    original['plugin_set'] = list(dict.fromkeys([*original.get('plugin_set', []), 'atri_bridge', *PLUGINS]))
    junction(seed / 'plugins/astrbot_plugin_atri_bridge', canonical / 'maintained/astrbot_plugin_atri_bridge')
    for plugin in PLUGINS:
        junction(seed / 'plugins' / plugin, canonical / 'third_party' / plugin)
    bridge_path = seed / 'config/astrbot_plugin_atri_bridge_config.json'
    bridge = json.loads(bridge_path.read_text(encoding='utf-8-sig')) if bridge_path.exists() else {'enabled': True}
    bridge['ingress_accounts'] = ['atri-plugin-' + name + '=' + str(settings[name]['account'])
                                  for name in ACCOUNTS if name in settings]
    atomic_json(bridge_path, bridge)
    # Native config routing keeps passive learning/proactive hooks off ingress
    # accounts. No third-party plugin source or database is merged/modified.
    profile = seed / 'config/abconf_atri-ingress.json'
    if not profile.exists():
        scoped = dict(original, plugin_set=['atri_bridge', *PLUGINS],
            provider_settings={**original.get('provider_settings', {}), 'enable': False},
            wake_prefix=['/'], disable_builtin_commands=True)
        atomic_json(profile, scoped)
    connection_path = runtime / 'connection.json'
    connection = json.loads(connection_path.read_text(encoding='utf-8-sig')) if connection_path.exists() else {}
    connection.update(directory=str(runtime.resolve()), plugin_host_only=True,
        dashboard_port=6186, ingress_ports=[ACCOUNTS[name][0] for name in ACCOUNTS if name in settings])
    atomic_json(seed / 'cmd_config.json', original)
    atomic_json(connection_path, connection)
    atomic_json(manifest, settings)
    return settings


def ensure_started(name, *, root=None, spawn=None, probe=None, starter=None):
    root = Path(root) if root else user_root()
    manifest = root / 'data/plugins/astrbot/shared/ingress.json'
    if not manifest.exists():
        return False
    settings = json.loads(manifest.read_text(encoding='utf-8'))
    if settings.get('enabled') is not True or name not in settings:
        return False
    if settings.get('host') == 'atri':
        from .qq_astrbot import start_managed, process_state
        probe = probe or _port_open
        runtime = _runtime(root)
        with transition(root / 'data/runtime', name='plugin-host-shared.lock'):
            port = ACCOUNTS[name][0]
            if probe(port):
                return True
            connection = json.loads((runtime / 'connection.json').read_text(encoding='utf-8-sig'))
            (starter or start_managed)(connection)
            deadline = time.monotonic() + 90
            while not probe(port):
                if (starter is None and process_state(directory=runtime)['phase'] == 'failed') or time.monotonic() >= deadline:
                    raise RuntimeError('Plugin host did not start; inspect astrbot-atri/astrbot.log')
                time.sleep(.2)
        return True
    spawn, probe = spawn or subprocess.Popen, probe or _port_open
    runtime = root / 'dev/workspace/runtimes/astrbot-shared' / name
    port, dashboard_port = ACCOUNTS[name]
    with transition(root / 'data/runtime', name='plugin-host-' + name + '.lock'):
        if probe(port):
            # The gate's authenticated handshake confirms identity. Never kill
            # or reconfigure an existing listener to make room for this host.
            return True
        python = root / 'dev/workspace/qq-trial/.venv/Scripts/python.exe'
        source = astrbot_source(root)
        env = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
            env.pop(key, None)
        env.update(astrbot_temp_environment(runtime / 'host', root=root))
        env.update(ASTRBOT_ROOT=str(runtime / 'host'), PYTHONUTF8='1',
                   PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        with (runtime / 'astrbot.log').open('ab') as log:
            child = spawn([str(python), str(runtime / 'host_entry.py'), str(source)],
                cwd=str(source), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 90
        while not probe(port):
            if child.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Plugin host did not start; inspect account-scoped astrbot.log')
            time.sleep(.2)
    return True


def stop(name, *, root=None, stopper=None):
    root = Path(root) if root else user_root()
    manifest = root / 'data/plugins/astrbot/shared/ingress.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')).get('host') == 'atri':
        # Each chat owns its own gate connection, not the shared service.
        return
    entry = root / 'dev/workspace/runtimes/astrbot-shared' / name / 'host_entry.py'
    if not entry.exists():
        return
    from .service_process import stop_entry
    with transition(root / 'data/runtime', name='plugin-host-' + name + '.lock'):
        try:
            (stopper or stop_entry)(entry, port=ACCOUNTS[name][0])
        except ValueError:
            # Windows venv Python has a launcher parent and interpreter child.
            # Stopping the parent may race the child's final exit. Re-census
            # the same unique entry instead of selecting by PID/name/port.
            time.sleep(.2)
            (stopper or stop_entry)(entry, port=ACCOUNTS[name][0])


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('name', choices=ACCOUNTS)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'start':
        if args.name == 'dsh':
            from .dsh_connection_install import install as install_connection
            install_connection(args.root)
            from .dsh_ecosystem_install import install as install_ecosystem
            install_ecosystem(args.root)
        if args.name == 'dsh' and (args.root / 'data/plugins/astrbot/shared/ingress.json').exists():
            from .dsh_plugin_install import install
            install(args.root)
        ensure_started(args.name, root=args.root)
    else:
        stop(args.name, root=args.root)


if __name__ == '__main__':
    main()
