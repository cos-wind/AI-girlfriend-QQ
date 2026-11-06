"""Locate an optional portable recognition runtime; never load its dependencies."""
from __future__ import annotations

import os
from pathlib import Path

from atrium_runtime import user_root
from .components import REQUIRED as COMPONENT_REQUIRED, find_component

REQUIRED = COMPONENT_REQUIRED['voice-asr']


def find_voice_component(roots=None) -> Path | None:
    return find_component('voice-asr', roots=roots)


def voice_component_environment(component: Path, *, root=None, env=None) -> dict[str, str]:
    """Pass user paths explicitly to embedded Python, which is not a frozen EXE."""
    result = dict(os.environ if env is None else env)
    state = Path(root) if root is not None else user_root()
    models = component / 'models'
    result.update(
        ATRIUM_USER_DIR=str(state),
        ATRI_ASR_PROVIDER='sensevoice', ATRI_ASR_DEVICE='cpu',
        ATRI_ASR_MODEL=str(models / 'sensevoice'), ATRI_ASR_VAD_MODEL=str(models / 'vad'),
        MODELSCOPE_CACHE=str(state / 'models/modelscope'), HF_HOME=str(state / 'models/huggingface'),
        ATRI_TTS_PREWARM_ENABLED='false', PYTHONDONTWRITEBYTECODE='1',
    )
    # Embedded Python resolves its own fixed _pth, never the developer PYTHONPATH.
    result.pop('PYTHONPATH', None)
    result.pop('PYTHONHOME', None)
    return result
