from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"
TOOLS_DIR = PROJECT_ROOT / "tools"
LOG_DIR = PROJECT_ROOT / "logs"
PROMPT_DIR = PROJECT_ROOT / "docs" / "prompts"

WEBUI_DIR = DATA_DIR / "webui"
MODEL_PROFILE_PATH = WEBUI_DIR / "model_profiles.json"
PROACTIVE_POLICY_PATH = WEBUI_DIR / "proactive_policy.json"

VOICE_ROOT = DATA_DIR / "voice"
VOICE_PROFILE_DIR = VOICE_ROOT / "profiles"
VOICE_CACHE_DIR = VOICE_ROOT / "cache"
VOICE_BEHAVIOR_PATH = WEBUI_DIR / "voice_behavior.json"


def _configured_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        value = dotenv_values(ENV_PATH).get(name)
    if not value or not str(value).strip():
        return default
    path = Path(str(value).strip())
    return path if path.is_absolute() else PROJECT_ROOT / path


STICKER_ROOT = _configured_path("STICKER_DIR", DATA_DIR / "stickers")
STICKER_DELETED_DIR = STICKER_ROOT / "_deleted"

MEMORY_PATH = DATA_DIR / "memory" / "users.json"
MEMORY_BACKUP_DIR = DATA_DIR / "memory" / "backups"
