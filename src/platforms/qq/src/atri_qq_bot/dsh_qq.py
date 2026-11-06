"""Explicit DSH account attachment; never inherits NapCat's account or profile."""
import json
from pathlib import Path
import re
import subprocess

from .snowluma_qq import SnowLumaQQ, _native_app, _running_exact, _ensure_program_integrity
from .snowluma_launcher import SnowLumaLauncher
from .snowluma_hook import SnowLumaHook


def target_account(root):
    try:
        settings = json.loads((Path(root).parent / 'QQ_Backends/DSH-QQ/desktop-launch.json').read_text(encoding='utf-8-sig'))
        account = str(settings.get('account', ''))
    except (OSError, ValueError, AttributeError) as error:
        raise ValueError('DSH 目标账号配置不可用；未使用其他 QQ 账号。') from error
    if not re.fullmatch(r'[0-9]{5,12}', account):
        raise ValueError('DSH 新账号配置无效；未使用 NapCat 账号。')
    return account


class DSHQQ:
    def __init__(self, root, *, service=None, hook=None, running=None, spawn=None, set_integrity=None):
        self.root = Path(root)
        self.service = service if service is not None else SnowLumaLauncher(root=self.root)
        self.hook = hook if hook is not None else SnowLumaHook(timeout=20)
        self.running = running or _running_exact
        self.spawn = spawn or subprocess.Popen
        self.set_integrity = set_integrity or _ensure_program_integrity

    def connect(self):
        settings = json.loads((self.root.parent / 'QQ_Backends/DSH-QQ/desktop-launch.json').read_text(encoding='utf-8-sig'))
        account = target_account(self.root)
        executable = Path(settings['qqExecutable']).resolve(strict=True)
        if executable.name.lower() != 'qq.exe':
            raise ValueError('DSH QQ 程序路径无效。')
        version = json.loads((executable.parent / 'versions/config.json').read_text(encoding='utf-8-sig'))['curVersion']
        if not re.fullmatch(r'[0-9]+(?:[.-][0-9]+)*', version):
            raise ValueError('DSH QQ 版本定位无效。')
        directory = executable.parent / 'versions' / version
        _native_app(directory)
        app = directory / 'resources/app'
        napcat = (self.root.parent / 'QQ_Backends/NapCat').resolve()
        old_client = (self.root / 'data/runtime/qq-snowluma/client').resolve()
        if executable.is_relative_to(napcat) or executable.is_relative_to(old_client) or (app / 'napcat').exists() or (executable.parent / 'NapCatHook.dll').exists():
            raise ValueError('DSH 不得挂载 NapCat 客户端，请检查独立 QQ 路径。')
        # The configured installation is a program source, never a process target.
        # In particular, -q does not isolate an already-running desktop QQ.
        client = SnowLumaQQ(root=self.root, source_loader=lambda: executable,
                            runtime_name='qq-dsh', account=account,
                            service=self.service, hook=self.hook, running=self.running,
                            spawn=self.spawn, set_integrity=self.set_integrity)
        client.prepare()
        return client.connect()
