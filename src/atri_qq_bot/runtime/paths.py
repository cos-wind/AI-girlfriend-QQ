from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from atri_runtime import resource_root, user_root


PROJECT_ROOT = user_root()
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"
TOOLS_DIR = resource_root() / "tools"
LOG_DIR = PROJECT_ROOT / "logs"
PROMPT_DIR = resource_root() / "docs" / "prompts"

WEBUI_DIR = DATA_DIR / "webui"
MODEL_PROFILE_PATH = WEBUI_DIR / "model_profiles.json"
PROACTIVE_POLICY_PATH = WEBUI_DIR / "proactive_policy.json"
# 视觉/语音用户权限由 WebUI 写入，OneBot 进程按需读取；独立文件避免污染 .env。
MODALITY_ACCESS_PATH = WEBUI_DIR / "modality_access.json"
# 回复策略（按对象/好感度/活跃度决定是否回复、频率与长度）与它的运行计数分开存，
# 避免 WebUI 保存配置时覆盖掉正在累计的频率计数。
REPLY_STRATEGY_PATH = WEBUI_DIR / "reply_strategy.json"
REPLY_STRATEGY_STATE_PATH = WEBUI_DIR / "reply_strategy_state.json"

VOICE_ROOT = DATA_DIR / "voice"
VOICE_PROFILE_DIR = VOICE_ROOT / "profiles"
VOICE_CACHE_DIR = VOICE_ROOT / "cache"
VOICE_BEHAVIOR_PATH = WEBUI_DIR / "voice_behavior.json"

# QQ 点歌只读取此目录中的成品文件。
MUSIC_ROOT = DATA_DIR / "music"


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
