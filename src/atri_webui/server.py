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
import sqlite3
import subprocess
import sys
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
from atri_qq_bot.proactive import (
    load_proactive_policy,
    persist_tiers_from_payload,
    save_proactive_policy,
)
from atri_qq_bot.runtime import (
    LOG_DIR,
    PROJECT_ROOT,
    STICKER_DELETED_DIR,
    STICKER_ROOT,
    read_project_logs,
)
from atri_qq_bot.music import song_catalog, save_song
from atri_qq_bot.runtime.paths import MUSIC_ROOT
from atri_qq_bot.insights import (
    group_summary_html,
    group_summary_image_path,
    render_group_summary_image,
    save_insights_env,
    summary_markdown,
)
from atri_qq_bot.insights.evaluation import EvaluationSample
from atri_qq_bot.voice import (
    VoicePromptContext,
    VoiceRequest,
    load_voice_behavior,
    save_voice_behavior,
)
from atri_qq_bot.runtime.control import restart_background_services, runtime_status
from atri_qq_bot.runtime.modality_access import load_modality_access, save_modality_access
from atri_qq_bot.runtime.reply_strategy import (
    counter_snapshot,
    load_reply_strategy,
    preview_limits,
    reset_reply_counters,
    save_reply_strategy,
    update_object_rule,
)
from .config_admin import config_payload, update_env
from . import account_view
from atri_qq_bot.accounts import (
    qq_from_account_id,
    resolve_account,
    resolve_config,
)
# QQ空间 Bridge 改由 WebUI 手动启停（默认不随桌宠/NapCat 启动）。
from .qzone_bridge_control import bridge_status, start_bridge, stop_bridge
from .napcat_account import (
    begin_account_switch,
    cancel_account_switch,
    finish_account_switch,
    napcat_login_state,
)
from .service_control import (
    music_workbench_status,
    start_music_workbench,
    start_voice_service,
    stop_voice_service,
    voice_service_status,
)
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
from .page import index as _page_module

_PAGE_DIR = Path(__file__).with_name("page")
_PAGE_MODULE_PATH = _PAGE_DIR / "index.py"
_PAGE_RELOAD_LOCK = threading.Lock()
_PAGE_MODULE_MTIME_NS = 0


def _page_signature() -> int:
    """页面目录里最新一次改动的时间戳。

    页面 PART 都是常量字符串，任何 ``page/*.py`` 改动都应该刷新浏览器即可看到。
    过去只盯 ``index.py``：改 body/script 部分时 mtime 不变，而且 PART 模块被缓存在
    ``sys.modules`` 里，只 reload index 也拿不到新内容（界面改动因此必须重启进程）。
    """

    latest = 0
    try:
        candidates = list(_PAGE_DIR.glob("*.py"))
    except OSError:
        return 0
    for path in candidates:
        try:
            latest = max(latest, path.stat().st_mtime_ns)
        except OSError:
            continue
    return latest


def _reload_page_modules() -> None:
    """先重载各 PART 模块，再重载 index，让页面字符串真正更新。"""

    importlib.invalidate_caches()
    index_name = _page_module.__name__
    package = index_name.rsplit(".", 1)[0]
    for name, module in list(sys.modules.items()):
        if name.startswith(f"{package}.") and name != index_name:
            try:
                importlib.reload(module)
            except Exception:  # pragma: no cover - 单页模块坏了不应该拖垮面板
                LOGGER.exception("页面模块重载失败：%s", name)
    importlib.reload(_page_module)


def _render_index_dynamic() -> str:
    """Render the WebUI with a lightweight source-mtime reload.

    The desktop WebUI is local-only and frequently edited during development.
    Reloading the presentation modules on request means a browser refresh is
    enough to pick up HTML/CSS/JS changes; API/service changes still require a
    normal process restart.
    """
    global _PAGE_MODULE_MTIME_NS
    signature = _page_signature()
    if signature and signature != _PAGE_MODULE_MTIME_NS:
        with _PAGE_RELOAD_LOCK:
            if signature != _PAGE_MODULE_MTIME_NS:
                _reload_page_modules()
                _PAGE_MODULE_MTIME_NS = signature
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
    asr_lexicon_text,
    resolve_voice_audio,
    save_asr_lexicon_text,
    save_reference_audio,
    save_test_audio,
    save_tts_pronunciation_text,
    save_voice_profile,
    tts_pronunciation_text,
    voice_candidates_payload,
    voice_profiles_payload,
)

MAX_UPLOAD_BYTES = 8_000_000
MAX_VOICE_UPLOAD_BYTES = 30_000_000
MAX_COMPLETE_MUSIC_UPLOAD_BYTES = 180_000_000
LOGGER = logging.getLogger("atri.webui")

# WebUI 是本地运维面板，不承载对话主循环。API 管理配置、记忆、日志和音频资源；
# QQ 连接仍由 OneBot 进程管理，避免浏览器请求直接触碰 QQ 状态。
#
# 歌曲合成工作流已迁出到独立的 AI_music 项目：本模块不再持有它的桥接地址、
# 素材目录或工程目录，只在「测试」页提供入口与只读探活（见 service_control）。


from .server_parts.voice_integrations import (
    _TRANSLATION_LANGUAGES,
    _detect_translation_source,
    _extract_translation,
    _voice_preview_synthesis_options,
    _voice_preview_synthesis_options_for_mode,
    translate_voice_text,
)


def _read_qzone_targets(path: Path) -> list[dict[str, Any]]:
    """只读打开指定 QQ 空间库的互动对象名单。

    用 ``mode=ro``：查看别的账号不该顺手创建它的库。库不存在或读不出来时返回空表，
    因为"这个账号还没有互动名单"和"读失败"在只读检视里的表现应该一致：空。
    """
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return []
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM qzone_targets ORDER BY nickname,user_id"
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        connection.close()


class WebUIState:
    def __init__(self, config: BotConfig, server: Any) -> None:
        self.config = config
        self.server = server
        self.lock = asyncio.Lock()
        self.group_name_lock = asyncio.Lock()
        self.group_name_refresh_submit_lock = threading.Lock()
        self._group_name_refresh_at = 0.0
        self._group_name_refresh_pending = False
        self.memory_admin = memory_admin_for_config(config)
        database = Path(os.getenv("QZONE_AUTOMATION_DB", "data/qzone_automation.sqlite3"))
        self.qzone_automation = QZoneAutomation(
            QZoneAutomationStore(database),
            lambda: QZoneAdmin(
                self.running_memory_admin().summary(),
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
        # 查看账号：面板可以手动选一个账号来**看**它的记忆与数据；机器人实际运行
        # 哪个账号仍由 NapCat 决定。选了"不是正在运行的那个"时进入**只读检视模式**，
        # 读路径跟随查看账号、写路径一律拒绝。
        self._view_lock = threading.RLock()
        self._view_memory_admin: tuple[str, Any] | None = None
        self._view_insights_store: tuple[str, Any] | None = None

    # ---- 查看账号 -------------------------------------------------------

    def running_account(self) -> Any | None:
        """机器人**正在运行**的账号（由 OneBot 侧的协调器持有）。"""
        coordinator = getattr(self.server, "account_coordinator", None)
        if coordinator is None:
            return None
        return coordinator.account()

    def running_account_id(self) -> str | None:
        account = self.running_account()
        return account.account_id if account is not None else None

    def view_selection(self) -> str:
        if not bool(getattr(self.config, "account_system_enabled", False)):
            # 账号系统关闭时不存在查看选择，也不该读写选择文件。
            return account_view.AUTO
        return account_view.load_view_selection()

    def set_view_selection(self, value: str) -> str:
        saved = account_view.save_view_selection(value)
        with self._view_lock:
            self._view_memory_admin = None
        LOGGER.info("面板查看账号已设为 %s", saved)
        return saved

    def view_account(self) -> Any | None:
        """面板正在展示的账号；``None`` 表示"用运行账号"。

        账号系统关闭、选择为 ``auto``、或目标账号不存在时都返回 ``None``，
        于是读路径继续用运行账号，行为与今天一致。
        """
        selection = self.view_selection()
        if selection == account_view.AUTO:
            return None
        running = self.running_account()
        if running is not None and running.account_id == selection:
            return None
        try:
            return resolve_account(self.config, qq_from_account_id(selection))
        except ValueError:
            return None

    def is_read_only_view(self) -> bool:
        """面板是否处于只读检视模式。"""
        return account_view.is_read_only(
            self.view_selection(), self.running_account_id()
        )

    def view_config(self) -> Any:
        """读路径应当使用的配置：检视别的账号时是它的账号作用域配置。"""
        account = self.view_account()
        if account is None:
            return self.config
        return resolve_config(self.config, account)

    def _memory_admin_for_account(self, account: Any) -> Any:
        """按账号构造并缓存记忆管理对象（键里带前缀，和查看账号共用同一个缓存槽）。"""

        cache_key = f"memory:{account.account_id}"
        with self._view_lock:
            cached = self._view_memory_admin
            if cached is not None and cached[0] == cache_key:
                return cached[1]
        admin = memory_admin_for_config(resolve_config(self.config, account))
        with self._view_lock:
            self._view_memory_admin = (cache_key, admin)
        return admin

    def running_memory_admin(self) -> Any:
        """**正在运行的账号**的记忆管理对象；没有账号介入时回落到进程默认。

        写路径必须用它：``self.memory_admin`` 是进程启动时按默认账号（``BOT_QQ``）
        建的，换了 NapCat 登录号之后它还指向旧账号——那样在面板里保存/删除记忆会写进
        旧账号的数据区。
        """

        account = self.running_account()
        if account is None:
            return self.memory_admin
        return self._memory_admin_for_account(account)

    def view_memory_admin(self) -> Any:
        """读路径应当使用的记忆管理对象；按账号缓存，避免每次请求重建。

        ``auto``（跟随运行账号）→ **运行账号**的记忆。以前这里直接返回
        ``self.memory_admin``（进程默认账号），于是切换 NapCat 登录号之后用户中心
        还是原账号的人——那是 bug。
        """

        account = self.view_account()
        if account is None:
            return self.running_memory_admin()
        return self._memory_admin_for_account(account)

    def view_insights_store(self) -> Any:
        """读路径应当使用的评测库。

        - ``auto``（查看 = 运行）→ **运行账号**的 ``InsightsStore``。进程级 runtime
          只有在它就是指向这个账号的库时才复用——它是进程启动时按默认账号建的，
          换号之后继续用它就会把原账号的群和评测显示出来。
        - 查看别的账号 → 它自己的 ``insights.sqlite3``；**文件不存在时返回 None**
          （该账号还没有评测数据），而不是顺手创建——"看"不该产生副作用。
        """

        account = self.view_account() or self.running_account()
        runtime_store = getattr(getattr(self.server, "insights", None), "store", None)
        if account is None:
            return runtime_store
        from atri_qq_bot.accounts import account_data_paths

        layout = account_data_paths(self.config, account)
        if layout is None:
            return runtime_store
        expected = layout.insights_db_path
        if runtime_store is not None:
            try:
                if Path(getattr(runtime_store, "path", expected)).resolve() == expected.resolve():
                    return runtime_store
            except OSError:  # pragma: no cover - 路径异常时按账号库继续
                pass
        if not expected.is_file():
            return None
        cache_key = f"insights:{account.account_id}"
        with self._view_lock:
            if self._view_insights_store is not None and self._view_insights_store[0] == cache_key:
                return self._view_insights_store[1]
        try:
            from atri_qq_bot.insights.store import InsightsStore

            store = InsightsStore(expected)
        except Exception as exc:  # pragma: no cover - 损坏的库不应该让面板整体报错
            LOGGER.warning("读取查看账号的评测库失败：%s", exc)
            return None
        with self._view_lock:
            self._view_insights_store = (cache_key, store)
        return store

    def effective_account(self) -> Any | None:
        """当前面板与用户目录应当代表的账号：查看别的账号 → 它；否则 → 运行账号。"""

        return self.view_account() or self.running_account()

    def effective_bot_qq(self) -> str:
        """代表"机器人自己"的 QQ。

        跟随运行账号时必须用**运行账号**：否则换号后目录里还会把旧号标成机器人。
        """

        account = self.effective_account()
        if account is not None:
            return str(getattr(account, "qq", "") or "")
        return str(getattr(self.view_config(), "bot_qq", "") or "")

    def view_modality_policy(self) -> dict[str, Any]:
        """读路径应当使用的视觉/语音权限策略。

        跟随**生效账号**：查看别的账号 → 它的文件；auto → 运行账号的文件。账号自己
        的文件不存在时就是**空策略**，不回落到全局——全局那份是原账号的名单
        （实测 232 条），换号后继续用它，用户中心就还是原账号的人。
        默认账号的 ``webui_dir`` 就是全局 ``data/webui``，所以默认行为不变。
        """

        account = self.effective_account()
        if account is None:
            return load_modality_access()
        from atri_qq_bot.accounts import account_data_paths
        from atri_qq_bot.runtime.modality_access import load_modality_access_from

        layout = account_data_paths(self.config, account)
        if layout is None:
            return load_modality_access()
        return load_modality_access_from(layout.webui_dir / "modality_access.json")

    def view_qzone_targets(self) -> list[dict[str, Any]]:
        """读路径应当使用的 QQ 空间互动对象名单。

        同样跟随生效账号：空间互动对象是"当前登录那个号"的名单，用全局库会把原账号
        的目标混进用户中心的群列表。**文件不存在返回空**，且用只读连接打开，
        绝不因为"看"而创建文件。
        """

        account = self.effective_account()
        if account is None:
            return self.qzone_automation.store.targets()
        from atri_qq_bot.accounts import account_data_paths

        layout = account_data_paths(self.config, account)
        if layout is None or not layout.qzone_db_path.is_file():
            return []
        return _read_qzone_targets(layout.qzone_db_path)

    def view_payload(self) -> dict[str, Any]:
        """给面板的查看状态描述（含只读判定与原因）。"""
        selection = self.view_selection()
        running_id = self.running_account_id()
        state = account_view.describe(selection, running_id)
        account = self.view_account()
        state.update(
            {
                "running_account_id": running_id,
                "viewing_account_id": (
                    account.account_id if account is not None else running_id
                ),
                "enabled": bool(
                    getattr(self.config, "account_system_enabled", False)
                ),
            }
        )
        return state

    def log_read_only_refusal(self, action: str) -> None:
        LOGGER.warning(
            "只读检视模式：拒绝执行 %s（查看账号 %s，运行账号 %s）",
            action,
            self.view_selection(),
            self.running_account_id(),
        )

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

    def refresh_group_names_soon(self) -> None:
        """后台刷新群名缓存，绝不阻塞 WebUI 的读取接口。"""
        now = time.monotonic()
        with self.group_name_refresh_submit_lock:
            if self._group_name_refresh_pending or now - self._group_name_refresh_at < 30:
                return
            self._group_name_refresh_pending = True
        try:
            future = asyncio.run_coroutine_threadsafe(self.refresh_group_names(), _main_loop())
        except Exception:
            with self.group_name_refresh_submit_lock:
                self._group_name_refresh_pending = False
            return

        def done(completed: Any) -> None:
            with self.group_name_refresh_submit_lock:
                self._group_name_refresh_pending = False
            with contextlib.suppress(Exception):
                completed.result()

        future.add_done_callback(done)

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
            # 历史 bug：切换聊天模型后没有同步 tools.chat_model / chat_base_url，
            # 导致视觉推理前“卸载聊天模型腾显存”用的仍是旧模型名，显存调度错乱。
            self.server.tools.chat_model = str(new_config.openai_model or "").strip()
            self.server.tools.chat_base_url = str(new_config.openai_base_url or "").rstrip("/")
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
            self.server.tools.vision_max_bytes = int(
                new_config.toolbox_vision_max_bytes
            )
            self.server.tools.vision_retry_count = int(
                new_config.toolbox_vision_retry_count
            )
            self.server.tools.vision_resource_wait_seconds = float(
                new_config.toolbox_vision_resource_wait_seconds
            )
            self.server.tools.vision_timeout_seconds = float(
                new_config.toolbox_vision_timeout_seconds
            )
            self.server.tools.vision_unload_other_ollama_models = bool(
                new_config.toolbox_vision_unload_other_ollama_models
            )
            self.server.tools.ocr_enabled = bool(
                new_config.toolbox_ocr_enabled
            )
            self.server.tools.vision_video_num_predict = int(
                new_config.toolbox_vision_video_num_predict
            )
            self.server.tools.video_frame_analysis_enabled = bool(
                new_config.toolbox_video_frame_analysis_enabled
            )
            self.server.tools.video_max_frames = int(
                new_config.toolbox_video_max_frames
            )
            self.server.tools.video_deadline_seconds = float(
                new_config.toolbox_video_deadline_seconds
            )
            self.server.tools.max_document_bytes = int(
                new_config.toolbox_max_document_bytes
            )
            self.server.tools.max_media_bytes = int(
                new_config.toolbox_max_media_bytes
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


from .server_parts.handler_account import HandlerAccountMixin
from .server_parts.handler_config import HandlerConfigMixin
from .server_parts.handler_core import HandlerCoreMixin
from .server_parts.handler_insights import HandlerInsightsMixin
from .server_parts.handler_qq_music import HandlerQQMusicMixin
from .server_parts.handler_qzone import HandlerQZoneMixin
from .server_parts.handler_response import HandlerResponseMixin
from .server_parts.handler_stickers_memory import HandlerStickersMemoryMixin
from .server_parts.handler_voice import HandlerVoiceMixin
from .server_parts.handler_workbench import HandlerWorkbenchMixin
from .server_parts.handler_knowledge import HandlerKnowledgeMixin


class AtriWebUIHandler(
    HandlerCoreMixin,
    HandlerKnowledgeMixin,
    HandlerConfigMixin,
    HandlerAccountMixin,
    HandlerQQMusicMixin,
    HandlerInsightsMixin,
    HandlerVoiceMixin,
    HandlerStickersMemoryMixin,
    HandlerWorkbenchMixin,
    HandlerQZoneMixin,
    HandlerResponseMixin,
    EvaluationHandlersMixin,
    BaseHTTPRequestHandler,
):
    webui_state: WebUIState


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
