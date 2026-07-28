from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"
TOOLS_DIR = PROJECT_ROOT / "tools"

WEBUI_DIR = DATA_DIR / "webui"
MODEL_PROFILE_PATH = WEBUI_DIR / "model_profiles.json"
PROACTIVE_POLICY_PATH = WEBUI_DIR / "proactive_policy.json"

VOICE_ROOT = DATA_DIR / "voice"
VOICE_PROFILE_DIR = VOICE_ROOT / "profiles"
VOICE_CACHE_DIR = VOICE_ROOT / "cache"
VOICE_BEHAVIOR_PATH = WEBUI_DIR / "voice_behavior.json"

STICKER_ROOT = DATA_DIR / "stickers"
STICKER_DELETED_DIR = STICKER_ROOT / "_deleted"

MEMORY_PATH = DATA_DIR / "memory" / "users.json"
MEMORY_BACKUP_DIR = DATA_DIR / "memory" / "backups"
