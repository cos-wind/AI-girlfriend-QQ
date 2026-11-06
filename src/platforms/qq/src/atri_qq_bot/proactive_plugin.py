"""Install the reviewed proactive plugin without taking over ATRI scheduling."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from . import qq_astrbot as host
from . import plugin_layout

PLUGIN = 'astrbot_plugin_proactive_chat'
REVISION = '635fc18eeb84e3c7b58661425359244552286835'
VERSION = '1.2.6'
REPOSITORY = 'https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat'


def trial_defaults(schema):
    """Empty recipient lists: installation must never start a second sender."""
    from .plugin_install import defaults
    config = defaults(schema)
    for key in ('friend_settings', 'group_settings'):
        config[key]['enable'] = False
        config[key]['session_list'] = []
        config[key]['tts_settings']['enable_tts'] = False
    for key in ('web_admin', 'notification_settings', 'telemetry_config'):
        config[key]['enabled'] = False
    return config


def install(source: Path, directory: Path):
    source, directory = source.resolve(), directory.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise ValueError('Plugin revision differs from reviewed v1.2.6')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Plugin checkout has local changes')
    if host.process_state(directory=directory)['phase'] in {'running', 'starting'}:
        raise ValueError('Pause the ATRI-connected host before installing')
    settings = json.loads((directory / 'connection.json').read_text(encoding='utf-8-sig'))
    if any(host.listening(settings[key]) for key in host.service_ports(settings)):
        raise ValueError('Connected host ports are still occupied')
    data = directory / 'host/data'
    destination = data / 'plugins' / PLUGIN
    config_path = data / 'config' / f'{PLUGIN}_config.json'
    if destination.exists() or config_path.exists():
        raise ValueError('Plugin or configuration already exists; refuse to overwrite')
    cmd_path = data / 'cmd_config.json'
    original = cmd_path.read_bytes()
    cmd = json.loads(original.decode('utf-8-sig'))
    enabled = cmd.setdefault('plugin_set', ['atri_bridge'])
    if enabled != ['*'] and PLUGIN not in enabled:
        enabled.append(PLUGIN)
    schema = json.loads((source / '_conf_schema.json').read_text(encoding='utf-8'))
    config = trial_defaults(schema)
    recovery = plugin_layout.backup_directory(directory)
    recovery.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='proactive-', dir=recovery))
    (backup / 'cmd_config.json').write_bytes(original)
    provenance = data / 'plugin_data/atri_bridge/installed-proactive.json'
    if provenance.exists():
        raise ValueError('Installation receipt already exists')
    created_code = None
    try:
        created_code = plugin_layout.deploy(source, directory, PLUGIN)
        host.atomic_json(config_path, config)
        host.atomic_json(cmd_path, cmd)
        host.atomic_json(provenance, dict(plugin=PLUGIN, version=VERSION,
                                         revision=REVISION, repository=REPOSITORY))
    except BaseException:
        cmd_path.write_bytes(original)
        config_path.unlink(missing_ok=True)
        provenance.unlink(missing_ok=True)
        # Only this newly created, verified plugin directory is ours to remove.
        plugin_layout.rollback_deployment(directory, PLUGIN, created_code)
        raise
    return destination
