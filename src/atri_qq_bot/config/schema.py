from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .env import _project_root


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
    group_proactive_max_silence_days: int = 3
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
    llm_tools_enabled: bool = True
    llm_tool_max_calls: int = 2
    web_search_enabled: bool = True
    web_search_timeout_seconds: float = 6.0
    web_search_max_results: int = 5
    webui_enabled: bool = True
    webui_host: str = "127.0.0.1"
    webui_port: int = 8787

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)
