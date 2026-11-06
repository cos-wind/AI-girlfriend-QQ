"""Load the installed SnowLuma hook into only our dedicated QQ main process.

Use the same native exports and existing-pipe adoption as SnowLuma 2.2.0.
No WebUI credentials, account operations, upstream patches or global autoload.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


_NATIVE = r'''
const fs = require('node:fs');
const path = require('node:path');
const source = process.argv[1];
const addon = require(path.join(source, 'native/snowluma-win32-x64.node'));
(async () => {
  const pids = await addon.getAllMainProcessAsync();
  const pid = Number(process.argv[2] || 0);
  if (!pid) { console.log(JSON.stringify(pids)); return; }
  if (!pids.includes(pid)) throw new Error('QQ main process disappeared');
  const pipe = `mojo.${pid}.control`;
  if (!fs.readdirSync('\\\\.\\pipe\\').includes(pipe)) {
    await addon.loadModuleManualAsync(pid, path.join(source, 'native/snowluma-win32-x64.dll'));
  }
  const deadline = Date.now() + 8000;
  while (!fs.readdirSync('\\\\.\\pipe\\').includes(pipe)) {
    if (Date.now() >= deadline) throw new Error('QQ control pipe not ready');
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  console.log(JSON.stringify({pid}));
})().catch(() => { process.exitCode = 1; });
'''


def _process_path(pid):
    from .napcat_session import launcher
    return launcher().process_executable_path(pid)


class SnowLumaHook:
    def __init__(self, *, run=None, process_path=None, timeout=8):
        self._run = run or subprocess.run
        self._path = process_path or _process_path
        self._timeout = timeout

    def _native(self, source: Path, pid=0):
        # Do not inherit dev/auth overrides or hooks from either QQ backend.
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(('NAPCAT_', 'SNOWLUMA_'))
               and k.upper() not in {'NODE_OPTIONS', 'NODE_PATH'}}
        try:
            result = self._run([str(source / 'node.exe'), '-e', _NATIVE, str(source), str(pid)],
                               cwd=str(source), env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               encoding='utf-8', check=True, timeout=12,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise ValueError('专用 QQ 自动挂载失败；保留登录，请重试或查看 SnowLuma 日志。') from error

    def attach(self, source: Path, executable: Path) -> int:
        for name in ('node.exe', 'native/snowluma-win32-x64.node', 'native/snowluma-win32-x64.dll'):
            if not (source / name).is_file():
                raise ValueError('SnowLuma 挂载组件不完整，未挂载任何 QQ。')
        target = os.path.normcase(str(executable.resolve()))
        deadline = time.monotonic() + self._timeout
        while True:
            pids = self._native(source)
            if not isinstance(pids, list) or any(type(pid) is not int or pid <= 0 for pid in pids):
                raise ValueError('SnowLuma 主进程列表异常，未挂载任何 QQ。')
            matches = []
            for pid in set(pids):
                path = self._path(pid)
                if path is not None and os.path.normcase(str(path.resolve())) == target:
                    matches.append(pid)
            if len(matches) > 1:
                raise ValueError('发现多个专用 QQ 主进程，未自动选择，请检查 SnowLuma 日志。')
            if matches:
                pid = matches[0]
                # Recheck immediately before native load; inaccessible processes
                # must never fall back to matching only a name or another QQ.
                path = self._path(pid)
                if path is None or os.path.normcase(str(path.resolve())) != target:
                    raise ValueError('专用 QQ 进程已变化，未挂载其他 QQ，请重试。')
                result = self._native(source, pid)
                if not isinstance(result, dict) or result.get('pid') != pid:
                    raise ValueError('专用 QQ 挂载回执异常，请查看 SnowLuma 日志。')
                return pid
            if time.monotonic() >= deadline:
                raise ValueError('专用 QQ 主进程尚未就绪，请点击“继续连接 QQ”重试；不会挂载普通 QQ。')
            time.sleep(0.3)
