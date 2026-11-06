"""System commit headroom for admission decisions.

视频链路会让 CPU 语音识别与视觉大模型同时驻留；两者都按提交内存（RAM +
分页文件）计费。这里只读系统状态，不分配、不改变任何进程。
"""
from __future__ import annotations

import os

# 实测：隔离的 SenseVoice CPU worker 仅加载模型就提交约 6.5 GB。
ASR_WORKER_COMMIT_BYTES = 7 * 1024**3


def available_commit_bytes() -> int | None:
    """可继续提交的字节数（RAM + 分页文件）；平台不支持时返回 ``None``。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPageFile)
    except (OSError, AttributeError, ValueError):
        return None
