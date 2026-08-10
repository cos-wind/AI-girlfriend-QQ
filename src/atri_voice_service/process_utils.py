from __future__ import annotations

import os
import subprocess
from typing import Any


def hidden_subprocess_options() -> dict[str, Any]:
    """Return Windows process options that prevent console child windows."""
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        "startupinfo": startupinfo,
    }
