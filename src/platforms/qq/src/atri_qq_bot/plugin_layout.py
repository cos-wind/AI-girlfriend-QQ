"""Canonical plugin code, private state and host loading entries.

Only the managed ATRI instance uses the workspace layout. Explicit temporary
instances remain self-contained, including installed-package tests.
"""
from pathlib import Path
import os
import shutil
import subprocess

from atrium_runtime import user_root


def runtime_directory() -> Path:
    return user_root() / 'dev/workspace/runtimes/astrbot-atri'


def managed(directory: Path) -> bool:
    return directory.resolve() == runtime_directory().resolve()


def junction(entry: Path, target: Path) -> None:
    """Never replace an existing directory or silently accept a wrong link."""
    target = target.resolve(strict=True)
    if os.path.lexists(entry):
        if entry.resolve() != target:
            raise ValueError(f'Loading entry already exists: {entry}')
        return
    entry.parent.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        # PowerShell -Command reparses native arguments. Quote literal paths
        # explicitly (including embedded apostrophes), and make errors fatal.
        literal = lambda path: "'" + str(path).replace("'", "''") + "'"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                        'New-Item -ErrorAction Stop -ItemType Junction -Path ' + literal(entry)
                        + ' -Target ' + literal(target) + ' | Out-Null'],
                       check=True, capture_output=True)
    else:
        entry.symlink_to(target, target_is_directory=True)
    if entry.resolve() != target:
        raise OSError(f'Loading entry did not resolve to its target: {entry}')


def prepare_state(directory: Path) -> None:
    if not managed(directory):
        return
    state = user_root() / 'data/plugins/astrbot/atri'
    for name, folder in (('config', 'config'), ('plugin_data', 'storage')):
        target = state / folder
        target.mkdir(parents=True, exist_ok=True)
        junction(directory / 'host/data' / name, target)


def backup_directory(directory: Path) -> Path:
    if managed(directory):
        return user_root() / 'dev/workspace/backups/plugin-installs/astrbot-atri'
    return directory / 'install-backups'


def deploy(source: Path, directory: Path, plugin: str, *, maintained=False) -> Path | None:
    """Return newly created canonical code for transaction rollback, if any."""
    destination = directory / 'host/data/plugins' / plugin
    if not managed(directory):
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        return None
    created = None
    target = source
    if not maintained:
        target = user_root() / 'src/platforms/qq/plugins/astrbot/third_party' / plugin
        if not target.exists():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            created = target
        else:
            raise ValueError('Canonical plugin already exists; review updates before replacing it')
    try:
        junction(destination, target)
    except BaseException:
        if created:
            shutil.rmtree(created)
        raise
    return created


def rollback_deployment(directory: Path, plugin: str, created: Path | None) -> None:
    destination = directory / 'host/data/plugins' / plugin
    if managed(directory):
        if os.path.lexists(destination):
            # rmdir removes the junction itself; it does not traverse the target.
            if destination.resolve() == destination.absolute():
                raise ValueError('Refuse to remove a physical managed loading directory')
            if os.name == 'nt':
                os.rmdir(destination)
            else:
                destination.unlink()
        expected = user_root() / 'src/platforms/qq/plugins/astrbot/third_party' / plugin
        if created is not None and created.resolve() == expected.resolve():
            shutil.rmtree(created)
    elif destination.exists() and destination.resolve().parent == (directory / 'host/data/plugins').resolve():
        shutil.rmtree(destination)
