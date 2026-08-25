from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from maibot_sdk import (
    API,
    CONFIG_RELOAD_SCOPE_SELF,
    Command,
    Field,
    HomeCard,
    MaiBotPlugin,
    PluginConfigBase,
    Tool,
)
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .storage import QQZoneRepository
from .zone_service import BridgeSettings, QQZoneError, QQZoneService


class BridgeConfig(PluginConfigBase):
    __ui_label__ = "QQ 空间 Bridge"
    __ui_order__ = 10

    enabled: bool = Field(default=False, description="是否启用 QQ 空间能力")
    base_url: str = Field(
        default="http://127.0.0.1:5700",
        description="onebot-qzone HTTP 地址",
        json_schema_extra={"label": "Bridge 地址", "placeholder": "http://127.0.0.1:5700"},
    )
    access_token: str = Field(
        default="",
        description="onebot-qzone Access Token",
        json_schema_extra={"label": "Access Token", "x-widget": "password"},
    )
    timeout_seconds: float = Field(default=10.0, ge=2.0, le=60.0)
    allow_remote: bool = Field(default=False, description="允许连接非本机 Bridge；不推荐")
    include_image_data: bool = Field(default=False, description="读取动态时附带图片 Base64；会显著增大响应")
    post_backend: Literal["qzone_bridge", "napcat"] = Field(
        default="qzone_bridge",
        description="发布后端：qzone_bridge 或 NapCat 原生 send_qzone_msg",
    )
    napcat_base_url: str = Field(default="http://127.0.0.1:3000", description="NapCat OneBot HTTP 地址")
    napcat_access_token: str = Field(
        default="",
        description="NapCat HTTP Access Token",
        json_schema_extra={"label": "NapCat Access Token", "x-widget": "password"},
    )


class SafetyConfig(PluginConfigBase):
    __ui_label__ = "写操作安全"
    __ui_order__ = 20

    allow_llm_like: bool = Field(default=False, description="允许 LLM Tool 直接点赞")
    allow_llm_comment: bool = Field(default=False, description="允许 LLM Tool 直接评论")
    allow_llm_post: bool = Field(default=False, description="允许 LLM Tool 直接发布动态")
    comment_max_chars: int = Field(default=120, ge=1, le=500)
    post_max_chars: int = Field(default=240, ge=20, le=1000)
    daily_post_limit: int = Field(default=2, ge=1, le=20)
    default_visibility: Literal[0, 1, 2] = Field(
        default=1,
        description="0=所有人，1=好友，2=仅自己",
    )


class ProactiveConfig(PluginConfigBase):
    __ui_label__ = "自主发布与互动"
    __ui_order__ = 30

    enabled: bool = Field(default=False, description="允许亚托莉按计划生成并发布动态")
    schedule_hours: str = Field(default="9,18,22", description="允许发布的本地小时，逗号分隔")
    schedule_minute: int = Field(default=0, ge=0, le=59, description="计划发布分钟")
    timezone: str = Field(default="Asia/Shanghai")
    minimum_interval_minutes: int = Field(default=360, ge=30, le=10080)
    source_stream_ids: list[str] = Field(
        default_factory=list,
        description="用于生成动态的聊天流 ID；为空时从最近 QQ 聊天流中选择",
    )
    max_source_streams: int = Field(default=3, ge=1, le=10)
    context_messages_per_stream: int = Field(default=12, ge=1, le=50)
    persona_name: str = Field(default="亚托莉")
    topic_prompt: str = Field(default="", max_length=200, description="自主发布默认主题")
    content_prompt: str = Field(default="", max_length=500, description="自主发布额外写作要求")
    mood_hint: str = Field(default="", description="可选的当前情绪提示")
    generation_temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    generation_max_tokens: int = Field(default=300, ge=64, le=1000)
    interactions_enabled: bool = Field(default=False, description="允许亚托莉自动判断点赞和评论")
    auto_like_enabled: bool = Field(default=True, description="自主互动时允许点赞")
    auto_comment_enabled: bool = Field(default=True, description="自主互动时允许评论")
    interaction_schedule_hours: str = Field(default="10,19", description="自主互动小时，逗号分隔")
    interaction_schedule_minute: int = Field(default=30, ge=0, le=59, description="自主互动分钟")
    interaction_minimum_interval_minutes: int = Field(default=180, ge=30, le=10080)
    max_likes_per_run: int = Field(default=3, ge=0, le=20)
    max_comments_per_run: int = Field(default=1, ge=0, le=10)
    interaction_feed_limit: int = Field(default=20, ge=1, le=50)
    comment_prompt: str = Field(
        default="友善、简短、像亚托莉本人，不透露私聊或隐私；只有确实有话可说时才评论。",
        max_length=500,
    )
    ignored_user_ids: list[str] = Field(default_factory=list, description="不参与自主互动的 QQ 号")


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class QQZonePluginConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)


class QQZonePlugin(MaiBotPlugin):
    config_model = QQZonePluginConfig

    def __init__(self) -> None:
        super().__init__()
        self.service: QQZoneService | None = None
        self.repository: QQZoneRepository | None = None
        self._scheduler_task: asyncio.Task[None] | None = None

    async def on_load(self) -> None:
        self.repository = QQZoneRepository(self.ctx.paths.data_dir / "qqzone.sqlite3")
        self._rebuild_service()
        self._restart_scheduler()
        self.ctx.logger.info("QQ 空间插件已加载，数据库=%s", self.ctx.paths.data_dir / "qqzone.sqlite3")

    async def on_unload(self) -> None:
        await self._stop_scheduler()
        self.ctx.logger.info("QQ 空间插件已卸载")

    async def on_config_update(
        self,
        scope: str,
        config_data: dict[str, object],
        version: str,
    ) -> None:
        del config_data
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            self._rebuild_service()
            await self._stop_scheduler()
            self._restart_scheduler()
            self.ctx.logger.info("QQ 空间配置已热更新：%s", version)

    def _rebuild_service(self) -> None:
        bridge = self.config.bridge
        self.service = QQZoneService(
            BridgeSettings(
                enabled=bridge.enabled,
                base_url=bridge.base_url.rstrip("/"),
                access_token=bridge.access_token,
                timeout_seconds=bridge.timeout_seconds,
                allow_remote=bridge.allow_remote,
                include_image_data=bridge.include_image_data,
                post_backend=bridge.post_backend,
                napcat_base_url=bridge.napcat_base_url.rstrip("/"),
                napcat_access_token=bridge.napcat_access_token,
            )
        )

    @HomeCard(
        "qqzone",
        title="QQ 动态",
        description="查看好友动态、人工点赞评论和管理亚托莉自主发布",
        content=[
            {"type": "markdown", "content": "通过本机 **onebot-qzone** 管理 QQ 空间。写操作默认需要人工触发。"},
            {"type": "actions", "actions": [{"label": "打开 QQ 动态", "url": "/api/webui/qqzone/page"}]},
        ],
        link_url="/api/webui/qqzone/page",
        link_label="打开模块",
        icon="message-circle",
        width="medium",
        order=120,
    )
    async def qqzone_home_card(self) -> None:
        return None

    # ---------------------------- LLM Tools ----------------------------

    @Tool(
        "get_feeds",
        description="读取 QQ 空间好友动态。user_id 为空时读取好友动态流；填写 QQ 号时读取该用户的说说。只读操作。",
        parameters=[
            ToolParameterInfo(
                name="user_id",
                param_type=ToolParamType.STRING,
                description="可选的目标 QQ 号；空字符串表示好友动态流",
                required=False,
                default="",
            ),
            ToolParameterInfo(
                name="limit",
                param_type=ToolParamType.INTEGER,
                description="返回数量，1-50",
                required=False,
                default=20,
            ),
        ],
    )
    async def tool_get_feeds(self, user_id: str = "", limit: int = 20, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        feeds = await self._get_feeds(user_id, limit)
        return {"success": True, "feeds": feeds}

    @Tool(
        "like_feed",
        description="点赞一条 QQ 空间动态。这是有副作用的操作，仅在用户明确要求时调用，并受 allow_llm_like 配置控制。",
        parameters=[
            ToolParameterInfo(name="user_id", param_type=ToolParamType.STRING, description="动态作者 QQ", required=True),
            ToolParameterInfo(name="tid", param_type=ToolParamType.STRING, description="动态 tid", required=True),
        ],
    )
    async def tool_like_feed(self, user_id: str, tid: str, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self._assert_llm_write("like")
        return await self._like(user_id, tid, source="llm")

    @Tool(
        "comment_feed",
        description="评论一条 QQ 空间动态。这是有副作用的公开社交操作，仅在用户明确要求并给出评论内容时调用。",
        parameters=[
            ToolParameterInfo(name="user_id", param_type=ToolParamType.STRING, description="动态作者 QQ", required=True),
            ToolParameterInfo(name="tid", param_type=ToolParamType.STRING, description="动态 tid", required=True),
            ToolParameterInfo(name="content", param_type=ToolParamType.STRING, description="要发布的评论原文", required=True),
        ],
    )
    async def tool_comment_feed(self, user_id: str, tid: str, content: str, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self._assert_llm_write("comment")
        return await self._comment(user_id, tid, content, source="llm")

    @Tool(
        "post_feed",
        description="发布一条 QQ 空间动态。这是高风险副作用操作，只能在用户明确要求或自主发布策略允许时调用。",
        parameters=[
            ToolParameterInfo(name="content", param_type=ToolParamType.STRING, description="动态正文", required=True),
            ToolParameterInfo(
                name="who_can_see",
                param_type=ToolParamType.INTEGER,
                description="0=所有人，1=好友，2=仅自己",
                required=False,
                default=1,
            ),
        ],
    )
    async def tool_post_feed(self, content: str, who_can_see: int = 1, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self._assert_llm_write("post")
        return await self._post(content, who_can_see, source="llm")

    # -------------------------- WebUI RPC APIs -------------------------

    @API("web_dashboard", description="QQ 动态 WebUI 首页数据", version="1")
    async def web_dashboard(self) -> dict[str, Any]:
        service = self._service()
        status = await service.status()
        friends: list[dict[str, str]] = []
        if status.get("connected"):
            try:
                friends = await service.get_friends()
            except QQZoneError as exc:
                status["friend_error"] = str(exc)
        actions = await asyncio.to_thread(self._repo().recent_actions, 30)
        last_post_at = float(await asyncio.to_thread(self._repo().get_state, "last_post_at", "0") or 0)
        next_schedule_at = ""
        try:
            now = datetime.now(ZoneInfo(self.config.proactive.timezone))
            hours = sorted({int(value) for value in re.findall(r"\d+", self.config.proactive.schedule_hours) if 0 <= int(value) <= 23})
            for day_offset in range(8):
                date_value = now.date() + timedelta(days=day_offset)
                for hour in hours:
                    candidate = datetime(
                        date_value.year,
                        date_value.month,
                        date_value.day,
                        hour,
                        self.config.proactive.schedule_minute,
                        tzinfo=now.tzinfo,
                    )
                    if candidate > now:
                        next_schedule_at = candidate.isoformat()
                        break
                if next_schedule_at:
                    break
        except Exception:
            next_schedule_at = ""
        last_interaction_at = float(
            await asyncio.to_thread(self._repo().get_state, "last_interaction_at", "0") or 0
        )
        next_interaction_at = ""
        try:
            now = datetime.now(ZoneInfo(self.config.proactive.timezone))
            hours = sorted(
                {
                    int(value)
                    for value in re.findall(r"\d+", self.config.proactive.interaction_schedule_hours)
                    if 0 <= int(value) <= 23
                }
            )
            for day_offset in range(8):
                date_value = now.date() + timedelta(days=day_offset)
                for hour in hours:
                    candidate = datetime(
                        date_value.year,
                        date_value.month,
                        date_value.day,
                        hour,
                        self.config.proactive.interaction_schedule_minute,
                        tzinfo=now.tzinfo,
                    )
                    if candidate > now:
                        next_interaction_at = candidate.isoformat()
                        break
                if next_interaction_at:
                    break
        except Exception:
            next_interaction_at = ""
        return {
            "success": True,
            "status": status,
            "friends": friends,
            "actions": actions,
            "default_visibility": self.config.safety.default_visibility,
            "post_max_chars": self.config.safety.post_max_chars,
            "post_backend": self.config.bridge.post_backend,
            "proactive": {
                "enabled": self.config.proactive.enabled,
                "schedule_hours": self.config.proactive.schedule_hours,
                "schedule_minute": self.config.proactive.schedule_minute,
                "timezone": self.config.proactive.timezone,
                "minimum_interval_minutes": self.config.proactive.minimum_interval_minutes,
                "topic_prompt": self.config.proactive.topic_prompt,
                "content_prompt": self.config.proactive.content_prompt,
                "mood_hint": self.config.proactive.mood_hint,
                "generation_temperature": self.config.proactive.generation_temperature,
                "generation_max_tokens": self.config.proactive.generation_max_tokens,
                "daily_limit": self.config.safety.daily_post_limit,
                "today_posts": await asyncio.to_thread(self._repo().count_success_today, "post"),
                "last_post_at": last_post_at,
                "next_schedule_at": next_schedule_at,
                "interactions_enabled": self.config.proactive.interactions_enabled,
                "auto_like_enabled": self.config.proactive.auto_like_enabled,
                "auto_comment_enabled": self.config.proactive.auto_comment_enabled,
                "interaction_schedule_hours": self.config.proactive.interaction_schedule_hours,
                "interaction_schedule_minute": self.config.proactive.interaction_schedule_minute,
                "interaction_minimum_interval_minutes": self.config.proactive.interaction_minimum_interval_minutes,
                "max_likes_per_run": self.config.proactive.max_likes_per_run,
                "max_comments_per_run": self.config.proactive.max_comments_per_run,
                "interaction_feed_limit": self.config.proactive.interaction_feed_limit,
                "comment_prompt": self.config.proactive.comment_prompt,
                "ignored_user_ids": self.config.proactive.ignored_user_ids,
                "today_likes": await asyncio.to_thread(self._repo().count_success_today, "like"),
                "today_comments": await asyncio.to_thread(self._repo().count_success_today, "comment"),
                "last_interaction_at": last_interaction_at,
                "next_interaction_at": next_interaction_at,
            },
        }

    @API("web_feeds", description="QQ 动态 WebUI 读取动态", version="1")
    async def web_feeds(self, user_id: str = "", limit: int = 20) -> dict[str, Any]:
        return {"success": True, "feeds": await self._get_feeds(user_id, limit)}

    @API("web_like", description="QQ 动态 WebUI 人工点赞", version="1")
    async def web_like(self, user_id: str, tid: str) -> dict[str, Any]:
        return await self._like(user_id, tid, source="webui")

    @API("web_comment", description="QQ 动态 WebUI 人工评论", version="1")
    async def web_comment(self, user_id: str, tid: str, content: str) -> dict[str, Any]:
        return await self._comment(user_id, tid, content, source="webui")

    @API("web_post", description="QQ 动态 WebUI 人工发布", version="1")
    async def web_post(
        self,
        content: str,
        who_can_see: int = 1,
        draft_id: int = 0,
    ) -> dict[str, Any]:
        result = await self._post(content, who_can_see, source="webui")
        if draft_id:
            await asyncio.to_thread(self._repo().mark_draft_published, draft_id, result.get("tid", ""))
        return result

    @API("web_generate", description="根据近期记忆和情绪生成动态草稿", version="1")
    async def web_generate(self, topic: str = "") -> dict[str, Any]:
        return await self.generate_autonomous_post(topic=topic, trigger="webui")

    @API("web_autopost", description="让亚托莉根据记忆生成并立即发布动态", version="1")
    async def web_autopost(self, topic: str = "") -> dict[str, Any]:
        draft = await self.generate_autonomous_post(topic=topic, trigger="webui_autopost")
        result = await self._post(draft["content"], self.config.safety.default_visibility, source="webui_autopost")
        await asyncio.to_thread(self._repo().mark_draft_published, draft["draft_id"], result.get("tid", ""))
        return {**result, "draft_id": draft["draft_id"], "mood": draft["mood"], "content": draft["content"]}

    @API("web_interact_now", description="让亚托莉读取好友动态并自主判断点赞或评论", version="1")
    async def web_interact_now(self) -> dict[str, Any]:
        return await self._run_scheduled_interactions(trigger="webui_interact")

    @Command(
        "qqzone_preview",
        description="生成一条 QQ 空间动态草稿，不直接发布",
        pattern=r"^/(?:动态预览|qqzone-preview)(?:\s+(.+))?$",
    )
    async def command_preview(self, **kwargs: Any) -> tuple[bool, str, int]:
        match = kwargs.get("match")
        topic = str(match.group(1) if match and match.lastindex else "").strip()
        result = await self.generate_autonomous_post(topic=topic, trigger="command")
        text = f"动态草稿 #{result['draft_id']}：\n{result['content']}\n\n请到 WebUI 的 QQ 动态页确认发布。"
        stream_id = str(kwargs.get("stream_id") or "")
        if stream_id:
            await self.ctx.send.text(text, stream_id)
        return True, text, 2

    # ----------------------------- domain ------------------------------

    async def _get_feeds(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        feeds = await self._service().get_feeds(user_id, max(1, min(50, int(limit))))
        await asyncio.to_thread(self._repo().cache_feeds, feeds)
        return feeds

    async def _resolve_feed(self, user_id: str, tid: str) -> dict[str, Any]:
        user = str(user_id or "").strip()
        feed_id = str(tid or "").strip()
        if not feed_id:
            raise ValueError("缺少动态 tid")
        cached = await asyncio.to_thread(self._repo().find_feed, user, feed_id)
        if cached:
            return cached
        feeds = await self._get_feeds(user, 50)
        for feed in feeds:
            if str(feed.get("tid")) == feed_id:
                return feed
        raise ValueError("未找到该动态，请先刷新动态列表")

    async def _like(self, user_id: str, tid: str, *, source: str) -> dict[str, Any]:
        feed = await self._resolve_feed(user_id, tid)
        try:
            result = await self._service().like_feed(feed)
        except Exception as exc:
            await self._record_failure("like", feed, "", source, exc)
            raise
        await asyncio.to_thread(
            self._repo().record_action,
            "like",
            owner_uin=str(feed.get("user_id") or user_id),
            tid=str(tid),
            source=source,
        )
        return {"success": True, **result}

    async def _comment(self, user_id: str, tid: str, content: str, *, source: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("评论不能为空")
        if len(text) > self.config.safety.comment_max_chars:
            raise ValueError(f"评论最多 {self.config.safety.comment_max_chars} 字")
        feed = await self._resolve_feed(user_id, tid)
        try:
            result = await self._service().comment_feed(feed, text)
        except Exception as exc:
            await self._record_failure("comment", feed, text, source, exc)
            raise
        await asyncio.to_thread(
            self._repo().record_action,
            "comment",
            owner_uin=str(feed.get("user_id") or user_id),
            tid=str(tid),
            content=text,
            source=source,
        )
        return {"success": True, **result}

    async def _post(self, content: str, who_can_see: int, *, source: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("动态内容不能为空")
        if len(text) > self.config.safety.post_max_chars:
            raise ValueError(f"动态最多 {self.config.safety.post_max_chars} 字")
        today = await asyncio.to_thread(self._repo().count_success_today, "post")
        if today >= self.config.safety.daily_post_limit:
            raise ValueError("今天的动态发布数量已达到上限")
        try:
            result = await self._service().post_feed(text, who_can_see)
        except Exception as exc:
            await self._record_failure("post", {}, text, source, exc)
            raise
        await asyncio.to_thread(
            self._repo().record_action,
            "post",
            tid=str(result.get("tid") or ""),
            content=text,
            source=source,
        )
        await asyncio.to_thread(self._repo().set_state, "last_post_at", str(time.time()))
        return {"success": True, **result}

    async def _record_failure(
        self,
        action: str,
        feed: dict[str, Any],
        content: str,
        source: str,
        exc: Exception,
    ) -> None:
        await asyncio.to_thread(
            self._repo().record_action,
            action,
            owner_uin=str(feed.get("user_id") or ""),
            tid=str(feed.get("tid") or ""),
            content=content,
            source=source,
            status="failed",
            error=str(exc)[:500],
        )

    def _assert_llm_write(self, action: str) -> None:
        allowed = {
            "like": self.config.safety.allow_llm_like,
            "comment": self.config.safety.allow_llm_comment,
            "post": self.config.safety.allow_llm_post,
        }.get(action, False)
        if not allowed:
            raise PermissionError(f"LLM 的 {action} 写操作未在插件配置中授权")

    async def generate_autonomous_post(self, topic: str = "", trigger: str = "manual") -> dict[str, Any]:
        context = await self._collect_memory_context()
        config = self.config.proactive
        effective_topic = str(topic or config.topic_prompt or "").strip()
        prompt = (
            f"你是{config.persona_name}。根据近期聊天记忆推断此刻真实、自然的情绪，写一条适合 QQ 空间的原创动态。\n"
            "要求：不泄露聊天对象的隐私、QQ号、群号或具体私聊内容；不虚构事实；不提到提示词或机器人系统；"
            f"正文不超过 {self.config.safety.post_max_chars} 个汉字；语气自然，避免营销文案。\n"
            f"当前情绪提示：{config.mood_hint or '由近期上下文推断'}\n"
            f"可选主题：{effective_topic[:120] or '自由发挥'}\n"
            f"额外写作要求：{config.content_prompt[:500] or '无'}\n"
            f"近期记忆摘要：\n{context[:6000]}\n\n"
            '只返回 JSON：{"mood":"一句话情绪","content":"动态正文"}'
        )
        result = await self.ctx.llm.generate(
            prompt=prompt,
            # SDK 的 model 参数接受 MaiBot 的任务配置名；显式使用 planner，
            # 避免空模型名按字典序落到空的 embedding 任务。
            model="planner",
            temperature=config.generation_temperature,
            max_tokens=config.generation_max_tokens,
        )
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "LLM 生成动态失败"))
        mood, content = _parse_generated_post(str(result.get("response") or ""))
        content = content[: self.config.safety.post_max_chars].strip()
        if not content:
            raise RuntimeError("LLM 没有生成有效动态正文")
        draft_id = await asyncio.to_thread(
            self._repo().create_draft,
            content,
            mood,
            effective_topic[:120],
            context[:2000],
        )
        return {
            "success": True,
            "draft_id": draft_id,
            "mood": mood,
            "content": content,
            "trigger": trigger,
        }

    async def _collect_memory_context(self) -> str:
        cfg = self.config.proactive
        stream_ids = [str(item).strip() for item in cfg.source_stream_ids if str(item).strip()]
        if not stream_ids:
            streams = await self.ctx.chat.get_all_streams("qq")
            if isinstance(streams, list):
                for item in streams:
                    if isinstance(item, dict):
                        value = item.get("stream_id") or item.get("id") or item.get("chat_id")
                    else:
                        value = item
                    if value:
                        stream_ids.append(str(value))
                    if len(stream_ids) >= cfg.max_source_streams:
                        break
        chunks: list[str] = []
        for stream_id in stream_ids[: cfg.max_source_streams]:
            try:
                messages = await self.ctx.message.get_recent(
                    stream_id,
                    cfg.context_messages_per_stream,
                )
                readable = await self.ctx.message.build_readable(
                    messages,
                    replace_bot_name=True,
                    timestamp_mode="relative",
                    truncate=True,
                )
            except Exception as exc:
                self.ctx.logger.warning("读取动态生成上下文失败 stream=%s: %s", stream_id, exc)
                continue
            if readable:
                chunks.append(f"[聊天流 {stream_id}]\n{readable}")
        return "\n\n".join(chunks) or "暂无可用的近期聊天记忆，请写一条克制的日常感想。"

    # ---------------------------- scheduler ----------------------------

    def _restart_scheduler(self) -> None:
        if self.config.proactive.enabled or self.config.proactive.interactions_enabled:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop(), name="qqzone-proactive")

    async def _stop_scheduler(self) -> None:
        task = self._scheduler_task
        self._scheduler_task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                await self._run_scheduled_post_if_due()
                await self._run_scheduled_interactions_if_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ctx.logger.error("QQ 空间自主发布检查失败：%s", exc)

    async def _run_scheduled_post_if_due(self) -> None:
        cfg = self.config.proactive
        if not cfg.enabled:
            return
        try:
            now = datetime.now(ZoneInfo(cfg.timezone))
        except Exception:
            now = datetime.now()
        hours = {
            int(value)
            for value in re.findall(r"\d+", cfg.schedule_hours)
            if 0 <= int(value) <= 23
        }
        if now.hour not in hours or now.minute != cfg.schedule_minute:
            return
        slot = f"{now:%Y-%m-%d}-{now.hour:02d}"
        if await asyncio.to_thread(self._repo().get_state, "last_schedule_slot", "") == slot:
            return
        last_post = float(await asyncio.to_thread(self._repo().get_state, "last_post_at", "0") or 0)
        if time.time() - last_post < cfg.minimum_interval_minutes * 60:
            return
        today = await asyncio.to_thread(self._repo().count_success_today, "post")
        if today >= self.config.safety.daily_post_limit:
            return
        draft = await self.generate_autonomous_post(topic=cfg.topic_prompt, trigger="scheduler")
        result = await self._post(
            draft["content"],
            self.config.safety.default_visibility,
            source="scheduler",
        )
        await asyncio.to_thread(self._repo().mark_draft_published, draft["draft_id"], result.get("tid", ""))
        await asyncio.to_thread(self._repo().set_state, "last_schedule_slot", slot)
        self.ctx.logger.info("亚托莉已自主发布 QQ 动态 tid=%s", result.get("tid") or "unknown")

    async def _run_scheduled_interactions_if_due(self) -> None:
        cfg = self.config.proactive
        if not cfg.interactions_enabled:
            return
        try:
            now = datetime.now(ZoneInfo(cfg.timezone))
        except Exception:
            now = datetime.now()
        hours = {
            int(value)
            for value in re.findall(r"\d+", cfg.interaction_schedule_hours)
            if 0 <= int(value) <= 23
        }
        if now.hour not in hours or now.minute != cfg.interaction_schedule_minute:
            return
        slot = f"{now:%Y-%m-%d}-{now.hour:02d}"
        if await asyncio.to_thread(self._repo().get_state, "last_interaction_slot", "") == slot:
            return
        last_interaction = float(
            await asyncio.to_thread(self._repo().get_state, "last_interaction_at", "0") or 0
        )
        if time.time() - last_interaction < cfg.interaction_minimum_interval_minutes * 60:
            return
        await self._run_scheduled_interactions(trigger="scheduler")
        await asyncio.to_thread(self._repo().set_state, "last_interaction_slot", slot)

    async def _run_scheduled_interactions(self, *, trigger: str) -> dict[str, Any]:
        cfg = self.config.proactive
        if not cfg.auto_like_enabled and not cfg.auto_comment_enabled:
            return {"success": True, "likes": [], "comments": [], "skipped": "点赞和评论均已关闭"}
        feeds = await self._get_feeds("", cfg.interaction_feed_limit)
        ignored = {str(value).strip() for value in cfg.ignored_user_ids if str(value).strip()}
        candidate_feeds = [
            feed
            for feed in feeds
            if str(feed.get("user_id") or "").strip() not in ignored
            and str(feed.get("tid") or "").strip()
        ]
        if not candidate_feeds:
            return {"success": True, "likes": [], "comments": [], "skipped": "没有可互动的动态"}
        feed_by_tid = {str(feed["tid"]): feed for feed in candidate_feeds}
        compact = [
            {
                "tid": str(feed.get("tid")),
                "user_id": str(feed.get("user_id") or ""),
                "nickname": str(feed.get("nickname") or ""),
                "content": str(feed.get("content") or "")[:300],
                "time": str(feed.get("time_text") or feed.get("abstime") or ""),
                "liked": bool(feed.get("liked")),
            }
            for feed in candidate_feeds
        ]
        prompt = (
            f"你是{cfg.persona_name}，正在谨慎浏览好友 QQ 空间动态。请根据动态内容决定是否点赞或评论。\n"
            "不要泄露隐私，不要对广告、争议、悲伤或明显不适合互动的内容发表评论；没有合适内容就返回空数组。"
            f"最多点赞 {cfg.max_likes_per_run} 条，最多评论 {cfg.max_comments_per_run} 条；评论要求：{cfg.comment_prompt or '友善简短'}\n"
            '只返回 JSON：{"likes":[{"tid":"动态tid"}],"comments":[{"tid":"动态tid","content":"评论"}]}\n'
            f"动态列表：\n{json.dumps(compact, ensure_ascii=False)}"
        )
        result = await self.ctx.llm.generate(
            prompt=prompt,
            model="planner",
            temperature=min(1.0, max(0.0, cfg.generation_temperature)),
            max_tokens=min(800, max(128, cfg.generation_max_tokens)),
        )
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "LLM 互动判断失败"))
        decision = _parse_interaction_decision(str(result.get("response") or ""))
        likes: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        if cfg.auto_like_enabled:
            for item in decision.get("likes", [])[: cfg.max_likes_per_run]:
                tid = str(item.get("tid") or "").strip()
                feed = feed_by_tid.get(tid)
                if not feed or bool(feed.get("liked")):
                    continue
                if await asyncio.to_thread(self._repo().has_successful_action, "like", tid):
                    continue
                try:
                    likes.append(await self._like(str(feed.get("user_id") or ""), tid, source=trigger))
                except Exception as exc:
                    self.ctx.logger.warning("自主点赞失败 tid=%s: %s", tid, exc)
        if cfg.auto_comment_enabled:
            for item in decision.get("comments", [])[: cfg.max_comments_per_run]:
                tid = str(item.get("tid") or "").strip()
                content = str(item.get("content") or "").strip()[: self.config.safety.comment_max_chars]
                feed = feed_by_tid.get(tid)
                if not feed or not content:
                    continue
                if await asyncio.to_thread(self._repo().has_successful_action, "comment", tid):
                    continue
                try:
                    comments.append(
                        await self._comment(str(feed.get("user_id") or ""), tid, content, source=trigger)
                    )
                except Exception as exc:
                    self.ctx.logger.warning("自主评论失败 tid=%s: %s", tid, exc)
        await asyncio.to_thread(self._repo().set_state, "last_interaction_at", str(time.time()))
        return {"success": True, "likes": likes, "comments": comments, "trigger": trigger}

    def _service(self) -> QQZoneService:
        if self.service is None:
            raise RuntimeError("QQ 空间服务尚未初始化")
        return self.service

    def _repo(self) -> QQZoneRepository:
        if self.repository is None:
            raise RuntimeError("QQ 空间数据库尚未初始化")
        return self.repository


def _parse_generated_post(raw: str) -> tuple[str, str]:
    value = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.S | re.I)
    candidate = fenced.group(1) if fenced else value
    parsed: Any = None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        object_match = re.search(r"\{.*\}", candidate, re.S)
        if object_match:
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads(object_match.group(0))
    if isinstance(parsed, dict):
        return str(parsed.get("mood") or "平静").strip(), str(parsed.get("content") or "").strip()
    return "平静", value.strip().strip('"')


def _parse_interaction_decision(raw: str) -> dict[str, list[dict[str, Any]]]:
    """Parse the small JSON contract used by autonomous like/comment decisions."""
    value = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.S | re.I)
    candidate = fenced.group(1) if fenced else value
    parsed: Any = None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        object_match = re.search(r"\{.*\}", candidate, re.S)
        if object_match:
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads(object_match.group(0))
    if not isinstance(parsed, dict):
        return {"likes": [], "comments": []}
    likes = parsed.get("likes") if isinstance(parsed.get("likes"), list) else []
    comments = parsed.get("comments") if isinstance(parsed.get("comments"), list) else []
    return {
        "likes": [item for item in likes if isinstance(item, dict)],
        "comments": [item for item in comments if isinstance(item, dict)],
    }


def create_plugin() -> QQZonePlugin:
    return QQZonePlugin()
