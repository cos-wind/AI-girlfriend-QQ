"""MaiBot 主进程侧 WebUI 适配器。

此模块只由 MaiBot WebUI 主进程导入。业务代码仍运行在隔离插件 Runner 中，
所有调用都通过插件 API RPC 完成。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.plugin_runtime.integration import get_plugin_runtime_manager
from src.webui.dependencies import require_auth
from src.webui.utils.toml_utils import save_toml_with_format


PLUGIN_ID = "atri.qqzone"
router = APIRouter(
    prefix="/qqzone",
    tags=["QQ动态"],
    dependencies=[Depends(require_auth)],
)


class FeedQuery(BaseModel):
    user_id: str = ""
    limit: int = Field(default=20, ge=1, le=50)


class FeedTarget(BaseModel):
    user_id: str = Field(min_length=5, max_length=20)
    tid: str = Field(min_length=1, max_length=200)


class CommentRequest(FeedTarget):
    content: str = Field(min_length=1, max_length=500)


class PostRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    visibility: int = Field(default=1, ge=0, le=2)
    draft_id: int | None = None


class GenerateRequest(BaseModel):
    topic: str = Field(default="", max_length=200)


class AutoPostRequest(BaseModel):
    topic: str = Field(default="", max_length=200)
    confirm: bool = False


class AutoInteractRequest(BaseModel):
    confirm: bool = True


class SettingsRequest(BaseModel):
    """QQ 动态自主发布设置；省略字段表示保持原值。"""

    enabled: bool | None = None
    schedule_hours: str | None = Field(default=None, max_length=100)
    schedule_minute: int | None = Field(default=None, ge=0, le=59)
    timezone: str | None = Field(default=None, max_length=80)
    minimum_interval_minutes: int | None = Field(default=None, ge=30, le=10080)
    daily_post_limit: int | None = Field(default=None, ge=1, le=20)
    default_visibility: int | None = Field(default=None, ge=0, le=2)
    topic_prompt: str | None = Field(default=None, max_length=200)
    content_prompt: str | None = Field(default=None, max_length=500)
    mood_hint: str | None = Field(default=None, max_length=500)
    generation_temperature: float | None = Field(default=None, ge=0, le=2)
    generation_max_tokens: int | None = Field(default=None, ge=64, le=1000)
    interactions_enabled: bool | None = None
    auto_like_enabled: bool | None = None
    auto_comment_enabled: bool | None = None
    interaction_schedule_hours: str | None = Field(default=None, max_length=100)
    interaction_schedule_minute: int | None = Field(default=None, ge=0, le=59)
    interaction_minimum_interval_minutes: int | None = Field(default=None, ge=30, le=10080)
    max_likes_per_run: int | None = Field(default=None, ge=0, le=20)
    max_comments_per_run: int | None = Field(default=None, ge=0, le=10)
    interaction_feed_limit: int | None = Field(default=None, ge=1, le=50)
    comment_prompt: str | None = Field(default=None, max_length=500)
    ignored_user_ids: list[str] | None = None


async def _invoke(component_name: str, args: dict[str, Any] | None = None) -> Any:
    manager = get_plugin_runtime_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="MaiBot 插件运行时尚未启动")

    supervisors = list(getattr(manager, "supervisors", ()) or ())
    for supervisor in supervisors:
        registered = getattr(supervisor, "_registered_plugins", {})
        if PLUGIN_ID not in registered:
            continue
        try:
            response = await supervisor.invoke_api(
                plugin_id=PLUGIN_ID,
                component_name=component_name,
                args=args or {},
                timeout_ms=120_000,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"QQ动态插件调用失败：{exc}") from exc

        if getattr(response, "error", None):
            error = response.error
            message = error.get("message", "插件 API 调用失败") if isinstance(error, dict) else str(error)
            raise HTTPException(status_code=502, detail=message)

        payload = response.payload if isinstance(getattr(response, "payload", None), dict) else {}
        if not payload.get("success", False):
            raise HTTPException(status_code=400, detail=str(payload.get("result") or "插件操作失败"))
        return payload.get("result")

    raise HTTPException(status_code=503, detail="ATRI QQ动态插件未加载，请检查插件状态")


@router.get("/page", response_class=HTMLResponse)
async def qqzone_page() -> HTMLResponse:
    page = Path(__file__).with_name("webui") / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="QQ动态 WebUI 模板缺失")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@router.get("/dashboard")
async def dashboard() -> Any:
    return await _invoke("web_dashboard")


@router.post("/feeds")
async def feeds(request: FeedQuery) -> Any:
    return await _invoke("web_feeds", request.model_dump())


@router.post("/like")
async def like(request: FeedTarget) -> Any:
    return await _invoke("web_like", request.model_dump())


@router.post("/comment")
async def comment(request: CommentRequest) -> Any:
    return await _invoke("web_comment", request.model_dump())


@router.post("/post")
async def post(request: PostRequest) -> Any:
    return await _invoke(
        "web_post",
        {
            "content": request.content,
            "who_can_see": request.visibility,
            "draft_id": request.draft_id or 0,
        },
    )


@router.post("/generate")
async def generate(request: GenerateRequest) -> Any:
    return await _invoke("web_generate", request.model_dump())


@router.post("/autopost")
async def autopost(request: AutoPostRequest) -> Any:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="需要确认后才执行立即发布")
    return await _invoke("web_autopost", request.model_dump())


@router.post("/interact")
async def interact(request: AutoInteractRequest) -> Any:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="需要确认后才执行自主互动")
    return await _invoke("web_interact_now")


@router.put("/settings")
async def update_settings(request: SettingsRequest) -> Any:
    """保存 QQ 动态详细配置，并立即通知插件热更新。"""

    manager = get_plugin_runtime_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="MaiBot 插件运行时尚未启动")
    config_path = Path(__file__).with_name("config.toml")
    if not config_path.is_file():
        raise HTTPException(status_code=500, detail="QQ动态插件配置文件不存在")
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            config_data = tomlkit.load(handle).unwrap()
        if not isinstance(config_data, dict):
            raise ValueError("插件配置格式无效")
        proactive = config_data.setdefault("proactive", {})
        safety = config_data.setdefault("safety", {})
        if not isinstance(proactive, dict) or not isinstance(safety, dict):
            raise ValueError("插件配置节格式无效")
        payload = request.model_dump(exclude_none=True)
        safety_keys = {"daily_post_limit", "default_visibility"}
        for key, value in payload.items():
            (safety if key in safety_keys else proactive)[key] = value
        validated = await manager.validate_plugin_config(PLUGIN_ID, config_data)
        if isinstance(validated, dict):
            config_data = validated
        save_toml_with_format(config_data, str(config_path))
        await manager.notify_plugin_config_updated(PLUGIN_ID, config_data=config_data)
        return {"success": True, "message": "配置已保存并热更新"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存 QQ动态配置失败：{exc}") from exc
