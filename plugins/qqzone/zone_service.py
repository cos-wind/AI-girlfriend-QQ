from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class QQZoneError(RuntimeError):
    """可安全展示给 WebUI 或 Tool 调用方的 QQ 空间错误。"""


@dataclass(frozen=True)
class BridgeSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:5700"
    access_token: str = ""
    timeout_seconds: float = 10.0
    allow_remote: bool = False
    include_image_data: bool = False
    post_backend: str = "qzone_bridge"
    napcat_base_url: str = "http://127.0.0.1:3000"
    napcat_access_token: str = ""

    def validate(self) -> None:
        if not self.enabled:
            raise QQZoneError("QQ 空间 Bridge 未启用")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise QQZoneError("QQ 空间 Bridge URL 无效")
        if not self.allow_remote and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise QQZoneError("QQ 空间 Bridge 默认只允许本机地址")

    def validate_napcat(self) -> None:
        parsed = urlparse(self.napcat_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise QQZoneError("NapCat HTTP URL 无效")
        if not self.allow_remote and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise QQZoneError("NapCat 默认只允许本机地址")


@dataclass(frozen=True)
class ZoneFeed:
    tid: str
    user_id: str
    nickname: str
    content: str
    abstime: int = 0
    time_text: str = ""
    liked: bool = False
    like_count: int = 0
    comment_count: int = 0
    image_count: int = 0
    appid: int = 0
    typeid: int = 0
    unikey: str = ""
    curkey: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QQZoneService:
    """onebot-qzone HTTP Action 的异步封装。"""

    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings

    async def status(self) -> dict[str, Any]:
        try:
            data = await self.action("check_cookie", {"probe": False})
        except QQZoneError as exc:
            return {
                "enabled": self.settings.enabled,
                "connected": False,
                "base_url": self.settings.base_url,
                "error": str(exc),
            }
        payload = data if isinstance(data, dict) else {}
        return {
            "enabled": True,
            "connected": bool(payload.get("valid", True)),
            "base_url": self.settings.base_url,
            "qq": str(payload.get("qq") or ""),
            "error": "" if payload.get("valid", True) else str(payload.get("message") or "Cookie 无效"),
        }

    async def get_friends(self) -> list[dict[str, str]]:
        data = await self.action("get_friend_list", {})
        items = data.get("items", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        friends: list[dict[str, str]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            user_id = str(raw.get("user_id") or raw.get("uin") or "").strip()
            if not user_id:
                continue
            friends.append(
                {
                    "user_id": user_id,
                    "nickname": str(raw.get("nickname") or raw.get("name") or f"QQ {user_id}"),
                    "remark": str(raw.get("remark") or ""),
                    "avatar": str(raw.get("avatar") or ""),
                }
            )
        return friends

    async def get_feeds(self, user_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        count = max(1, min(100, int(limit)))
        if str(user_id or "").strip():
            action = "get_emotion_list"
            params: dict[str, Any] = {
                "user_id": str(user_id).strip(),
                "pos": 0,
                "num": count,
                "max_pages": 3,
                "include_image_data": self.settings.include_image_data,
            }
        else:
            action = "get_friend_feeds"
            params = {
                "num": count,
                "fast_mode": True,
                "include_image_data": self.settings.include_image_data,
            }
        data = await self.action(action, params)
        raw_items = _feed_items(data)
        return [feed.to_dict() for feed in (_normalize_feed(item) for item in raw_items) if feed]

    async def like_feed(self, feed: dict[str, Any]) -> dict[str, Any]:
        tid = _required(feed.get("tid"), "缺少动态 tid")
        result = await self.action(
            "send_like",
            {
                "user_id": str(feed.get("user_id") or ""),
                "tid": tid,
                "abstime": _as_int(feed.get("abstime")),
                "appid": _as_int(feed.get("appid")),
                "typeid": _as_int(feed.get("typeid")),
                "unikey": str(feed.get("unikey") or ""),
                "curkey": str(feed.get("curkey") or ""),
            },
        )
        return {"tid": tid, "result": result}

    async def comment_feed(self, feed: dict[str, Any], content: str) -> dict[str, Any]:
        tid = _required(feed.get("tid"), "缺少动态 tid")
        text = _required(content, "评论不能为空")
        result = await self.action(
            "send_comment",
            {
                "target_uin": str(feed.get("user_id") or ""),
                "target_tid": tid,
                "content": text,
                "appid": _as_int(feed.get("appid")),
                "abstime": _as_int(feed.get("abstime")),
            },
        )
        return {"tid": tid, "content": text, "result": result}

    async def post_feed(self, content: str, who_can_see: int = 1) -> dict[str, Any]:
        text = _required(content, "动态内容不能为空")
        visibility = max(0, min(2, int(who_can_see)))
        if self.settings.post_backend == "napcat":
            self.settings.validate()
            self.settings.validate_napcat()
            # NapCat: 1=所有人、4=好友、64=仅自己。
            ugc_right = {0: 1, 1: 4, 2: 64}[visibility]
            result = await asyncio.to_thread(
                self._sync_action_at,
                self.settings.napcat_base_url,
                self.settings.napcat_access_token,
                "send_qzone_msg",
                {"content": text, "images": [], "ugc_right": ugc_right, "target_uins": []},
            )
        else:
            result = await self.action(
                "send_msg",
                {"message": text, "who_can_see": visibility},
            )
        payload = result if isinstance(result, dict) else {}
        return {
            "tid": str(payload.get("tid") or payload.get("message_id") or ""),
            "content": text,
            "who_can_see": visibility,
            "result": payload,
        }

    async def action(self, name: str, params: dict[str, Any]) -> Any:
        self.settings.validate()
        return await asyncio.to_thread(self._sync_action, name, params)

    def _sync_action(self, name: str, params: dict[str, Any]) -> Any:
        return self._sync_action_at(
            self.settings.base_url,
            self.settings.access_token,
            name,
            params,
        )

    def _sync_action_at(
        self,
        base_url: str,
        access_token: str,
        name: str,
        params: dict[str, Any],
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = Request(
            f"{base_url.rstrip('/')}/{name}",
            data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise QQZoneError(f"Bridge HTTP {exc.code}：{detail or exc.reason}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise QQZoneError(f"无法连接 QQ 空间 Bridge：{exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QQZoneError("QQ 空间 Bridge 返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise QQZoneError("QQ 空间 Bridge 响应格式无效")
        retcode = payload.get("retcode")
        retcode_failed = retcode is not None and str(retcode).strip() not in {"", "0"}
        if payload.get("status") in {"failed", "error"} or retcode_failed:
            message = payload.get("message") or payload.get("wording") or payload.get("error")
            raise QQZoneError(str(message or f"QQ 空间操作失败，retcode={retcode}"))
        return payload.get("data")


def _feed_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("msglist", "items", "feeds", "messages", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = data.get("data")
    return _feed_items(nested) if nested is not data else []


def _normalize_feed(raw: dict[str, Any]) -> ZoneFeed | None:
    tid = str(
        raw.get("tid")
        or raw.get("key")
        or raw.get("curkey")
        or raw.get("cellid")
        or raw.get("message_id")
        or raw.get("id")
        or ""
    ).strip()
    if not tid:
        return None
    user_info = raw.get("userinfo") if isinstance(raw.get("userinfo"), dict) else {}
    user_id = str(
        raw.get("uin")
        or raw.get("user_id")
        or raw.get("hostuin")
        or user_info.get("user_id")
        or user_info.get("uin")
        or ""
    ).strip()
    nickname = str(
        raw.get("nickname")
        or raw.get("name")
        or raw.get("uinname")
        or user_info.get("nickname")
        or f"QQ {user_id or '未知'}"
    )
    content = raw.get("content") or raw.get("con") or raw.get("summary") or raw.get("text") or ""
    if not content and isinstance(raw.get("conlist"), list):
        content = " ".join(
            str(part.get("con") or part.get("content") or "") if isinstance(part, dict) else str(part)
            for part in raw["conlist"]
        )
    if isinstance(content, list):
        content = " ".join(str(part) for part in content if part)
    content = " ".join(str(content).split())[:2000] or "[无文字动态]"
    pics = raw.get("pic") or raw.get("pics") or raw.get("images") or raw.get("photos") or []
    comments = raw.get("comments") if isinstance(raw.get("comments"), list) else []
    create_time = raw.get("createTime")
    nested_timestamp = create_time.get("time") if isinstance(create_time, dict) else 0
    time_text = create_time if isinstance(create_time, str) and not create_time.isdigit() else ""
    return ZoneFeed(
        tid=tid,
        user_id=user_id,
        nickname=nickname,
        content=content,
        abstime=_as_int(
            raw.get("abstime")
            or raw.get("created_time")
            or raw.get("timestamp")
            or raw.get("created_at")
            or nested_timestamp
        ),
        time_text=str(raw.get("createTime2") or raw.get("time_text") or time_text),
        liked=bool(raw.get("isLiked") or raw.get("is_liked") or raw.get("liked")),
        like_count=_as_int(
            raw.get("like_count") or raw.get("likenum") or raw.get("likes") or raw.get("likeNum")
        ),
        comment_count=_as_int(
            raw.get("comment_count")
            or raw.get("cmtnum")
            or raw.get("comments_count")
            or raw.get("commentNum"),
            len(comments),
        ),
        image_count=len(pics) if isinstance(pics, list) else 0,
        appid=_as_int(raw.get("appid")),
        typeid=_as_int(raw.get("typeid")),
        unikey=str(raw.get("unikey") or raw.get("likeUnikey") or ""),
        curkey=str(raw.get("curkey") or raw.get("cur_key") or raw.get("likeCurkey") or ""),
    )


def _required(value: Any, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(message)
    return text


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
