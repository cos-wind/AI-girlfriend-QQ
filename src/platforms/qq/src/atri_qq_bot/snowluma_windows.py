"""Background only the dedicated client after a fresh QQ online observation.

Never hide the login screen while offline, close a window/process, or keep
fighting a user who reopens QQ from its tray. State queries remain read-only.
"""
from __future__ import annotations

import os
from pathlib import Path


def _window_api():
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]

    def windows():
        result = []
        def collect(hwnd, _):
            if api.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                result.append((hwnd, pid.value))
            return True
        api.EnumWindows(callback_type(collect), 0)
        return result

    return windows, lambda hwnd: api.ShowWindowAsync(hwnd, 0)  # SW_HIDE, never WM_CLOSE


def hide_client_windows(executable: Path, *, windows=None, process_path=None, hide=None) -> bool:
    if windows is None or hide is None:
        if os.name != 'nt':
            return False
        windows, hide = _window_api()
    if process_path is None:
        from .napcat_session import launcher
        process_path = launcher().process_executable_path
    target = os.path.normcase(str(executable.resolve()))
    hidden = False
    for hwnd, pid in windows():
        path = process_path(pid)
        if path is not None and os.path.normcase(str(path.resolve())) == target:
            # Include dedicated renderers/popups; never match QQ.exe by name.
            hide(hwnd)
            hidden = True
    return hidden


class QQBackground:
    def __init__(self, executable: Path, *, hide=None):
        self.executable = executable
        self._hide = hide or hide_client_windows
        self._hidden = False

    def update(self, online: bool) -> None:
        if not online:
            self._hidden = False
        elif not self._hidden:
            try:
                self._hidden = self._hide(self.executable)
            except OSError:
                # Visibility cannot kill the core/host or change login state.
                pass
