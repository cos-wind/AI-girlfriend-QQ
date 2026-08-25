from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from atri_qq_bot.config import BotConfig, load_config
from atri_qq_bot.persona import AtriReplyEngine
from atri_qq_bot.llm_tools.web_search_tool import search_web
from atri_qq_bot.proactive import load_proactive_policy, save_proactive_policy
from atri_qq_bot.runtime import (
    LOG_DIR,
    PROJECT_ROOT,
    STICKER_DELETED_DIR,
    STICKER_ROOT,
    read_project_logs,
)
from atri_qq_bot.music import (
    AUDIO_EXTENSIONS as MUSIC_AUDIO_EXTENSIONS,
    complete_song_files,
    delivery_song_catalog,
    export_delivery_segments,
    save_complete_song,
)
from atri_qq_bot.runtime.paths import COMPLETE_MUSIC_ROOT, DELIVERY_MUSIC_ROOT
from atri_qq_bot.insights import group_summary_html, render_group_summary_image, save_insights_env, summary_markdown
from atri_qq_bot.insights.evaluation import EvaluationSample
from atri_qq_bot.voice import (
    VoicePromptContext,
    VoiceRequest,
    load_voice_behavior,
    save_voice_behavior,
)
from atri_qq_bot.runtime.control import restart_background_services, runtime_status
from atri_qq_bot.runtime.modality_access import load_modality_access, save_modality_access
from .config_admin import config_payload, update_env
from .call_page import render_voice_call
from .model_profiles import (
    MODEL_PRESETS,
    activate_model_profile,
    delete_model_profile,
    load_model_profiles,
    local_models_payload,
    model_profiles_payload,
    public_model_profile,
    upsert_model_profile,
)
from .memory_admin import (
    memory_admin_for_config,
)
from .qzone_admin import QZoneAdmin, QZoneBridgeError
from .qzone_automation import (
    QZoneAutomation,
    QZoneAutomationStore,
    parse_keywords,
    sanitize_qzone_fact_context,
    topic_for_schedule,
)
from .user_directory import UserDirectory
from .evaluation_handlers import EvaluationHandlersMixin
from .minecraft_admin import (
    minecraft_dashboard,
    save_minecraft_bridge_config,
    send_minecraft_command,
)
from .page import index as _page_module

_PAGE_MODULE_PATH = Path(__file__).with_name("page") / "index.py"
_PAGE_RELOAD_LOCK = threading.Lock()
_PAGE_MODULE_MTIME_NS = 0


def _render_index_dynamic() -> str:
    """Render the WebUI with a lightweight source-mtime reload.

    The desktop WebUI is local-only and frequently edited during development.
    Reloading this presentation module on request means a browser refresh is
    enough to pick up HTML/CSS/JS changes; API/service changes still require a
    normal process restart.
    """
    global _PAGE_MODULE_MTIME_NS
    try:
        mtime_ns = _PAGE_MODULE_PATH.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    if mtime_ns and mtime_ns != _PAGE_MODULE_MTIME_NS:
        with _PAGE_RELOAD_LOCK:
            if mtime_ns != _PAGE_MODULE_MTIME_NS:
                importlib.invalidate_caches()
                importlib.reload(_page_module)
                _PAGE_MODULE_MTIME_NS = mtime_ns
    return _page_module.render_index()
from .sticker_admin import (
    IMAGE_EXTENSIONS,
    looks_like_image_bytes,
    resolve_under,
    safe_filename,
    sanitize_category,
    sticker_file_payload,
    sticker_summary,
    unique_path,
)
from .upload_parser import multipart_file, multipart_text, parse_multipart_form
from .voice_admin import (
    AUDIO_EXTENSIONS,
    asr_lexicon_text,
    resolve_voice_audio,
    save_asr_lexicon_text,
    save_reference_audio,
    save_singing_source_audio,
    save_test_audio,
    save_tts_pronunciation_text,
    save_voice_profile,
    tts_pronunciation_text,
    voice_candidates_payload,
    voice_profiles_payload,
)

MAX_UPLOAD_BYTES = 8_000_000
MAX_VOICE_UPLOAD_BYTES = 30_000_000
MAX_SINGING_UPLOAD_BYTES = 100_000_000
MAX_MUSIC_STEM_UPLOAD_BYTES = 150_000_000
MAX_COMPLETE_MUSIC_UPLOAD_BYTES = 180_000_000
MUSIC_SERVICE_URL = os.getenv(
    "ATRI_MUSIC_SERVICE_URL",
    "http://127.0.0.1:8793",
).rstrip("/")
MUSIC_SOURCE_ROOT = Path(
    os.getenv("ATRI_MUSIC_SOURCE_DIR", str(Path.home() / "Music" / "QQmusic-MP3"))
).expanduser().resolve()
MUSIC_IMPORT_ROOT = Path(
    os.getenv(
        "ATRI_MUSIC_IMPORT_DIR",
        str(Path(__file__).resolve().parents[2] / "data" / "music_imports"),
    )
).expanduser().resolve()
LOGGER = logging.getLogger("atri.webui")

# WebUI 是本地运维面板，不承载对话主循环。API 管理配置、记忆、日志和音频资源；
# QQ 连接仍由 OneBot 进程管理，避免浏览器请求直接触碰 QQ 状态。


def _music_bridge_request(
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(
        f"{MUSIC_SERVICE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error")
        except Exception:
            detail = ""
        raise RuntimeError(detail or f"AI_music 返回 HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"AI_music 本地桥接不可达：{exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("AI_music 返回了无效响应")
    if result.get("ok") is False:
        raise RuntimeError(str(result.get("error") or "AI_music 请求失败"))
    return result


from .server_parts.voice_integrations import (
    _TRANSLATION_LANGUAGES,
    _detect_translation_source,
    _extract_translation,
    _voice_preview_synthesis_options,
    _voice_preview_synthesis_options_for_mode,
    translate_voice_text,
)


class WebUIState:
    def __init__(self, config: BotConfig, server: Any) -> None:
        self.config = config
        self.server = server
        self.lock = asyncio.Lock()
        self.group_name_lock = asyncio.Lock()
        self._group_name_refresh_at = 0.0
        self.memory_admin = memory_admin_for_config(config)
        database = Path(os.getenv("QZONE_AUTOMATION_DB", "data/qzone_automation.sqlite3"))
        self.qzone_automation = QZoneAutomation(
            QZoneAutomationStore(database),
            lambda: QZoneAdmin(
                self.memory_admin.summary(),
                bot_qq=self.config.bot_qq,
                owner_qqs=self.config.owner_qqs,
            ),
            lambda prompt, profile_id: run_coro(generate_qzone_text(self.config, prompt, "post", profile_id)),
            lambda prompt, profile_id: run_coro(generate_qzone_text(self.config, prompt, "comment", profile_id)),
            lambda settings, scheduled_at, slot_index=None: qzone_fact_context(
                self.config,
                settings,
                scheduled_at,
                slot_index,
            ),
        )
        self.qzone_login_lock = threading.Lock()
        self.qzone_login_running = False
        self.qzone_login_last: dict[str, Any] = {"ok": None, "message": ""}

    async def refresh_group_names(self, force: bool = False) -> dict[str, str]:
        """定期从 NapCat 同步群名，WebUI 断线时保留 SQLite 中的缓存。"""
        runtime = getattr(self.server, "insights", None)
        if runtime is None:
            return {}
        names = runtime.store.group_name_map()
        now = time.monotonic()
        if not force and now - self._group_name_refresh_at < 30:
            return names
        async with self.group_name_lock:
            now = time.monotonic()
            if not force and now - self._group_name_refresh_at < 30:
                return runtime.store.group_name_map()
            self._group_name_refresh_at = now
            fetch = getattr(self.server, "fetch_group_list", None)
            if not callable(fetch):
                return names
            try:
                groups = await fetch()
            except Exception as exc:
                LOGGER.debug("WebUI 同步群名失败：%s", exc)
                return names
            for item in groups:
                if isinstance(item, dict) and item.get("group_id") and item.get("group_name"):
                    runtime.store.set_group_name(str(item["group_id"]), str(item["group_name"]))
            return runtime.store.group_name_map()

    async def reload_config(self) -> BotConfig:
        async with self.lock:
            new_config = load_config()
            self.config = new_config
            self.memory_admin = memory_admin_for_config(new_config)
            self.server.config = new_config
            self.server.reply_engine.config = new_config
            if hasattr(self.server.reply_engine, "memory"):
                self.server.reply_engine.memory.update_retrieval_config(new_config)
            self.server.tools.config = new_config
            self.server.tools.enabled = bool(new_config.toolbox_enabled)
            self.server.tools.timeout = float(new_config.toolbox_timeout_seconds)
            self.server.tools.max_bytes = int(new_config.toolbox_max_bytes)
            self.server.tools.vision_enabled = bool(new_config.toolbox_vision_enabled)
            self.server.tools.vision_model = str(
                new_config.toolbox_vision_model or new_config.openai_model or ""
            )
            self.server.tools.vision_fallback_model = str(
                new_config.toolbox_vision_fallback_model or ""
            )
            self.server.tools.vision_base_url = str(
                new_config.toolbox_vision_base_url or new_config.openai_base_url or ""
            ).rstrip("/")
            self.server.tools.vision_fallback_base_url = str(
                new_config.toolbox_vision_fallback_base_url or ""
            ).rstrip("/")
            self.server.tools.vision_api_key = (
                new_config.toolbox_vision_api_key or new_config.openai_api_key
            )
            self.server.tools.vision_retry_count = int(
                new_config.toolbox_vision_retry_count
            )
            self.server.tools.vision_resource_wait_seconds = float(
                new_config.toolbox_vision_resource_wait_seconds
            )
            self.server.tools.vision_unload_other_ollama_models = bool(
                new_config.toolbox_vision_unload_other_ollama_models
            )
            self.server.tools.ocr_enabled = bool(
                new_config.toolbox_ocr_enabled
            )
            if hasattr(self.server, "voice"):
                self.server.voice.update_config(new_config)
            if hasattr(self.server, "proactive_planner"):
                self.server.proactive_planner.update_owner_qqs(new_config.owner_qqs)
            # 模型页面切换聊天模型后，评测旁路立即复用同一模型；不再维护第二套
            # Judge 接口和密钥配置。评测自身仍然在后台队列中执行。
            if getattr(self.server, "insights", None) is not None:
                await self.server.insights.reload_config()
            return new_config


async def start_webui(config: BotConfig, onebot_server: Any) -> Any | None:
    if not getattr(config, "webui_enabled", True):
        return None

    host = str(getattr(config, "webui_host", "127.0.0.1") or "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        host = "127.0.0.1"
    port = int(getattr(config, "webui_port", 8787) or 8787)
    state = WebUIState(config, onebot_server)

    class Handler(AtriWebUIHandler):
        webui_state = state

    try:
        httpd = LocalThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"[webui] skipped because http://{host}:{port} is unavailable: {exc}")
        return None
    task = asyncio.create_task(asyncio.to_thread(httpd.serve_forever))
    httpd._atri_task = task  # type: ignore[attr-defined]
    httpd._atri_webui_state = state  # type: ignore[attr-defined]
    state.qzone_automation.start()
    print(f"[webui] Listening on http://{host}:{port}")
    return httpd


async def stop_webui(httpd: Any | None) -> None:
    if httpd is None:
        return
    state = getattr(httpd, "_atri_webui_state", None)
    if state is not None:
        await state.qzone_automation.stop()
    httpd.shutdown()
    task = getattr(httpd, "_atri_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


from .server_parts.handler_config import HandlerConfigMixin
from .server_parts.handler_core import HandlerCoreMixin
from .server_parts.handler_insights import HandlerInsightsMixin
from .server_parts.handler_music import HandlerMusicMixin
from .server_parts.handler_qzone import HandlerQZoneMixin
from .server_parts.handler_response import HandlerResponseMixin
from .server_parts.handler_stickers_memory import HandlerStickersMemoryMixin
from .server_parts.handler_voice import HandlerVoiceMixin


class AtriWebUIHandler(
    HandlerCoreMixin,
    HandlerConfigMixin,
    HandlerMusicMixin,
    HandlerInsightsMixin,
    HandlerVoiceMixin,
    HandlerStickersMemoryMixin,
    HandlerQZoneMixin,
    HandlerResponseMixin,
    EvaluationHandlersMixin,
    BaseHTTPRequestHandler,
):
    webui_state: WebUIState


def _valid_singing_job_id(value: str) -> str:
    job_id = str(value or "").strip().lower()
    if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
        raise ValueError("歌唱任务 ID 无效")
    return job_id


def _valid_music_artifact_name(value: str) -> str:
    name = str(value or "").strip().lower()
    if name not in {"vocal", "harmony", "instrumental", "converted", "mix"}:
        raise ValueError("歌曲试听音轨无效")
    return name


def _valid_music_stage(value: str) -> str:
    stage = str(value or "").strip().lower()
    if stage not in {"separation", "inference", "mix"}:
        raise ValueError("歌曲处理阶段无效")
    return stage


def _singing_audio_path(value: Any, label: str) -> Path:
    raw_path = str(value or "").strip()
    if not raw_path:
        raise ValueError(f"{label}不能为空")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label}不存在：{path}")
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(f"{label}格式不受支持：{path.suffix}")
    return path


def run_coro(coro: Any) -> Any:
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop())
    return future.result(timeout=90)


_LOOP: asyncio.AbstractEventLoop | None = None


def _main_loop() -> asyncio.AbstractEventLoop:
    if _LOOP is None:
        raise RuntimeError("webui loop is not initialized")
    return _LOOP


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _LOOP
    _LOOP = loop


async def test_chat(config: BotConfig, text: str) -> dict[str, Any]:
    engine = AtriReplyEngine(
        replace(config, idle_proactive_enabled=False, group_proactive_enabled=False)
    )
    try:
        reply = await engine._reply_with_guarded_api("webui:test", text, "主人")
        reply = engine._finalize_reply(
            "webui:test",
            text,
            reply,
            strict_quality=not bool(config.human_reply_pipeline_enabled),
        )
        if not reply:
            raise RuntimeError("模型返回了空回复")
        return {"reply": reply, "used_ai": True, "error": ""}
    except Exception as exc:
        return {
            "reply": "",
            "used_ai": False,
            "error": str(exc),
        }


def _qzone_generation_config(config: BotConfig, profile_id: str) -> tuple[BotConfig, str]:
    wanted = str(profile_id or "").strip()
    if not wanted:
        return config, "当前聊天模型"
    profile = next((item for item in load_model_profiles() if str(item.get("id") or "") == wanted), None)
    if not profile:
        raise ValueError("没有找到所选模型档案")
    if str(profile.get("model_type") or "chat") != "chat":
        raise ValueError("QQ 动态生成只能选择聊天模型")
    base_url = str(profile.get("base_url") or "").strip().rstrip("/")
    model = str(profile.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError("所选模型档案缺少接口地址或模型名")
    try:
        tuned = replace(
            config,
            openai_api_key=str(profile.get("api_key") or config.openai_api_key or ""),
            openai_base_url=base_url,
            openai_model=model,
            temperature=float(profile.get("temperature") or config.temperature),
            frequency_penalty=float(profile.get("frequency_penalty") or config.frequency_penalty),
            max_tokens=max(120, int(profile.get("max_tokens") or config.max_tokens)),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"模型档案参数无效：{exc}") from exc
    return tuned, str(profile.get("name") or model)


def qzone_fact_context(
    config: BotConfig,
    settings: dict[str, Any],
    scheduled_at: float,
    slot_index: int | None = None,
) -> str:
    """Fetch recent evidence, then discard stale or low-attribution search results."""
    topic = topic_for_schedule(settings, scheduled_at, slot_index)
    query = f"{topic} 最新消息 {datetime.fromtimestamp(float(scheduled_at)).strftime('%Y-%m-%d')}"
    research_topic = any(marker in topic for marker in ("前沿", "科普", "技术", "科学", "研究"))
    trusted_domains = ["cas.cn", "arxiv.org", "nature.com"] if research_topic else ["gov.cn", "news.cn", "people.com.cn"]
    raw = str(
        run_coro(
            search_web(
                {
                    "query": query,
                    "mode": "news",
                    "domains": trusted_domains,
                    "max_results": 5,
                },
                config,
            )
        )
        or ""
    ).strip()
    return sanitize_qzone_fact_context(raw, scheduled_at)


async def generate_qzone_text(config: BotConfig, prompt: str, kind: str, profile_id: str = "") -> dict[str, Any]:
    instruction = str(prompt or "").strip()
    if not instruction:
        raise ValueError("请输入生成提示词")
    if len(instruction) > 2000:
        raise ValueError("提示词最多 2000 字")
    mode = "动态" if kind == "post" else "评论"
    if kind not in {"post", "comment"}:
        raise ValueError("生成类型无效")
    selected_config, profile_name = _qzone_generation_config(config, profile_id)
    engine = AtriReplyEngine(
        replace(
            selected_config,
            idle_proactive_enabled=False,
            group_proactive_enabled=False,
            chat_quality_retries=0,
        )
    )
    system = (
        "你现在在为 QQ 空间自动互动生成文案。你是亚托莉，必须保持当前项目已配置的人格、记忆和情绪状态。"
        f"请根据用户提示生成一条{mode}，只输出可以直接发布的{mode}正文，不要解释、不要加引号、不要写‘提示词’或‘生成结果’。"
        + ("动态要结合当前时间和提示中的主题方向，避免模板化，可在生活趣事、思考感悟、原作剧情、热点观点、天气季节、学习发现之间自然变化。" if kind == "post" else "")
        + ("动态必须优先采用提示中明确提供的一条事实或最新消息，并保留必要的来源/据报道表述；只能依据原文，不得补写新闻细节。没有可靠事实时不要编造新闻、日期、人物行动或亲身经历，也不要用‘今天看到/窗边发现’等虚构亲历替代事实。" if kind == "post" else "")
        + ("正文控制在 20-120 字，适合 QQ 空间动态。" if kind == "post" else "正文控制在 1-80 字，自然、像真人评论。")
    )
    reply = await engine._reply_with_guarded_api(
        "webui:qzone:generate",
        instruction,
        "主人",
        extra_system=system,
        allow_reply_voice=False,
    )
    reply = engine._finalize_reply("webui:qzone:generate", instruction, reply, strict_quality=False).strip()
    limit = 1000 if kind == "post" else 200
    return {"ok": True, "kind": kind, "content": reply[:limit], "model_name": profile_name, "model_profile_id": str(profile_id or "")}
