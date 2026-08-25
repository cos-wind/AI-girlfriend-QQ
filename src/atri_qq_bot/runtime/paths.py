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
# 视觉/语音用户权限由 WebUI 写入，OneBot 进程按需读取；独立文件避免污染 .env。
MODALITY_ACCESS_PATH = WEBUI_DIR / "modality_access.json"

VOICE_ROOT = DATA_DIR / "voice"
VOICE_PROFILE_DIR = VOICE_ROOT / "profiles"
VOICE_CACHE_DIR = VOICE_ROOT / "cache"
VOICE_BEHAVIOR_PATH = WEBUI_DIR / "voice_behavior.json"

# QQ 唱歌只读取 COMPLETE_MUSIC_ROOT，按文件名匹配并作为 QQ 语音发送整首。
# DELIVERY_MUSIC_ROOT 是 WebUI 的旧版分段管理/试听库，不参与 QQ 发送。
MUSIC_ROOT = DATA_DIR / "music"
COMPLETE_MUSIC_ROOT = MUSIC_ROOT / "完整音乐"
DELIVERY_MUSIC_ROOT = MUSIC_ROOT / "完整音乐片段"


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
