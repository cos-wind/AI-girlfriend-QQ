"""Pinned QQ Space installation; live hosts activate on their next explicit start."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .backend_isolation import transition
from .plugin_install import defaults
from .plugin_layout import junction
from .qq_astrbot import atomic_json

PLUGIN = 'astrbot_plugin_qzone'
REVISION = '0f5720f78d7bba45d94778580397e08fcfd02570'
BINDING = 'astrbot_plugin_atri_qzone_binding'


def enable_dual_accounts(root):
    """Explicit, backed-up upgrade; reload only the binding plugin afterwards."""
    root = Path(root)
    manifest = json.loads((root / 'data/plugins/astrbot/shared/ingress.json').read_text(encoding='utf-8'))
    if manifest.get('host') != 'atri':
        raise ValueError('QQ Space requires the unified host')
    accounts = {key: str(manifest[key]['account']) for key in ('dsh', 'napcat')}
    if any(not value.isdigit() for value in accounts.values()) or accounts['dsh'] == accounts['napcat']:
        raise ValueError('QQ Space requires two distinct bound accounts')
    path = root / 'data/plugins/astrbot/atri/config' / (BINDING + '_config.json')
    before = path.read_bytes()
    value = json.loads(before.decode('utf-8-sig'))
    if value.get('platform_id') != 'atri-plugin-dsh' or str(value.get('account')) != accounts['dsh']:
        raise ValueError('Existing QQ Space binding differs; refusing account change')
    bindings = ['atri-plugin-' + key + '=' + account for key, account in accounts.items()]
    if value.get('accounts') and value['accounts'] != bindings:
        raise ValueError('Existing QQ Space secondary binding differs')
    if value.get('accounts') == bindings:
        return False
    backup_root = root / 'dev/workspace/backups/plugin-installs/astrbot-atri'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='qzone-dual-', dir=backup_root))
    (backup / path.name).write_bytes(before)
    value['accounts'] = bindings
    atomic_json(path, value)
    return True



def assign_to_napcat(root, *, probe=None):
    """Explicit offline migration: promote NapCat data, archive old DSH data."""
    from .astrbot_launcher import _port_open
    root = Path(root).resolve()
    if any((probe or _port_open)(p) for p in (6186, 6281, 6282)):
        raise RuntimeError('Stop only the unified plugin host before changing Space scope')
    manifest = json.loads((root / 'data/plugins/astrbot/shared/ingress.json').read_text(encoding='utf-8'))
    if manifest.get('host') != 'atri':
        raise ValueError('Unified plugin host required')
    accounts = {key: str(manifest[key]['account']) for key in ('dsh', 'napcat')}
    if not all(v.isdigit() for v in accounts.values()) or accounts['dsh'] == accounts['napcat']:
        raise ValueError('Distinct verified accounts required')
    config = root / 'data/plugins/astrbot/atri/config'
    binding = config / (BINDING + '_config.json')
    current = json.loads(binding.read_text(encoding='utf-8-sig'))
    target = 'atri-plugin-napcat'
    expected = target + '=' + accounts['napcat']
    if current.get('platform_id') == target and str(current.get('account')) == accounts['napcat']:
        if current.get('accounts') == [expected] and current.get('active_platforms') == [target]:
            return False
        raise ValueError('Unexpected existing NapCat binding')
    if current.get('platform_id') != 'atri-plugin-dsh' or str(current.get('account')) != accounts['dsh']:
        raise ValueError('Existing primary account differs')
    if set(current.get('accounts', [])) != {'atri-plugin-' + k + '=' + v for k, v in accounts.items()}:
        raise ValueError('Existing secondary accounts differ')
    primary = config / (PLUGIN + '_config.json')
    secondary = config / 'atri_qzone_atri-plugin-napcat_config.json'
    napcat_config = json.loads(secondary.read_text(encoding='utf-8-sig'))
    storage = (root / 'data/plugins/astrbot/atri/storage' / PLUGIN).resolve()
    if not storage.is_relative_to(root) or not storage.is_dir():
        raise ValueError('Space storage must be inside the workspace')
    napcat_storage = storage / 'accounts' / (target + '-' + accounts['napcat'])
    if not (napcat_storage / 'posts_5.db').is_file():
        raise ValueError('Existing NapCat draft database required')
    backup_root = root / 'dev/workspace/backups/plugin-installs/astrbot-atri'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='qzone-napcat-only-', dir=backup_root)).resolve()
    if not backup.is_relative_to(root):
        raise ValueError('Backup must stay inside workspace')
    saved = {p: p.read_bytes() for p in (binding, primary, secondary)}
    for path, content in saved.items():
        (backup / path.name).write_bytes(content)
    # Copy only NapCat state to a fresh primary directory; preserve DSH intact.
    staged = backup / 'napcat-storage'
    shutil.copytree(napcat_storage, staged)
    current.update(platform_id=target, account=accounts['napcat'],
                   accounts=[expected], active_platforms=[target])
    current.setdefault('autonomy', {}).setdefault('dsh', {})['enabled'] = False
    moved = False
    try:
        storage.rename(backup / 'previous-storage')
        moved = True
        staged.rename(storage)
        atomic_json(primary, napcat_config)
        atomic_json(binding, current)
        secondary.rename(backup / 'retired-secondary-config.json')
    except BaseException:
        for path, content in saved.items():
            path.write_bytes(content)
        if moved:
            if storage.exists():
                storage.rename(backup / 'failed-new-storage')
            (backup / 'previous-storage').rename(storage)
        raise
    atomic_json(backup / 'verification.json', {'scope': 'napcat-only', 'dsh_archived': True})
    return True


def runtime(root):
    return Path(root) / 'dev/workspace/runtimes/astrbot-atri'


def canonical(root):
    return Path(root) / 'src/platforms/qq/plugins/astrbot/third_party' / PLUGIN


def initial_config(source):
    config = defaults(json.loads((source / '_conf_schema.json').read_text(encoding='utf-8')))
    config['manage_group'] = ''
    config['trigger'].update(publish_cron='', comment_cron='', read_prob=0,
                             like_when_comment=False)
    return config


def snapshot(source):
    return {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob('*') if p.is_file() and '.git' not in p.parts
            and '__pycache__' not in p.parts and p.name != 'ATRI-UPSTREAM.json'}


def check_source(source):
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
    if revision != REVISION or dirty:
        raise ValueError('QQ Space requires the clean reviewed upstream revision')


def apply_pending(root):
    """Apply before host startup, with all host listeners stopped."""
    root = Path(root)
    state = root / 'data/plugins/astrbot/atri'
    pending = state / 'pending-qzone.json'
    if not pending.exists():
        return False
    request = json.loads(pending.read_text(encoding='utf-8'))
    if request.get('revision') != REVISION or not str(request.get('account', '')).isdigit():
        raise ValueError('Unreviewed pending QQ Space installation')
    manifest = json.loads((root / 'data/plugins/astrbot/shared/ingress.json').read_text(encoding='utf-8'))
    if manifest.get('host') != 'atri' or str(manifest['dsh']['account']) != str(request['account']):
        raise ValueError('QQ Space requires the reviewed unified SnowLuma binding')
    source = canonical(root)
    receipt = json.loads((source / 'ATRI-UPSTREAM.json').read_text(encoding='utf-8'))
    if receipt.get('revision') != REVISION or receipt.get('files') != snapshot(source):
        raise ValueError('QQ Space source differs from reviewed installation')
    data = runtime(root) / 'host/data'
    config_path = data / 'cmd_config.json'
    plugin_config = state / 'config' / (PLUGIN + '_config.json')
    entry = data / 'plugins' / PLUGIN
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    def enable(config):
        enabled = config.setdefault('plugin_set', ['atri_bridge'])
        if enabled != ['*']:
            for plugin in ('atri_qzone_binding', PLUGIN):
                if plugin not in enabled:
                    enabled.append(plugin)
    enable(config)
    profiles = list((data / 'config').glob('abconf_*.json'))
    updates = {config_path: config}
    for path in profiles:
        profile = json.loads(path.read_text(encoding='utf-8-sig'))
        enable(profile)
        updates[path] = profile
    binding_config = state / 'config' / (BINDING + '_config.json')
    binding_value = {'platform_id': 'atri-plugin-dsh', 'account': request['account']}
    if binding_config.exists():
        existing = json.loads(binding_config.read_text(encoding='utf-8-sig'))
        napcat_only = (existing.get('platform_id') == 'atri-plugin-napcat'
                       and str(existing.get('account')) == str(manifest['napcat']['account'])
                       and existing.get('accounts') == ['atri-plugin-napcat=' + str(manifest['napcat']['account'])]
                       and existing.get('active_platforms') == ['atri-plugin-napcat'])
        if not napcat_only and any(existing.get(k) != v for k, v in binding_value.items()):
            raise ValueError('Existing QQ Space binding differs; refusing account change')
        expected = {'atri-plugin-' + key + '=' + str(manifest[key]['account']) for key in ('dsh', 'napcat')}
        if not set(existing.get('accounts', [])).issubset(expected):
            raise ValueError('Existing QQ Space secondary binding differs')
        binding_value = existing
    updates[binding_config] = binding_value
    backup_root = root / 'dev/workspace/backups/plugin-installs/astrbot-atri'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='qzone-', dir=backup_root))
    saved = {p: p.read_bytes() if p.exists() else None for p in (*updates, plugin_config)}
    for i, (path, content) in enumerate(saved.items()):
        if content is not None:
            (backup / str(i)).write_bytes(content)
    atomic_json(backup / 'files.json', {str(i): str(p) for i, p in enumerate(saved)})
    binding_entry = data / 'plugins' / BINDING
    entries = {p: os.path.lexists(p) for p in (entry, binding_entry)}
    try:
        junction(entry, source)
        junction(binding_entry, root / 'src/platforms/qq/plugins/astrbot/maintained' / BINDING)
        if not plugin_config.exists():
            atomic_json(plugin_config, initial_config(source))
        for path, value in updates.items():
            atomic_json(path, value)
        pending.unlink()
    except BaseException:
        for path, content in saved.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        for entry, existed in entries.items():
            if not existed and os.path.lexists(entry):
                if os.name == 'nt':
                    os.rmdir(entry)
                else:
                    entry.unlink()
        raise
    return True


def install(root, source, *, probe=None):
    from .astrbot_launcher import _port_open
    root, source = Path(root), Path(source)
    check_source(source)
    manifest = json.loads((root / 'data/plugins/astrbot/shared/ingress.json').read_text(encoding='utf-8'))
    account = str(manifest['dsh']['account'])
    target = canonical(root)
    files = snapshot(source)
    if target.exists():
        receipt = json.loads((target / 'ATRI-UPSTREAM.json').read_text(encoding='utf-8'))
        if receipt.get('revision') != REVISION or files != snapshot(target):
            raise ValueError('Existing QQ Space source will not be overwritten')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.qzone-install-', dir=target.parent))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('.git', '__pycache__'))
            atomic_json(staging / 'ATRI-UPSTREAM.json', {'repo': 'https://github.com/Zhalslar/astrbot_plugin_qzone',
                        'version': '3.1.3', 'revision': REVISION, 'files': files})
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    with transition(root / 'data/runtime', name='plugin-host-shared.lock'):
        state = root / 'data/plugins/astrbot/atri'
        atomic_json(state / 'pending-qzone.json', {'revision': REVISION, 'account': account})
        if manifest.get('host') != 'atri' or any((probe or _port_open)(port) for port in (6186, 6281, 6282)):
            return 'pending-next-unified-host-start'
        apply_pending(root)
        return 'installed-host-stopped'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.root, args.source)))


if __name__ == '__main__':
    main()
