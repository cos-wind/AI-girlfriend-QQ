"""Installation resources and private writable state for ATRIum.

Source checkouts keep their existing layout. Release executables never write
beside the EXE and can use --user-dir to exercise a completely fresh profile.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

VERSION = "1.0.0"


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_packaged():
        return Path(sys._MEIPASS)
    location = Path(__file__).resolve()
    # The checkout groups shared modules under src/shared; portable Python
    # components and wheels retain the flat package layout.
    if location.parent.name == "shared" and location.parent.parent.name == "src":
        return location.parents[2]
    return location.parents[1]


def user_root() -> Path:
    configured = os.environ.get("ATRIUM_USER_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if is_packaged():
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ATRIum"
    return resource_root()


def instance_suffix() -> str:
    if is_packaged() or os.environ.get("ATRIUM_USER_DIR"):
        return "-" + hashlib.sha256(str(user_root()).casefold().encode()).hexdigest()[:12]
    return ""


def worker_command(worker: str, *args: str) -> list[str]:
    if not is_packaged():
        raise RuntimeError("worker dispatch is only for the release executable")
    return [sys.executable, "--worker", worker, *args]


def source_python(*args: str, windowed: bool = True) -> tuple[list[str], dict[str, str]]:
    """Use project dependencies without Windows' venv executable redirector.

    The redirector adds a process job that prevents the dedicated QQ client
    from starting. Launch the base interpreter directly with the same venv.
    """
    env = dict(os.environ)
    executable = Path(sys.executable)
    if sys.platform == "win32":
        name = "pythonw.exe" if windowed else "python.exe"
        venv = resource_root() / ".venv"
        config = venv / "pyvenv.cfg"
        home = Path(sys._base_executable).parent
        if config.is_file():
            for line in config.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "home":
                    home = Path(value.strip())
                    break
        executable = home / name
        if (venv / "Scripts" / name).is_file():
            env["__PYVENV_LAUNCHER__"] = str(venv / "Scripts" / name)
    return [str(executable), *args], env
