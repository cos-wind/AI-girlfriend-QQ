"""ATRI 的不可变运行配置契约。

``BotConfig`` 只保存经过 loader 校验后的值：OneBot 地址、回复策略、
模型与多模态开关、语音、WebUI。业务模块只读取它，配置修改由 WebUI
写入 .env 后重新加载，避免运行中出现半更新状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .env import _project_root


VALID_REPLY_MODES = {"private", "mention", "smart", "all"}


@dataclass(frozen=True)
class BotConfig:
    # OneBot 反向 WebSocket：NapCat 连接到 host:port/onebot。
    bot_qq: int
    host: str
    port: int
    reply_mode: str  # private / mention / smart / all，见 VALID_REPLY_MODES。
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    temperature: float
    max_tokens: int
    frequency_penalty: float = 0.25
    # 单次模型请求和 GPU 排队分别设上限，避免一个失败轮次拖住整个会话。
    chat_request_timeout_seconds: float = 25.0
    chat_resource_wait_seconds: float = 35.0
    chat_quality_retries: int = 1
    message_split_max_chars: int = 44
    message_split_max_parts: int = 4
    message_send_delay_min: float = 0.55
    message_send_delay_max: float = 1.35
    # 拟人打字节奏：按字数估算"打完这一条"的耗时，再叠加抖动。
    # reply_first_delay_* 是看到消息到发出第一条之间的停顿（读消息 + 起手打字）。
    typing_chars_per_second: float = 5.5
    typing_max_delay_seconds: float = 12.0
    reply_first_delay_min: float = 0.8
    reply_first_delay_max: float = 2.5
    sticker_dir: Path = field(default_factory=lambda: _project_root() / "data" / "stickers")
    sticker_trigger_file: Path = field(
        default_factory=lambda: _project_root() / "data" / "stickers" / "triggers.json"
    )
    # Incoming chat stickers belong to the configured QQ account record tree,
    # not to the local library used by the model when it sends stickers.
    sticker_capture_dir: Path = field(
        default_factory=lambda: Path.home()
        / "Documents"
        / "Tencent Files"
        / "0"
        / "ATRI"
        / "chat_history"
    )
    sticker_chance: float = 0.24
    sticker_cooldown_seconds: int = 120
    sticker_capture_enabled: bool = True
    sticker_capture_max_bytes: int = 3_000_000
    memory_path: Path = field(default_factory=lambda: _project_root() / "data" / "memory" / "users.json")
    # JSON 是可编辑事实源；SQLite 仅作可删除、可重建的检索索引。
    memory_retrieval_enabled: bool = True
    memory_retrieval_path: Path = field(
        default_factory=lambda: _project_root() / "data" / "memory" / "semantic_memory.sqlite3"
    )
    memory_retrieval_max_chars: int = 1_800
    memory_retrieval_lore_limit: int = 3
    memory_retrieval_memory_limit: int = 5
    # 默认关闭向量调用：bge-m3 会按需占用额外内存，FTS5 主路径始终可用。
    memory_vector_enabled: bool = False
    memory_embedding_model: str = "bge-m3:latest"
    memory_embedding_base_url: str = "http://127.0.0.1:11434"
    memory_embedding_timeout_seconds: float = 2.0
    # 记忆提取在独立后台线程执行；即使本地模型超时也不影响回复链路。
    memory_extraction_enabled: bool = True
    memory_extraction_llm_enabled: bool = True
    memory_extraction_model: str = "qwen3:4b-instruct"
    memory_extraction_base_url: str = "http://127.0.0.1:11434"
    memory_extraction_api_key: str | None = None
    memory_extraction_timeout_seconds: float = 10.0
    memory_extraction_cooldown_seconds: float = 45.0
    # 启动后低优先级回放已有 history；只写入有证据的显式事实/重复偏好。
    memory_backfill_enabled: bool = True
    memory_backfill_max_conversations: int = 250
    proactive_v2_enabled: bool = False
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
    toolbox_vision_fallback_model: str = ""
    toolbox_vision_base_url: str = ""
    # 可选：视觉兜底模型的独立接口地址。未填写时，本地模型名自动使用本机 Ollama。
    toolbox_vision_fallback_base_url: str = ""
    toolbox_vision_api_key: str | None = None
    toolbox_vision_max_bytes: int = 8_000_000
    toolbox_vision_retry_count: int = 1
    toolbox_vision_resource_wait_seconds: float = 10.0
    toolbox_vision_timeout_seconds: float = 55.0
    toolbox_vision_unload_other_ollama_models: bool = False
    toolbox_ocr_enabled: bool = False
    toolbox_video_frame_analysis_enabled: bool = True
    toolbox_video_max_frames: int = 4
    # 单条视频消息的总处理预算，默认 60 秒，超时自动降级到 OCR/标题。
    toolbox_video_deadline_seconds: float = 60.0
    # 多帧（视频抽样帧 / 多帧 GIF）视觉理解的输出 token 上限。
    # 单张图片继续用固定 320；多帧综合理解需要更多字段输出，默认放宽到 800。
    toolbox_vision_video_num_predict: int = 800
    llm_tools_enabled: bool = True
    llm_tool_max_calls: int = 2
    llm_agent_protocol_enabled: bool = False
    llm_agent_max_steps: int = 6
    llm_agent_max_tool_calls: int = 3
    human_reply_pipeline_enabled: bool = True
    # 新认知内核先以只读影子模式运行：维护持续目标、自我和情绪，
    # 但不发送消息、不调用副作用能力，也不写入 L1/L2/L3。
    cognition_shadow_enabled: bool = True
    cognition_state_path: Path = field(
        default_factory=lambda: _project_root() / "data" / "cognition" / "state.sqlite3"
    )
    cognition_shadow_timeout_seconds: float = 2.0
    cognition_shadow_max_concurrency: int = 2
    web_search_enabled: bool = True
    web_search_timeout_seconds: float = 6.0
    web_search_max_results: int = 5
    # 结构化搜索 API key（可选，任一配置即启用该源；未配置自动跳过）。
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    searxng_instances: str = ""
    web_page_max_chars: int = 8_000
    web_grounding_review_enabled: bool = True
    # 时效性/专业事实类提问强制先联网取证，避免小模型直接拿训练记忆编造版本号、
    # 价格、政策等易过期信息。设为 false 可退回"模型自行决定是否搜索"。
    web_fact_search_enforcement: bool = True
    voice_asr_enabled: bool = False
    voice_tts_enabled: bool = False
    voice_service_url: str = "http://127.0.0.1:8790"
    voice_service_timeout_seconds: float = 180.0
    voice_profile: str = "atri"
    voice_zh_profile: str = ""
    voice_group_enabled: bool = False
    voice_reply_to_voice: bool = False
    voice_max_chars: int = 160
    voice_segment_max_chars: int = 100
    voice_cooldown_seconds: int = 30
    voice_input_max_bytes: int = 20_000_000
    # WebUI 仅允许绑定回环地址，避免把本机管理能力暴露到局域网。
    webui_enabled: bool = True
    webui_host: str = "127.0.0.1"
    webui_port: int = 8787
    # 账号管理系统（见 docs/account_system/）。两个开关默认关闭，此时整条链路走
    # 账号化之前的代码路径——"代码部署了但开关没开"等于零行为变化，回退只需改
    # .env 加重启。
    account_system_enabled: bool = False
    account_follow_napcat: bool = False
    accounts_db_path: Path = field(
        default_factory=lambda: _project_root() / "data" / "accounts" / "index.sqlite3"
    )

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)
