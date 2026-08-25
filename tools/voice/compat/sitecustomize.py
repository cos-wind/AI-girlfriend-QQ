from __future__ import annotations

import os
import subprocess
from typing import Any


if os.environ.get("ATRI_G2PW_FORCE_CPU", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}:
    # GPT-SoVITS v2Pro only uses ONNX Runtime for the small Chinese G2PW
    # front-end. The bundled ORT GPU wheel targets CUDA 13 while this runtime
    # uses PyTorch CUDA 12, so probing CUDA emits a missing-cublas error and
    # delays the first Chinese sentence before falling back to CPU. Keep the
    # acoustic models on CUDA and expose CPU only to this ONNX front-end.
    try:
        import onnxruntime as _onnxruntime

        _onnxruntime.preload_dlls = lambda *args, **kwargs: None
        _onnxruntime.get_available_providers = lambda: ["CPUExecutionProvider"]
    except ImportError:
        pass


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
