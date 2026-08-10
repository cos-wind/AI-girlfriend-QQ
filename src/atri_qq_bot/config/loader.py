"""从 .env 读取并约束运行配置。

所有数值范围在此处收敛，例如工具调用次数、视频抽帧数和语音长度；下游
模块因此不应自行解析环境变量。修改 .env 后经 WebUI 的 reload_config
或重启服务生效。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from .env import (
    _env,
    _env_bool,
    _env_float,
    _env_int,
    _env_int_tuple,
    _env_path,
    _optional_env,
    _project_root,
)
from .schema import VALID_REPLY_MODES, BotConfig


def load_config(env_file: str | Path | None = None) -> BotConfig:
    """加载指定 .env 并返回已校验配置；非法回复模式会立即报错。"""
    root = _project_root()
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(root / ".env", override=True)

    reply_mode = _env("REPLY_MODE", "mention").lower()
    if reply_mode not in VALID_REPLY_MODES:
        modes = ", ".join(sorted(VALID_REPLY_MODES))
        raise ValueError(f"REPLY_MODE must be one of: {modes}")

    openai_base_url = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    openai_model = _supported_model_alias(
        openai_base_url,
        _env("OPENAI_MODEL", "gpt-4.1-mini"),
    )
    openai_api_key = _optional_env("OPENAI_API_KEY")
    return BotConfig(
        bot_qq=_env_int("BOT_QQ", 0),
        host=_env("HOST", "127.0.0.1"),
        port=_env_int("PORT", 8765),
        reply_mode=reply_mode,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        openai_model=openai_model,
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
        memory_retrieval_enabled=_env_bool("MEMORY_RETRIEVAL_ENABLED", True),
        memory_retrieval_path=_env_path(
            "MEMORY_RETRIEVAL_PATH",
            root / "data" / "memory" / "semantic_memory.sqlite3",
            root,
        ),
        memory_retrieval_max_chars=max(
            800, min(3_000, _env_int("MEMORY_RETRIEVAL_MAX_CHARS", 1_800))
        ),
        memory_retrieval_lore_limit=max(
            1, min(5, _env_int("MEMORY_RETRIEVAL_LORE_LIMIT", 3))
        ),
        memory_retrieval_memory_limit=max(
            2, min(8, _env_int("MEMORY_RETRIEVAL_MEMORY_LIMIT", 5))
        ),
        memory_vector_enabled=_env_bool("MEMORY_VECTOR_ENABLED", False),
        memory_embedding_model=_env("MEMORY_EMBEDDING_MODEL", "bge-m3:latest"),
        memory_embedding_base_url=_env(
            "MEMORY_EMBEDDING_BASE_URL", "http://127.0.0.1:11434"
        ).rstrip("/"),
        memory_embedding_timeout_seconds=max(
            0.5, min(20.0, _env_float("MEMORY_EMBEDDING_TIMEOUT_SECONDS", 2.0))
        ),
        memory_extraction_enabled=_env_bool("MEMORY_EXTRACTION_ENABLED", True),
        memory_extraction_llm_enabled=_env_bool("MEMORY_EXTRACTION_LLM_ENABLED", True),
        memory_extraction_model=_env("MEMORY_EXTRACTION_MODEL", "qwen3:4b-instruct"),
        memory_extraction_base_url=_env(
            "MEMORY_EXTRACTION_BASE_URL", openai_base_url
        ).rstrip("/"),
        memory_extraction_api_key=_optional_env("MEMORY_EXTRACTION_API_KEY") or openai_api_key,
        memory_extraction_timeout_seconds=max(
            3.0, min(30.0, _env_float("MEMORY_EXTRACTION_TIMEOUT_SECONDS", 10.0))
        ),
        memory_extraction_cooldown_seconds=max(
            5.0, min(300.0, _env_float("MEMORY_EXTRACTION_COOLDOWN_SECONDS", 45.0))
        ),
        memory_backfill_enabled=_env_bool("MEMORY_BACKFILL_ENABLED", True),
        memory_backfill_max_conversations=max(
            10, min(500, _env_int("MEMORY_BACKFILL_MAX_CONVERSATIONS", 250))
        ),
        proactive_v2_enabled=_env_bool("PROACTIVE_V2_ENABLED", False),
        idle_proactive_enabled=_env_bool("IDLE_PROACTIVE_ENABLED", True),
        idle_minutes=_env_int("IDLE_MINUTES", 180),
        idle_cooldown_minutes=_env_int("IDLE_COOLDOWN_MINUTES", 720),
        idle_check_seconds=_env_int("IDLE_CHECK_SECONDS", 60),
        group_context_enabled=_env_bool("GROUP_CONTEXT_ENABLED", True),
        group_proactive_enabled=_env_bool("GROUP_PROACTIVE_ENABLED", True),
        group_proactive_idle_minutes=_env_int("GROUP_PROACTIVE_IDLE_MINUTES", 90),
        group_proactive_cooldown_minutes=_env_int("GROUP_PROACTIVE_COOLDOWN_MINUTES", 240),
        group_proactive_daily_limit=min(3, _env_int("GROUP_PROACTIVE_DAILY_LIMIT", 3)),
        group_proactive_max_silence_days=max(0, _env_int("GROUP_PROACTIVE_MAX_SILENCE_DAYS", 3)),
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
        toolbox_vision_fallback_model=_env(
            "TOOLBOX_VISION_FALLBACK_MODEL",
            "",
        ),
        toolbox_vision_base_url=_env("TOOLBOX_VISION_BASE_URL", "").rstrip("/"),
        toolbox_vision_api_key=_optional_env("TOOLBOX_VISION_API_KEY"),
        toolbox_vision_max_bytes=_env_int("TOOLBOX_VISION_MAX_BYTES", 8_000_000),
        toolbox_vision_retry_count=max(
            0,
            min(3, _env_int("TOOLBOX_VISION_RETRY_COUNT", 1)),
        ),
        toolbox_vision_resource_wait_seconds=max(
            5.0,
            min(
                300.0,
                _env_float("TOOLBOX_VISION_RESOURCE_WAIT_SECONDS", 120.0),
            ),
        ),
        toolbox_vision_unload_other_ollama_models=_env_bool(
            "TOOLBOX_VISION_UNLOAD_OTHER_OLLAMA_MODELS",
            True,
        ),
        toolbox_ocr_enabled=_env_bool("TOOLBOX_OCR_ENABLED", False),
        toolbox_video_frame_analysis_enabled=_env_bool("TOOLBOX_VIDEO_FRAME_ANALYSIS_ENABLED", True),
        toolbox_video_max_frames=max(1, min(8, _env_int("TOOLBOX_VIDEO_MAX_FRAMES", 4))),
        llm_tools_enabled=_env_bool("LLM_TOOLS_ENABLED", True),
        llm_tool_max_calls=max(1, min(4, _env_int("LLM_TOOL_MAX_CALLS", 2))),
        llm_agent_protocol_enabled=_env_bool("LLM_AGENT_PROTOCOL_ENABLED", False),
        llm_agent_max_steps=max(2, min(10, _env_int("LLM_AGENT_MAX_STEPS", 6))),
        llm_agent_max_tool_calls=max(
            1,
            min(6, _env_int("LLM_AGENT_MAX_TOOL_CALLS", 3)),
        ),
        human_reply_pipeline_enabled=_env_bool("HUMAN_REPLY_PIPELINE_ENABLED", True),
        web_search_enabled=_env_bool("WEB_SEARCH_ENABLED", True),
        web_search_timeout_seconds=_env_float("WEB_SEARCH_TIMEOUT_SECONDS", 6.0),
        web_search_max_results=max(1, min(8, _env_int("WEB_SEARCH_MAX_RESULTS", 5))),
        web_page_max_chars=max(1000, min(20_000, _env_int("WEB_PAGE_MAX_CHARS", 8_000))),
        web_grounding_review_enabled=_env_bool("WEB_GROUNDING_REVIEW_ENABLED", True),
        voice_asr_enabled=_env_bool("VOICE_ASR_ENABLED", False),
        voice_tts_enabled=_env_bool("VOICE_TTS_ENABLED", False),
        voice_service_url=_env("VOICE_SERVICE_URL", "http://127.0.0.1:8790").rstrip("/"),
        voice_service_timeout_seconds=max(
            2.0, _env_float("VOICE_SERVICE_TIMEOUT_SECONDS", 180.0)
        ),
        voice_profile=_env("VOICE_PROFILE", "atri"),
        voice_zh_rescue_profile=_env(
            "VOICE_ZH_RESCUE_PROFILE",
            "atri-official-v2pro-curated-gpt-e6",
        ),
        voice_group_enabled=_env_bool("VOICE_GROUP_ENABLED", False),
        voice_reply_to_voice=_env_bool("VOICE_REPLY_TO_VOICE", False),
        voice_max_chars=max(20, min(500, _env_int("VOICE_MAX_CHARS", 160))),
        voice_segment_max_chars=max(
            16,
            min(60, _env_int("VOICE_SEGMENT_MAX_CHARS", 34)),
        ),
        voice_cooldown_seconds=max(0, _env_int("VOICE_COOLDOWN_SECONDS", 30)),
        voice_input_max_bytes=max(
            1_000_000, _env_int("VOICE_INPUT_MAX_BYTES", 20_000_000)
        ),
        webui_enabled=_env_bool("WEBUI_ENABLED", True),
        webui_host=_env("WEBUI_HOST", "127.0.0.1"),
        webui_port=_env_int("WEBUI_PORT", 8787),
    )


def _supported_model_alias(base_url: str, model: str) -> str:
    if "api.deepseek.com" not in str(base_url).casefold():
        return model
    return {
        "deepseek-chat": "deepseek-v4-flash",
        "deepseek-reasoner": "deepseek-v4-pro",
    }.get(str(model).strip().casefold(), model)
