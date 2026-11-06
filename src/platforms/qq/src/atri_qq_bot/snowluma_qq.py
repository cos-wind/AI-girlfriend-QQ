"""Explicit QQ login for SnowLuma, isolated from NapCat and desktop QQ."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from atrium_runtime import user_root


def _source_executable() -> Path:
    from .napcat_session import launcher
    # Only the explicitly configured project client. Never discover desktop QQ.
    value = launcher().project_env_value('QQ_EXE')
    if not value:
        raise ValueError('未配置项目专用 QQ，未使用普通桌面 QQ。')
    return Path(value.strip('"'))


def _running_exact(executable: Path) -> bool:
    from .napcat_session import launcher
    module = launcher()
    target = os.path.normcase(str(executable.resolve()))
    return any(path is not None and os.path.normcase(str(path.resolve())) == target
               for path in (module.process_executable_path(pid) for pid in module.pids_by_name('QQ.exe')))


def _native_app(version: Path) -> None:
    if not (version / 'QQNT.dll').is_file():
        raise ValueError('QQ 版本目录缺少 QQNT.dll，未启动不完整的客户端。')
    app = version / 'resources/app'
    package = json.loads((app / 'package.json').read_text(encoding='utf-8-sig'))
    if package.get('main') != './application.asar/app_launcher/index.js' or not (app / 'application.asar').exists():
        raise ValueError('项目 QQ 不是已知的原生入口，未修改原安装，请检查 QQ 版本。')


def _version_directory(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r'[0-9]+(?:[.-][0-9]+)*', name):
        raise ValueError('QQ 版本定位配置无效，请检查项目专用 QQ 安装。')
    version = directory / 'versions' / name
    if version.is_symlink() or getattr(version.lstat(), 'st_file_attributes', 0) & 0x400:
        raise ValueError('QQ 版本目录存在链接，未复制或修改链接目标。')
    return version


def _ensure_launcher_config(directory: Path, version: Path) -> None:
    """QQ.exe needs this index to locate QQNT.dll; a version folder alone is insufficient."""
    config = directory / 'versions/config.json'
    if config.exists():
        current = json.loads(config.read_text(encoding='utf-8-sig'))
        if current.get('curVersion') != version.name or current.get('baseVersion') != version.name:
            raise ValueError('SnowLuma 专用 QQ 的版本定位与程序不一致，请检查安装。')
        return
    # Recreate only the program index omitted by older copies, never login data.
    value = {'baseVersion': version.name, 'curVersion': version.name,
             'prevVersion': '', 'onErrorVersions': [],
             'buildId': version.name.rsplit('-', 1)[-1], 'unzipRetryCount': 0}
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=config.parent,
                                     prefix='config-', suffix='.tmp', delete=False) as file:
        temporary = Path(file.name)
        json.dump(value, file)
    try:
        temporary.replace(config)
    finally:
        temporary.unlink(missing_ok=True)


def _ignore_hooks(directory, names):
    excluded = set()
    for name in names:
        lower = name.lower()
        if lower.startswith('napcat') or lower == 'dbghelp.dll' or lower.endswith(('.log', '.bak')):
            excluded.add(name)
            continue
        path = Path(directory) / name
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('QQ 安装中存在目录链接，未复制或修改链接目标。')
    return excluded


def _ensure_program_integrity(directory: Path) -> None:
    """Chromium refuses Low-labelled DLLs in its GPU sandbox. Keep that policy on."""
    if os.name != 'nt':
        return
    for path in (directory, *directory.rglob('*')):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('专用 QQ 程序目录存在链接，未调整链接目标的标签。')
    try:
        # Only the isolated program tree: no DACL changes, profile, or source QQ.
        subprocess.run(['icacls', str(directory), '/setintegritylevel', '(OI)(CI)M'],
                       check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError('专用 QQ 程序完整性标签设置失败，未启动 QQ。') from error


class SnowLumaQQ:
    """Explicit dedicated-client connection; never log out or migrate profiles."""

    def __init__(self, *, root=None, source_loader=None, spawn=None, running=None, set_integrity=None,
                 service=None, hook=None, runtime_name='qq-snowluma', account=None):
        root = Path(root) if root is not None else user_root()
        if runtime_name not in {'qq-snowluma', 'qq-dsh'}:
            raise ValueError('专用 QQ 运行目录无效。')
        self.directory = root / 'data/runtime' / runtime_name / 'client'
        self.profile = self.directory.parent / 'qq-profile'
        self._account = account
        self._source_loader = source_loader or _source_executable
        self._spawn = spawn or subprocess.Popen
        self._running = running or _running_exact
        self._set_integrity = set_integrity or _ensure_program_integrity
        self._integrity_ready = False
        self._process = None
        from .snowluma_launcher import SnowLumaLauncher
        from .snowluma_hook import SnowLumaHook
        self._service = service if service is not None else SnowLumaLauncher(root=root)
        self._hook = hook if hook is not None else SnowLumaHook()

    def connect(self) -> str:
        """One explicit action owns service startup, QQ reuse and targeted load."""
        self._service.start()
        self.open()
        source, _ = self._service._paths()
        self._hook.attach(source, self.directory / 'QQ.exe')
        return '专用 QQ 已自动挂载，等待 QQ 登录及通道确认；如需认证，请在专用 QQ 窗口完成。'

    def prepare(self) -> Path:
        executable = self._prepare_files()
        if not self._integrity_ready:
            self._set_integrity(self.directory)
            self._integrity_ready = True
        return executable

    def _prepare_files(self) -> Path:
        for path in (self.directory.parent, self.directory, self.profile):
            if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('专用 QQ 程序或登录目录存在链接，未复用或挂载其他 QQ。')
        executable = self.directory / 'QQ.exe'
        if self.directory.exists():
            marker = json.loads((self.directory / '.atri-client.json').read_text(encoding='utf-8'))
            version = _version_directory(self.directory, marker['version'])
            if not executable.is_file():
                raise ValueError('SnowLuma 专用 QQ 安装不完整，未触碰原 QQ。')
            _native_app(version)
            if (version / 'resources/app/dbghelp.dll').exists() or (version / 'resources/app/napcat').exists():
                raise ValueError('SnowLuma 专用 QQ 出现其他注入文件，请检查安装。')
            _ensure_launcher_config(self.directory, version)
            return executable
        source = self._source_loader().resolve(strict=True)
        if source.name.lower() != 'qq.exe':
            raise ValueError('项目专用 QQ 路径无效。')
        config = json.loads((source.parent / 'versions/config.json').read_text(encoding='utf-8-sig'))
        version = _version_directory(source.parent, config.get('curVersion'))
        _native_app(version)
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a complete copy; never edit, link or delete source files.
        with tempfile.TemporaryDirectory(prefix='client-prepare-', dir=self.directory.parent) as temporary:
            staging = Path(temporary) / 'client'
            staging.mkdir()
            for file in source.parent.iterdir():
                lower = file.name.lower()
                if file.is_file() and (lower in {'qq.exe', 'qqex.exe'} or
                        lower.endswith('.dll') and lower.startswith(('api-ms-', 'msvc', 'vcruntime', 'ucrtbase', 'vcomp', 'qq_shell_extension'))):
                    if file.is_symlink() or getattr(file.lstat(), 'st_file_attributes', 0) & 0x400:
                        raise ValueError('QQ 安装中存在文件链接，未复制链接目标。')
                    shutil.copy2(file, staging / file.name)
            shutil.copytree(version, staging / 'versions' / version.name, ignore=_ignore_hooks)
            _ensure_launcher_config(staging, staging / 'versions' / version.name)
            (staging / '.atri-client.json').write_text(json.dumps({'version': version.name}), encoding='utf-8')
            staging.replace(self.directory)
        return executable

    def open(self) -> str:
        executable = self.prepare()
        if (self._process is not None and self._process.poll() is None) or self._running(executable):
            return 'SnowLuma 专用 QQ 已在运行，保留当前登录。'
        self.profile.mkdir(parents=True, exist_ok=True)
        environment = {k: v for k, v in os.environ.items()
                       if not k.upper().startswith(('NAPCAT_', 'SNOWLUMA_'))
                       and k.upper() not in {'NODE_OPTIONS', 'NODE_PATH'}}
        self._process = self._spawn(
            self._launch_arguments(executable), cwd=str(self.directory),
            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if self._process.poll() is not None and self._process.returncode:
            raise ValueError('专用 QQ 启动失败，未改动原 QQ 账号。')
        # The host backgrounds QQ only after a fresh online observation.
        # A process/attachment receipt cannot establish authentication.
        return 'SnowLuma 专用 QQ 已启动，等待登录及通道确认。'

    def _launch_arguments(self, executable: Path) -> list[str]:
        """保留目标账号参数与独立 profile；参数不保证官方 QQ 自动登录。

        NapCat 会主动调用快速登录接口，SnowLuma 挂载不能等同该行为。
        账号只取显式绑定或本实例文件，禁止继承 NapCat / BOT_QQ。
        """
        arguments = [str(executable)]
        uin = self._target_uin()
        if uin:
            arguments.extend(['-q', uin])
        arguments.append(f'--user-data-dir={self.profile.resolve()}')
        return arguments

    def _target_uin(self) -> str:
        if self._account is not None:
            raw = str(self._account).strip()
        else:
            try:
                raw = (self.directory.parent / 'quick-account.txt').read_text(
                    encoding='utf-8', errors='replace').strip()
            except OSError:
                raw = ''
        if not raw or raw.casefold() in {'off', 'manual', 'none', '-'}:
            return ''
        if not re.fullmatch(r'[0-9]{5,12}', raw):
            raise ValueError('专用 QQ 账号绑定无效，未使用其他后端账号。')
        return raw

