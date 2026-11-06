"""Install reviewed QQ plugins into the stopped ATRI-connected host only."""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from . import qq_astrbot as host
from . import plugin_layout

PLUGIN = 'astrbot_plugin_qqadmin'
REVISION = 'a94a369ec5d17daa9a37f523ca861316fbcf9c30'
CULTURE_PLUGIN = 'astrbot_plugin_self_learning'
CULTURE_REVISION = 'cef208d24d0d5cbf25356320508406f98ae6997d'


def culture_defaults(schema):
    config = defaults(schema)
    disabled = {'enable_affection_system', 'enable_daily_mood', 'enable_startup_random_mood',
        'enable_emotion_learning_gate', 'enable_expression_forgetting', 'enable_persona_evolution',
        'use_persona_manager_updates', 'auto_apply_persona_updates', 'auto_apply_approved_persona',
        'enable_social_context_injection', 'enable_goal_driven_chat', 'enable_memory_graph',
        'enable_knowledge_graph', 'enable_time_decay', 'enable_memory_cleanup', 'enable_ml_analysis',
        'enable_llm_hooks', 'enable_realtime_learning', 'enable_realtime_llm_filter',
        'enable_realtime_v2_processing', 'jargon_websearch_enabled'}
    for group in config.values():
        if isinstance(group, dict):
            for key in group.keys() & disabled:
                group[key] = False
    config['Integration_Settings'].update(livingmemory_plugin_name='atri_bridge',
        group_chat_plus_plugin_name='atri_bridge', delegate_memory_to_livingmemory=True,
        delegate_reply_to_group_chat_plus=True, disable_local_memory_when_delegated=True,
        disable_local_reply_when_delegated=True)
    config['Self_Learning_Basic'].update(web_interface_host='127.0.0.1', web_interface_port=7833)
    config['V2_Architecture_Settings'].update(knowledge_engine='legacy', memory_engine='legacy')
    config['MaiBot_Enhancement']['enable_realtime_expression_learning'] = True
    config['Target_Settings']['target_qq_list'] = ['all']
    config['Storage_Settings']['data_dir'] = ''
    config['Database_Settings']['db_type'] = 'sqlite'
    return config


def defaults(schema):
    return {key: defaults(item['items']) if item.get('type') == 'object'
            else item.get('default') for key, item in schema.items()}


def install(source: Path, directory: Path, manifest: Path, *, plugin=PLUGIN, account=None,
            learning_provider=None):
    culture = plugin == CULTURE_PLUGIN
    if plugin not in (PLUGIN, CULTURE_PLUGIN):
        raise ValueError('Unreviewed plugin')
    if culture and (not str(account or '').isdecimal() or not int(account)):
        raise ValueError('Culture learning requires an explicit bot account')
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != (CULTURE_REVISION if culture else REVISION):
        raise ValueError('Plugin revision differs from reviewed revision')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Plugin checkout has local changes')
    settings = json.loads((directory / 'connection.json').read_text(encoding='utf-8-sig'))
    if host.process_state(directory=directory)['phase'] in {'running', 'starting'}:
        raise ValueError('Pause the ATRI-connected host before installing plugins')
    directory, manifest = directory.resolve(), manifest.resolve()
    data = directory / 'host/data'
    destination = data / 'plugins' / plugin
    if destination.exists():
        raise ValueError('Plugin already exists; review and update the canonical source while stopped')
    port = settings.get('capability_port', 8797)
    if host.listening(port):
        raise ValueError('Capability port occupied; no process will be stopped')
    cfg_path = data / 'cmd_config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
    bridge_path = data / 'config/astrbot_plugin_atri_bridge_config.json'
    bridge = json.loads(bridge_path.read_text(encoding='utf-8-sig'))
    plugin_cfg = data / 'config' / (plugin + '_config.json')
    if culture and plugin_cfg.exists():
        raise ValueError('Existing culture configuration requires manual compatibility review')
    config = None
    if not plugin_cfg.exists():
        schema = json.loads((source / '_conf_schema.json').read_text(encoding='utf-8'))
        config = culture_defaults(schema) if culture else defaults(schema)
        if not culture:
            config['default'].update(join_switch=False, join_min_level=0, join_max_time=0,
            join_accept_words=[], join_reject_words=[], custom_ban_words=[],
            word_ban_time=0, spamming_ban_time=0, builtin_ban=False,
            join_ban_time=0, leave_block=False, leave_notify=False, join_welcome='')
    enabled = cfg.setdefault('plugin_set', ['atri_bridge'])
    if enabled != ['*'] and plugin not in enabled:
        enabled.append(plugin)
    token = bridge.get('capability_token') or secrets.token_urlsafe(32)
    bridge.update(capability_port=port, capability_token=token)
    bridge.setdefault('shared_tools', [])
    if culture:
        if len(bridge.get('platform_ids', [])) != 1:
            raise ValueError('Culture learning requires one dedicated platform instance')
        bridge.update(culture_enabled=True, culture_account=str(account))
        if learning_provider:
            provider_id = learning_provider['id']
            if any(p.get('id') == provider_id for p in cfg.get('provider', [])):
                raise ValueError('Learning provider already exists')
            cfg.setdefault('provider', []).append(learning_provider)
            for key in ('filter_provider_id', 'refine_provider_id', 'reinforce_provider_id'):
                config['Model_Configuration'][key] = provider_id
    settings['capability_port'] = port
    owned_bridge = data / 'plugins' / host.PLUGIN
    bridge_sources = [p for p in host.bridge_source().iterdir()
                      if p.is_file() and p.suffix in {'.py', '.json', '.yaml'}]
    provenance = data / 'plugin_data/atri_bridge' / ('installed-self-learning.json' if culture else 'installed-qqadmin.json')
    # Keep a private recovery copy and restore every touched existing file on failure.
    recovery = plugin_layout.backup_directory(directory)
    recovery.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='culture-' if culture else 'qqadmin-', dir=recovery))
    if culture:
        # Offline SQLite backup includes AstrBot persona tables; originals remain untouched.
        import sqlite3
        for index, path in enumerate(data.glob('*.db')):
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as origin:
                with sqlite3.connect(backup / f'persona-{index}.db') as target:
                    origin.backup(target)
    paths = [cfg_path, bridge_path, directory / 'connection.json', manifest,
             plugin_cfg, provenance] + [owned_bridge / p.name for p in bridge_sources]
    saved = {}
    for index, path in enumerate(paths):
        saved[path] = path.read_bytes() if path.exists() else None
        if saved[path] is not None:
            (backup / str(index)).write_bytes(saved[path])
    host.atomic_json(backup / 'files.json', {str(i): str(p) for i, p in enumerate(paths)})
    created_code = None
    try:
        created_code = plugin_layout.deploy(source, directory, plugin)
        for file in bridge_sources:
            if file.resolve() != (owned_bridge / file.name).resolve():
                shutil.copy2(file, owned_bridge / file.name)
        if config is not None:
            host.atomic_json(plugin_cfg, config)
        host.atomic_json(cfg_path, cfg)
        host.atomic_json(bridge_path, bridge)
        host.atomic_json(directory / 'connection.json', settings)
        host.atomic_json(manifest, {'enabled': True, 'url': f'http://127.0.0.1:{port}', 'token': token})
        host.atomic_json(provenance,
            {'plugin': plugin, 'version': '4.4.3' if culture else '3.4.2', 'revision': revision,
             'repository': ('https://github.com/NickCharlie/astrbot_plugin_self_learning' if culture
                            else 'https://github.com/Zhalslar/astrbot_plugin_qqadmin')})
    except Exception:
        for path, content in saved.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        # This exact destination was absent at preflight and created by us.
        plugin_layout.rollback_deployment(directory, plugin, created_code)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--plugin', choices=[PLUGIN, CULTURE_PLUGIN], default=PLUGIN)
    parser.add_argument('--account')
    args = parser.parse_args()
    install(args.source, args.directory, args.manifest, plugin=args.plugin, account=args.account)
    print('Reviewed plugin installed. Restart the connected host to load.')


if __name__ == '__main__':
    main()
