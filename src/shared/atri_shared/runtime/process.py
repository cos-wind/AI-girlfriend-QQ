"""Hidden process execution and local TCP inspection; no platform dependencies."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import socket
import subprocess
from typing import Any

def hidden_subprocess_startupinfo() -> Any | None:
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = 0
    return startupinfo


def run_hidden(
    command: list[str],
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """运行隐藏命令；可选超时避免控制面板被系统命令永久卡住。"""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=hidden_subprocess_startupinfo(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=exc.stdout or b"",
            stderr=(exc.stderr or b"hidden command timed out").encode()
            if isinstance(exc.stderr, str)
            else (exc.stderr or b"hidden command timed out"),
        )


def is_port_listening(port: int) -> bool:
    return _is_port_listening(tcp_rows(), port)


def has_established_port(port: int) -> bool:
    return _has_established_port(tcp_rows(), port)


def _is_port_listening(rows: list[dict[str, int | str | None]], port: int) -> bool:
    return any(row["local_port"] == port and row["state"] == "LISTENING" for row in rows)


def _has_established_port(rows: list[dict[str, int | str | None]], port: int) -> bool:
    return any(
        row["state"] == "ESTABLISHED" and (row["local_port"] == port or row["remote_port"] == port)
        for row in rows
    )


def tcp_rows() -> list[dict[str, int | str | None]]:
    if os.name != "nt":
        return []
    return _windows_tcp_rows()


class _MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("state", wintypes.DWORD),
        ("local_address", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("remote_address", wintypes.DWORD),
        ("remote_port", wintypes.DWORD),
        ("pid", wintypes.DWORD),
    ]


_TCP_STATES = {
    1: "CLOSED",
    2: "LISTENING",
    3: "SYN_SENT",
    4: "SYN_RECEIVED",
    5: "ESTABLISHED",
    6: "FIN_WAIT_1",
    7: "FIN_WAIT_2",
    8: "CLOSE_WAIT",
    9: "CLOSING",
    10: "LAST_ACK",
    11: "TIME_WAIT",
    12: "DELETE_TCB",
}


def _windows_tcp_rows() -> list[dict[str, int | str | None]]:
    get_table = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD

    size = wintypes.DWORD(0)
    # AF_INET + TCP_TABLE_OWNER_PID_ALL. The table can grow between the size
    # probe and read, so retry a bounded number of times.
    result = get_table(None, ctypes.byref(size), False, socket.AF_INET, 5, 0)
    if result not in {0, 122} or size.value <= 0:
        return []
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = get_table(buffer, ctypes.byref(size), False, socket.AF_INET, 5, 0)
        if result == 122:
            continue
        if result != 0:
            return []
        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        if count == 0:
            return []
        row_array = ctypes.cast(
            ctypes.byref(buffer, ctypes.sizeof(wintypes.DWORD)),
            ctypes.POINTER(_MibTcpRowOwnerPid * count),
        ).contents
        return [
            {
                "local_port": socket.ntohs(row.local_port & 0xFFFF),
                "remote_port": socket.ntohs(row.remote_port & 0xFFFF),
                "state": _TCP_STATES.get(int(row.state), str(int(row.state))),
                "pid": int(row.pid),
            }
            for row in row_array
        ]
    return []


def endpoint_port(endpoint: str) -> int | None:
    try:
        return int(endpoint.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


