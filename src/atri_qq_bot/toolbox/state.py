from __future__ import annotations

from typing import Any

from .support import ToolboxMixin


class ToolboxStateMixin(ToolboxMixin):
    def __init__(self, config: Any) -> None:
        self.config = config
        self.enabled = bool(getattr(config, "toolbox_enabled", True))
        self.timeout = float(getattr(config, "toolbox_timeout_seconds", 8.0))
        self.max_bytes = int(getattr(config, "toolbox_max_bytes", 2_000_000))
        self.max_document_bytes = int(getattr(config, "toolbox_max_document_bytes", 20_000_000))
        self.max_media_bytes = int(getattr(config, "toolbox_max_media_bytes", 80_000_000))
        self.vision_enabled = bool(getattr(config, "toolbox_vision_enabled", False))
        self.vision_model = str(
            getattr(config, "toolbox_vision_model", "") or getattr(config, "openai_model", "")
        ).strip()
        self.vision_fallback_model = str(
            getattr(config, "toolbox_vision_fallback_model", "") or ""
        ).strip()
        self.vision_base_url = str(
            getattr(config, "toolbox_vision_base_url", "") or getattr(config, "openai_base_url", "")
        ).rstrip("/")
        # 视觉主模型和兜底模型可以来自不同提供商：例如主模型使用云端
        # GLM，资源不足或限流时切换到本机 Ollama 的 Qwen-VL。
        # 旧版本只根据主模型的 Base URL 判断传输方式，导致“云端主模型
        # + 本地兜底模型”实际上永远不会切换。
        self.vision_fallback_base_url = str(
            getattr(config, "toolbox_vision_fallback_base_url", "") or ""
        ).rstrip("/")
        self.vision_api_key = getattr(config, "toolbox_vision_api_key", None) or getattr(config, "openai_api_key", None)
        self.vision_max_bytes = int(getattr(config, "toolbox_vision_max_bytes", 8_000_000))
        self.vision_retry_count = max(
            0,
            min(3, int(getattr(config, "toolbox_vision_retry_count", 1))),
        )
        self.vision_resource_wait_seconds = max(
            5.0,
            min(
                300.0,
                float(
                    getattr(
                        config,
                        "toolbox_vision_resource_wait_seconds",
                        10.0,
                    )
                ),
            ),
        )
        self.vision_timeout_seconds = max(
            20.0,
            min(
                60.0,
                float(getattr(config, "toolbox_vision_timeout_seconds", 55.0)),
            ),
        )
        self._vision_attempt_timeout_seconds = self.vision_timeout_seconds
        self.vision_unload_other_ollama_models = bool(
            getattr(
                config,
                "toolbox_vision_unload_other_ollama_models",
                False,
            )
        )
        self.ocr_enabled = bool(getattr(config, "toolbox_ocr_enabled", False))
        self.chat_model = str(getattr(config, "openai_model", "") or "").strip()
        self.chat_base_url = str(
            getattr(config, "openai_base_url", "") or ""
        ).rstrip("/")
        self.video_frame_analysis_enabled = bool(
            getattr(config, "toolbox_video_frame_analysis_enabled", True)
        )
        self.video_max_frames = max(1, min(8, int(getattr(config, "toolbox_video_max_frames", 4))))
        # 多帧视觉理解的输出 token 上限（视频抽样帧 / 多帧 GIF）。钳制在 [320, 2048]。
        self.vision_video_num_predict = max(
            320,
            min(2048, int(getattr(config, "toolbox_vision_video_num_predict", 800))),
        )
        # 视频处理使用独立预算，避免抽帧、OCR、视觉请求串行叠加后拖住整条回复链路。
        self.video_deadline_seconds = max(
            20.0,
            min(60.0, float(getattr(config, "toolbox_video_deadline_seconds", 60.0))),
        )
        self._vision_event_log = PROJECT_ROOT / "logs" / "vision-events.jsonl"
        self._vision_lock = asyncio.Lock()
