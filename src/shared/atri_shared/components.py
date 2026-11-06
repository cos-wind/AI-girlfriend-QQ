"""Portable component discovery. Reading this module never imports AI runtimes."""
from __future__ import annotations
import json
from pathlib import Path
import sys
from atrium_runtime import resource_root, user_root

REQUIRED = {
    'voice-asr': ('python.exe', 'python311._pth', 'app/src/atri_voice_service/server.py',
                  'Lib/site-packages/funasr/__init__.py', 'Lib/site-packages/torch/__init__.py',
                  'models/sensevoice/model.pt', 'models/sensevoice/config.yaml',
                  'models/vad/model.pt', 'models/vad/config.yaml'),
    'music-workbench': ('python.exe', 'launch.py', 'web/index.html', 'app/src/backend/bridge/server.py'),
    'music-rvc-cpu': ('python.exe', 'pipeline-template.json', 'rvc/infer/cli.py', 'rvc/assets/weights/ATRI01.pth'),
}


def find_component(id_, roots=None):
    if id_ not in REQUIRED:
        return None
    for root in roots if roots is not None else (user_root(), Path(sys.executable).parent, resource_root()):
        candidate = Path(root) / 'components' / id_
        try:
            manifest = json.loads((candidate / 'component.json').read_text(encoding='utf-8'))
            if (manifest.get('id') == id_ and manifest.get('version') == '1.0.0'
                    and manifest.get('platform') == 'windows-x64'
                    and all((candidate / file).is_file() and (candidate / file).stat().st_size > 0 for file in REQUIRED[id_])):
                return candidate
        except (OSError, ValueError, AttributeError):
            continue
    return None
