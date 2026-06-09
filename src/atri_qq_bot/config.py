from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


VALID_REPLY_MODES = {"private", "mention", "smart", "all"}


@dataclass(frozen=True)
class BotConfig:
    bot_qq: int
    host: str
    port: int
    reply_mode: str
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    temperature: float
    max_tokens: int
    frequency_penalty: float = 0.25
    message_split_max_chars: int = 44
    message_split_max_parts: int = 4
    message_send_delay_min: float = 0.55
    message_send_delay_max: float = 1.35
    sticker_dir: Path = field(default_factory=lambda: _project_root() / "data" / "stickers")
    sticker_trigger_file: Path = field(
        default_factory=lambda: _project_root() / "data" / "stickers" / "triggers.json"
    )
    sticker_chance: float = 0.24
    sticker_cooldown_seconds: int = 120
    sticker_capture_enabled: bool = True
    sticker_capture_max_bytes: int = 3_000_000
    memory_path: Path = field(default_factory=lambda: _project_root() / "data" / "memory" / "users.json")
    idle_proactive_enabled: bool = True
    idle_minutes: int = 180
    idle_cooldown_minutes: int = 720
    idle_check_seconds: int = 60
    group_context_enabled: bool = True
    group_proactive_enabled: bool = True
    group_proactive_idle_minutes: int = 90
    group_proactive_cooldown_minutes: int = 240
    group_proactive_daily_limit: int = 3
    group_proactive_check_seconds: int = 90
    owner_qqs: tuple[int, ...] = ()
    morning_greeting_enabled: bool = True
    morning_greeting_time: str = "07:30"
    morning_greeting_timezone: str = "Asia/Shanghai"
    morning_greeting_catchup_minutes: int = 90
    toolbox_enabled: bool = True
    toolbox_timeout_seconds: float = 8.0
    toolbox_max_bytes: int = 2_000_000
    toolbox_max_document_bytes: int = 20_000_000
    toolbox_max_media_bytes: int = 80_000_000
    toolbox_vision_enabled: bool = False
    toolbox_vision_model: str = ""
    toolbox_vision_base_url: str = ""
    toolbox_vision_api_key: str | None = None
    toolbox_vision_max_bytes: int = 8_000_000
    toolbox_video_frame_analysis_enabled: bool = True
    toolbox_video_max_frames: int = 4

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)


def load_config(env_file: str | Path | None = None) -> BotConfig:
    root = _project_root()
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(root / ".env", override=True)

    reply_mode = _env("REPLY_MODE", "mention").lower()
    if reply_mode not in VALID_REPLY_MODES:
        modes = ", ".join(sorted(VALID_REPLY_MODES))
        raise ValueError(f"REPLY_MODE must be one of: {modes}")

    return BotConfig(
        bot_qq=_env_int("BOT_QQ", 3380609082),
        host=_env("HOST", "127.0.0.1"),
        port=_env_int("PORT", 8765),
        reply_mode=reply_mode,
        openai_api_key=_optional_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        openai_model=_env("OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=_env_float("TEMPERATURE", 0.8),
        frequency_penalty=_env_float("FREQUENCY_PENALTY", 0.25),
        max_tokens=_env_int("MAX_TOKENS", 350),
        message_split_max_chars=_env_int("MESSAGE_SPLIT_MAX_CHARS", 44),
        message_split_max_parts=_env_int("MESSAGE_SPLIT_MAX_PARTS", 4),
        message_send_delay_min=_env_float("MESSAGE_SEND_DELAY_MIN", 0.55),
        message_send_delay_max=_env_float("MESSAGE_SEND_DELAY_MAX", 1.35),
        sticker_dir=_env_path("STICKER_DIR", root / "data" / "stickers", root),
        sticker_trigger_file=_env_path(
            "STICKER_TRIGGER_FILE", root / "data" / "stickers" / "triggers.json", root
        ),
        sticker_chance=_env_float("STICKER_CHANCE", 0.24),
        sticker_cooldown_seconds=_env_int("STICKER_COOLDOWN_SECONDS", 120),
        sticker_capture_enabled=_env_bool("STICKER_CAPTURE_ENABLED", True),
        sticker_capture_max_bytes=_env_int("STICKER_CAPTURE_MAX_BYTES", 3_000_000),
        memory_path=_env_path("MEMORY_PATH", root / "data" / "memory" / "users.json", root),
        idle_proactive_enabled=_env_bool("IDLE_PROACTIVE_ENABLED", True),
        idle_minutes=_env_int("IDLE_MINUTES", 180),
        idle_cooldown_minutes=_env_int("IDLE_COOLDOWN_MINUTES", 720),
        idle_check_seconds=_env_int("IDLE_CHECK_SECONDS", 60),
        group_context_enabled=_env_bool("GROUP_CONTEXT_ENABLED", True),
        group_proactive_enabled=_env_bool("GROUP_PROACTIVE_ENABLED", True),
        group_proactive_idle_minutes=_env_int("GROUP_PROACTIVE_IDLE_MINUTES", 90),
        group_proactive_cooldown_minutes=_env_int("GROUP_PROACTIVE_COOLDOWN_MINUTES", 240),
        group_proactive_daily_limit=min(3, _env_int("GROUP_PROACTIVE_DAILY_LIMIT", 3)),
        group_proactive_check_seconds=_env_int("GROUP_PROACTIVE_CHECK_SECONDS", 90),
        owner_qqs=_env_int_tuple("OWNER_QQ", ()),
        morning_greeting_enabled=_env_bool("MORNING_GREETING_ENABLED", True),
        morning_greeting_time=_env("MORNING_GREETING_TIME", "07:30"),
        morning_greeting_timezone=_env("MORNING_GREETING_TIMEZONE", "Asia/Shanghai"),
        morning_greeting_catchup_minutes=_env_int("MORNING_GREETING_CATCHUP_MINUTES", 90),
        toolbox_enabled=_env_bool("TOOLBOX_ENABLED", True),
        toolbox_timeout_seconds=_env_float("TOOLBOX_TIMEOUT_SECONDS", 8.0),
        toolbox_max_bytes=_env_int("TOOLBOX_MAX_BYTES", 2_000_000),
        toolbox_max_document_bytes=_env_int("TOOLBOX_MAX_DOCUMENT_BYTES", 20_000_000),
        toolbox_max_media_bytes=_env_int("TOOLBOX_MAX_MEDIA_BYTES", 80_000_000),
        toolbox_vision_enabled=_env_bool("TOOLBOX_VISION_ENABLED", False),
        toolbox_vision_model=_env("TOOLBOX_VISION_MODEL", ""),
        toolbox_vision_base_url=_env("TOOLBOX_VISION_BASE_URL", "").rstrip("/"),
        toolbox_vision_api_key=_optional_env("TOOLBOX_VISION_API_KEY"),
        toolbox_vision_max_bytes=_env_int("TOOLBOX_VISION_MAX_BYTES", 8_000_000),
        toolbox_video_frame_analysis_enabled=_env_bool("TOOLBOX_VIDEO_FRAME_ANALYSIS_ENABLED", True),
        toolbox_video_max_frames=max(1, min(8, _env_int("TOOLBOX_VIDEO_MAX_FRAMES", 4))),
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_path(name: str, default: Path, base: Path) -> Path:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    path = Path(value.strip())
    if path.is_absolute():
        return path
    return base / path


def _env_int_tuple(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    value = os.getenv(name)
    if not value or not value.strip():
        return default

    numbers: list[int] = []
    for piece in value.replace("，", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        numbers.append(int(piece))
    return tuple(numbers)
