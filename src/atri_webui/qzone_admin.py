from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class QZoneBridgeError(RuntimeError):
    """A user-facing failure returned by the local QZone bridge."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class QZoneBridgeSettings:
    enabled: bool
    base_url: str
    access_token: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "QZoneBridgeSettings":
        return cls(
            enabled=_env_bool("QZONE_BRIDGE_ENABLED", False),
            base_url=str(os.getenv("QZONE_BRIDGE_URL", "http://127.0.0.1:5700") or "").rstrip("/"),
            access_token=str(os.getenv("QZONE_BRIDGE_TOKEN", "") or "").strip(),
            timeout_seconds=max(
                2.0,
                min(30.0, float(os.getenv("QZONE_BRIDGE_TIMEOUT_SECONDS", "8") or 8)),
            ),
        )

    def public_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "token_configured": bool(self.access_token),
            "timeout_seconds": self.timeout_seconds,
        }

    def validate(self) -> None:
        if not self.enabled:
            raise QZoneBridgeError("QQ 动态模块未启用，请设置 QZONE_BRIDGE_ENABLED=1")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise QZoneBridgeError("QQ 动态 Bridge 只允许使用本机回环地址")


BridgeRequester = Callable[[str, dict[str, Any]], dict[str, Any]]


class QZoneBridgeClient:
    def __init__(
        self,
        settings: QZoneBridgeSettings | None = None,
        requester: BridgeRequester | None = None,
    ) -> None:
        self.settings = settings or QZoneBridgeSettings.from_env()
        self._requester = requester

    def action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        self.settings.validate()
        if self._requester is not None:
            result = self._requester(name, params)
        else:
            result = self._http_action(name, params)
        if not isinstance(result, dict):
            raise QZoneBridgeError("QQ 动态 Bridge 返回了无效响应")
        retcode = result.get("retcode")
        if result.get("status") in {"failed", "error"} or (
            retcode is not None and str(retcode) not in {"0", "None"}
        ):
            detail = result.get("message") or result.get("wording") or result.get("error")
            if str(retcode) == "1401":
                detail = (
                    "QQ 动态 Bridge 在线但尚未登录；MaiBot WebUI 登录与 QQ 空间登录独立，"
                    "请扫描 Bridge 生成的 QQ 空间二维码后再刷新动态"
                )
            raise QZoneBridgeError(str(detail or f"QQ 动态操作失败（retcode={retcode}）"))
        return result

    def status(self) -> dict[str, Any]:
        """读取 Bridge 登录状态，不触发任何 QQ 空间操作。"""
        self.settings.validate()
        headers = {"Accept": "application/json"}
        if self.settings.access_token:
            headers["Authorization"] = f"Bearer {self.settings.access_token}"
        request = Request(
            f"{self.settings.base_url}/status",
            headers=headers,
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise QZoneBridgeError(
                f"QQ 动态 Bridge 状态请求失败 HTTP {exc.code}：{detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise QZoneBridgeError(f"QQ 动态 Bridge 不可达：{exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QZoneBridgeError("QQ 动态 Bridge 状态返回的不是 JSON") from exc
        if not isinstance(payload, dict):
            raise QZoneBridgeError("QQ 动态 Bridge 状态返回了无效响应")
        return payload

    def _http_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(params, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.settings.access_token:
            headers["Authorization"] = f"Bearer {self.settings.access_token}"
        request = Request(
            f"{self.settings.base_url}/{name}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise QZoneBridgeError(
                f"QQ 动态 Bridge 返回 HTTP {exc.code}：{detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise QZoneBridgeError(f"QQ 动态 Bridge 不可达：{exc}") from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QZoneBridgeError("QQ 动态 Bridge 返回的不是 JSON") from exc
        if not isinstance(result, dict):
            raise QZoneBridgeError("QQ 动态 Bridge 返回了无效响应")
        return result


class QZoneAdmin:
    def __init__(
        self,
        memory_payload: dict[str, Any],
        client: QZoneBridgeClient | None = None,
        bot_qq: Any | None = None,
        owner_qqs: Any | None = None,
    ) -> None:
        self.memory_payload = memory_payload
        self.client = client or QZoneBridgeClient()
        self.users = qzone_memory_users(memory_payload)
        # BotConfig is loaded from .env/config.toml and is not guaranteed to
        # be exported to os.environ.  Keep the identifiers on the admin
        # object so the pinned spaces are deterministic after every restart.
        self.bot_qq = str(bot_qq if bot_qq is not None else os.getenv("BOT_QQ", "") or "").strip()
        raw_owners = owner_qqs if owner_qqs is not None else (os.getenv("OWNER_QQ", ""),)
        if isinstance(raw_owners, (str, int)):
            raw_owners = (raw_owners,)
        self.owner_qqs = [str(value).strip() for value in (raw_owners or ()) if str(value).strip()]

    def dashboard(self) -> dict[str, Any]:
        return {
            "ok": True,
            "bridge": self.client.settings.public_payload(),
            "users": self.users,
        }

    def friends(self) -> list[dict[str, Any]]:
        """读取 Bridge 好友列表；失败时由调用方展示 Bridge 错误。"""
        data = self.client.action("get_friend_list", {})
        payload: Any = data.get("data", data)
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("friends") or payload.get("list") or []
        if not isinstance(payload, list):
            return []
        result: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            user_id = str(item.get("user_id") or item.get("uin") or "").strip()
            if not user_id.isdigit():
                continue
            result.append(
                {
                    "user_id": user_id,
                    "nickname": str(item.get("nickname") or item.get("name") or f"QQ {user_id}"),
                    "remark": str(item.get("remark") or ""),
                    "avatar": str(item.get("avatar") or ""),
                }
            )
        return result

    def feeds(self, user_id: Any, limit: Any = 10) -> dict[str, Any]:
        user = self._resolve_user(user_id)
        count = max(1, min(30, _as_int(limit, 10)))
        result = self.client.action(
            # feeds_html_act_all with an explicit feed_owner reads the
            # selected friend's own QZone page.  get_emotion_list is faster
            # when it works, but can return an empty page after a session
            # refresh even though the same friend is readable in QZone.
            "get_feeds_html_act_all",
            {
                "user_id": user["user_id"],
                "feed_owner": user["user_id"],
                "count": count,
                "max_rounds": 1,
                "include_image_data": False,
            },
        )
        return {
            "ok": True,
            "user": user,
            "feeds": normalize_feeds(result, user),
        }

    def all_feeds(self, limit: Any = 20) -> dict[str, Any]:
        count = max(1, min(50, _as_int(limit, 20)))
        # Bridge already exposes the QQ-space friend stream in one request.
        # Calling get_emotion_list once per friend is both slow and prone to
        # triggering QQ rate limits (a large friend list makes the WebUI time
        # out before the first page can be rendered).
        feeds: list[dict[str, Any]] = []
        errors: list[str] = []
        cursor = ""
        # The Bridge returns a cursor when the friend stream is larger than
        # one page.  Read a few pages so the list is useful for searching,
        # while keeping refresh bounded for large friend lists.
        for _ in range(4):
            params: dict[str, Any] = {"num": count, "fast_mode": True, "include_image_data": False}
            if cursor:
                params["cursor"] = cursor
            try:
                result = self.client.action("get_friend_feeds", params)
            except Exception as exc:
                if not feeds:
                    raise
                errors.append(f"好友动态分页读取失败：{exc}")
                break
            data = result.get("data", result)
            if isinstance(data, dict):
                feeds.extend(normalize_feeds(data, {"user_id": "", "display_name": ""}))
                has_more = bool(data.get("has_more") or data.get("hasMore"))
                next_cursor = str(data.get("next_cursor") or data.get("nextCursor") or "").strip()
            elif isinstance(data, list):
                # 部分 Bridge 版本直接返回数组，不带 data/items 包装。
                feeds.extend(normalize_feeds({"data": data}, {"user_id": "", "display_name": ""}))
                has_more = False
                next_cursor = ""
            else:
                has_more = False
                next_cursor = ""
            if not has_more or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        # Always load the two pinned spaces directly; the aggregate home
        # stream may omit the bot or the owner depending on QZone ranking.
        for special in self._special_users():
            try:
                feeds.extend(self.feeds(special["user_id"], min(count, 10)).get("feeds") or [])
            except Exception as exc:
                errors.append(f"{special['user_id']}: {exc}")
        # Some QZone sessions return an empty feeds3 home stream while direct
        # friend pages remain readable.  Fall back to a bounded, concurrent
        # sample so the UI still behaves like a timeline without making 80+
        # serial requests (which previously caused timeouts).
        if not feeds:
            candidates = self._special_users() + self.friends()[:20]
            with ThreadPoolExecutor(max_workers=4) as pool:
                unique: dict[str, dict[str, Any]] = {str(user["user_id"]): user for user in candidates}
                pending = {pool.submit(self.feeds, user["user_id"], min(count, 10)): user for user in unique.values()}
                for future in as_completed(pending):
                    user = pending[future]
                    try:
                        feeds.extend(future.result().get("feeds") or [])
                    except Exception as exc:
                        errors.append(f"{user.get('user_id')}: {exc}")
        # The list view is one row per person. Keep only the newest post from
        # each author, then pin ATRI and the configured owner in that order.
        latest: dict[str, dict[str, Any]] = {}
        for feed in feeds:
            user_id = str(feed.get("user_id") or "").strip()
            if not user_id:
                continue
            old = latest.get(user_id)
            if old is None or int(feed.get("abstime") or 0) > int(old.get("abstime") or 0):
                latest[user_id] = feed
        special = self._special_users()
        special_ids = [str(item["user_id"]) for item in special]
        ordered: list[dict[str, Any]] = []
        for item in special:
            user_id = str(item["user_id"])
            if user_id in latest:
                feed = dict(latest[user_id])
                feed["pinned"] = True
                feed["pin_label"] = str(item.get("pin_label") or item.get("nickname") or "置顶")
                ordered.append(feed)
        remaining = [feed for user_id, feed in latest.items() if user_id not in special_ids]
        remaining.sort(key=lambda item: int(item.get("abstime") or 0), reverse=True)
        ordered.extend(remaining)
        return {"ok": True, "feeds": ordered[:count], "errors": errors}

    def _special_users(self) -> list[dict[str, Any]]:
        self_id = self.bot_qq
        owner_id = self.owner_qqs[0] if self.owner_qqs else ""
        result: list[dict[str, Any]] = []
        if self_id.isdigit():
            result.append({"user_id": self_id, "nickname": "亚托莉", "pin_label": "亚托莉"})
        if owner_id.isdigit() and owner_id != self_id:
            result.append({"user_id": owner_id, "nickname": "余弦寄长风", "pin_label": "余弦寄长风"})
        return result

    def like(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = self._resolve_user(payload.get("user_id"))
        tid = _required_text(payload.get("tid"), "缺少动态 tid")
        abstime = _as_int(payload.get("abstime"), 0)
        result = self.client.action(
            "send_like",
            {"user_id": int(user["user_id"]), "tid": tid, "abstime": abstime},
        )
        return {"ok": True, "action": "like", "tid": tid, "result": _safe_result(result)}

    def comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = self._resolve_user(payload.get("user_id"))
        tid = _required_text(payload.get("tid"), "缺少动态 tid")
        content = _required_text(payload.get("content"), "评论不能为空")
        if len(content) > 200:
            raise ValueError("评论最多 200 个字符")
        result = self.client.action(
            "send_comment",
            {
                "target_uin": int(user["user_id"]),
                "target_tid": tid,
                "content": content,
            },
        )
        return {
            "ok": True,
            "action": "comment",
            "tid": tid,
            "content": content,
            "result": _safe_result(result),
        }

    def post(self, content: str, visibility: int = 1) -> dict[str, Any]:
        text = _required_text(content, "动态内容不能为空")
        if len(text) > 1000:
            raise ValueError("动态最多 1000 个字符")
        result = self.client.action(
            "send_msg",
            {"message": text, "who_can_see": max(0, min(2, int(visibility)))},
        )
        payload = result.get("data", result) if isinstance(result, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        return {"ok": True, "action": "post", "content": text, "tid": str(payload.get("tid") or payload.get("message_id") or ""), "result": _safe_result(result)}

    def _resolve_user(self, user_id: Any) -> dict[str, Any]:
        wanted = str(user_id or "").strip()
        for user in self.users:
            if user["user_id"] == wanted:
                return user
        if wanted.isdigit() and len(wanted) <= 12:
            return {"user_id": wanted, "display_name": f"QQ {wanted}", "last_user_at_text": "", "affection_label": "手动添加"}
        raise ValueError("QQ 号无效")


def qzone_memory_users(memory_payload: dict[str, Any]) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in memory_payload.get("items") or []:
        if not isinstance(item, dict) or item.get("kind") != "person":
            continue
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        user_id = str(target.get("user_id") or "").strip()
        if not user_id and str(item.get("id") or "").startswith("person:"):
            user_id = str(item["id"]).split(":", 1)[1].strip()
        if not user_id.isdigit() or user_id in seen:
            continue
        seen.add(user_id)
        users.append(
            {
                "user_id": user_id,
                "display_name": str(item.get("display_name") or f"QQ {user_id}"),
                "last_user_at_text": str(item.get("last_user_at_text") or ""),
                "affection_label": str(item.get("affection_label") or ""),
            }
        )
    return users


def normalize_feeds(result: dict[str, Any], user: dict[str, Any]) -> list[dict[str, Any]]:
    data: Any = result.get("data", result)
    if isinstance(data, dict):
        for key in ("items", "feeds", "messages", "msglist", "list", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []
    feeds: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        tid = str(
            raw.get("tid")
            or raw.get("message_id")
            or raw.get("cur_key")
            or raw.get("id")
            or ""
        ).strip()
        if not tid:
            continue
        content = _feed_text(raw)
        images = raw.get("images") or raw.get("pics") or raw.get("pic") or raw.get("photos") or []
        if not isinstance(images, list):
            images = []
        feeds.append(
            {
                "tid": tid,
                "user_id": str(raw.get("uin") or raw.get("user_id") or user["user_id"]),
                "author": str(
                    raw.get("nickname")
                    or raw.get("name")
                    or raw.get("user_name")
                    or user["display_name"]
                ),
                "content": content or "[无文字动态]",
                "abstime": _as_int(
                    raw.get("abstime") or raw.get("created_time") or raw.get("timestamp") or raw.get("created_at"), 0
                ),
                "time_text": str(
                    raw.get("time_text") or raw.get("createTime") or raw.get("create_time") or raw.get("time") or ""
                ),
                "liked": bool(raw.get("isLiked") or raw.get("is_liked") or raw.get("liked")),
                "like_count": _as_int(raw.get("like_count") or raw.get("likenum") or raw.get("likes"), 0),
                "comment_count": _as_int(
                    raw.get("comment_count") or raw.get("cmtnum") or raw.get("comments_count"),
                    len(raw.get("comments") or []) if isinstance(raw.get("comments"), list) else 0,
                ),
                "image_count": len(images),
            }
        )
    return feeds


def _feed_text(raw: dict[str, Any]) -> str:
    value: Any = raw.get("content") or raw.get("con") or raw.get("summary") or raw.get("text")
    if isinstance(value, str):
        return " ".join(value.split())[:1000]
    if isinstance(value, list):
        return " ".join(str(part) for part in value if part)[:1000]
    return ""


def _safe_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in ("status", "retcode", "message", "wording")
        if key in result
    }


def _required_text(value: Any, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(message)
    return text


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
