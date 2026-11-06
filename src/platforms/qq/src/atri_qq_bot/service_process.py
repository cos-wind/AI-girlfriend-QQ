"""Stop one verified backend installation, including after a desktop restart.

Never select by image name or kill the owner of an unverified port. Windows
handles pin identity while terminating, so PID reuse cannot target a new process.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from atri_shared.runtime.process import run_hidden, tcp_rows


def process_inventory() -> list[dict]:
    if os.name != 'nt':
        raise ValueError('当前后端启停仅支持 Windows。')
    result = run_hidden(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
        "@(Get-CimInstance Win32_Process -ErrorAction Stop | "
        "Select-Object @{n='pid';e={$_.ProcessId}},@{n='parent';e={$_.ParentProcessId}},"
        "@{n='exe';e={$_.ExecutablePath}},@{n='command';e={$_.CommandLine}},"
        "@{n='created';e={if ($_.CreationDate) {$_.CreationDate.ToFileTimeUtc().ToString()} else {'0'}}}) | ConvertTo-Json -Compress"], timeout=12)
    if result.returncode:
        raise ValueError('无法核验后端进程，未关闭任何程序，请重试。')
    rows = json.loads(result.stdout.decode('utf-8-sig') or '[]')
    return rows if isinstance(rows, list) else [rows]


def _arguments(command: str) -> list[str]:
    count = ctypes.c_int()
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    argv = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not argv:
        return []
    try:
        return [argv[index] for index in range(count.value)]
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel.LocalFree(ctypes.cast(argv, wintypes.HLOCAL))


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def _terminate_verified(row: dict) -> None:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x0001 | 0x00100000, False, int(row['pid']))
    if not handle:
        if ctypes.get_last_error() == 87:  # Already exited.
            return
        raise ValueError('没有权限关闭该后端进程，请使用原启动方式关闭。')
    try:
        buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) or not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            # Stopping a supervisor can make its children exit after census.
            # Only the pinned handle's exit signal proves this race is benign.
            if kernel.WaitForSingleObject(handle, 0) == 0:
                return
            raise ValueError('无法再次核验进程身份，未关闭该进程。')
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        # CIM CreationDate (DMTF) truncates to microseconds; native FILETIME
        # retains 100 ns ticks. Compare at the census precision, using integers
        # to avoid losing low bits of the large FILETIME value to floats.
        if created // 10 != int(row['created']) // 10 or not _same_path(buffer.value, row['exe']):
            raise ValueError('后端进程已变化，请刷新后重试。')
        if not kernel.TerminateProcess(handle, 0):
            if kernel.WaitForSingleObject(handle, 0) == 0:
                return
            raise ValueError('后端关闭失败，请查看原启动日志。')
        if kernel.WaitForSingleObject(handle, 5000) != 0:
            raise ValueError('后端尚未退出，请稍后刷新确认。')
    finally:
        kernel.CloseHandle(handle)


def stop_entry(entry: Path, *, port: int, process=None, standalone=False,
               wrapper: Path | None = None, required_args: tuple[str, ...] = ()) -> None:
    _stop_entry(entry, port=port, process=process, standalone=standalone,
                wrapper=wrapper, required_args=required_args, rows=process_inventory())


def stop_entries(entries, *, inventory=None) -> None:
    """One lifecycle transaction, one census; native handles still pin every exit.

    A PowerShell caller may pass its fresh CIM snapshot over stdin, avoiding a
    nested PowerShell. Never persist or reuse this snapshot across operations.
    """
    rows = process_inventory() if inventory is None else inventory
    for entry, options in entries:
        _stop_entry(entry, rows=rows, **options)


def _stop_entry(entry, *, rows, port, process=None, standalone=False,
                wrapper=None, required_args=()):
    by_pid = {int(row['pid']): row for row in rows}

    def ancestors(row):
        visited = set()
        while int(row.get('parent', 0)) in by_pid:
            parent = by_pid[int(row['parent'])]
            if parent['pid'] in visited or int(parent['created']) > int(row['created']):
                break
            visited.add(parent['pid'])
            yield parent
            row = parent

    allowed = {'python.exe', 'pythonw.exe', 'node.exe', 'powershell.exe', 'pwsh.exe'}
    matches = []
    for row in rows:
        if not row.get('exe') or Path(row['exe']).name.lower() not in allowed:
            continue
        args = _arguments(row.get('command') or '')
        direct = len(args) > 1 and Path(args[1]).is_absolute() and _same_path(args[1], entry)
        script = wrapper is not None and any(args[index].lower() == '-file' and
            _same_path(args[index + 1], wrapper) for index in range(1, len(args) - 1))
        if required_args and not any(tuple(args[i:i + len(required_args)]) == required_args
                                     for i in range(2, len(args))):
            continue
        if direct or script:
            # The managed ATRI instance shares main.py with standalone AstrBot.
            if standalone and any('atri_qq_bot.qq_astrbot' in (item.get('command') or '')
                                  for item in ancestors(row)):
                continue
            matches.append(row)
    if standalone:
        candidates = matches
        owners = {int(row['pid']) for row in tcp_rows()
                  if row['state'] == 'LISTENING' and row['local_port'] == port}
        owned = getattr(process, 'pid', None) if process is not None and process.poll() is None else None
        matches = [row for row in matches if row['pid'] == owned or any(
            listener in by_pid and (listener == row['pid'] or row in ancestors(by_pid[listener]))
            for listener in owners)]
        if not matches and (owners or candidates):
            raise ValueError('端口进程未确认为独立 AstrBot，未关闭任何程序。')
    targets = {int(row['pid']): row for row in matches}
    for row in rows:
        if row.get('exe') and Path(row['exe']).name.lower() in allowed and any(
                int(parent['pid']) in targets for parent in ancestors(row)):
            targets[int(row['pid'])] = row
    # Parents first prevents supervisors from recreating their children.
    for row in sorted(targets.values(), key=lambda item: int(item['created'])):
        _terminate_verified(row)
