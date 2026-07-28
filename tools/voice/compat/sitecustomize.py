from __future__ import annotations

import os
import subprocess
from typing import Any


if os.name == "nt" and not getattr(subprocess.Popen, "_atri_hidden", False):
    _OriginalPopen = subprocess.Popen

    class _HiddenPopen(_OriginalPopen):
        _atri_hidden = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | int(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startupinfo
            super().__init__(*args, **kwargs)

    subprocess.Popen = _HiddenPopen
