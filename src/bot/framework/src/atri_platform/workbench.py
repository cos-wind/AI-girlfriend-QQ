"""Explicit, local multi-platform workbench operations.

Construction and status are passive. Optional libraries and account sessions are
created only after a user action, on one owning worker thread per adapter.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
import sqlite3
from threading import Lock
import time
from urllib.parse import urlsplit
import uuid

from .worker import OwnedWorker


OPEN_URL_HOSTS = ("bilibili.com", "douyin.com")


def external_url(payload: dict) -> str:
    """只放行已发布的视频链接与本机第三方面板；不放行 file、内网主机或带凭据的地址。"""
    url = payload.get("url")
    if not isinstance(url, str) or not url.strip() or len(url) > 500 or "\x00" in url:
        raise ValueError("链接不能为空，且不得超过 500 字符")
    url = url.strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.username or parsed.password:
        raise ValueError("链接不能包含账号信息")
    if parsed.scheme == "http":
        # 本机回环面板（WeFlow 等）走 http，仅限 127.0.0.1/localhost，且只交给系统浏览器打开。
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("只允许打开本机回环地址或 B 站、抖音链接")
        return url
    if parsed.scheme != "https" or parsed.port not in {None, 443}:
        raise ValueError("只允许打开 https 链接")
    if not any(host == item or host.endswith("." + item) for item in OPEN_URL_HOSTS):
        raise ValueError("只允许打开 B 站或抖音链接")
    return url


PLATFORMS = {
    "wechat": {"name": "微信机器人通道", "package": "qrcode", "extra": "desktop",
               "capabilities": ["腾讯 iLink 协议扫码", "收取机器人消息", "确认后回复文本"]},
    "wechat-desktop": {"name": "微信桌面会话", "package": "wxauto4", "extra": "wechat",
               "capabilities": ["读取指定会话", "编辑草稿", "确认后发送文本"]},
    "wechat-personal": {"name": "个人微信", "package": "wxauto4", "extra": "wechat",
               "capabilities": ["扫码登录", "好友私聊", "群聊 @ 回复"]},
    "bilibili": {"name": "哔哩哔哩", "package": "bilibili-api-python", "extra": "bilibili",
                 "capabilities": ["扫码登录", "搜索视频", "热门视频", "读取字幕", "浏览器播放"]},
    "douyin": {"name": "抖音", "package": "playwright", "extra": "social-browser",
               "capabilities": ["独立浏览器登录", "账号验证", "搜索视频", "读取当前页面", "切换推荐视频"]},
}

# 采集记录默认只给最近 30 条；界面必须同时显示总数，否则更早的记录会静默消失。
HISTORY_LIMIT = 30
HISTORY_LIMIT_MAX = 200


def text_field(payload: dict, key: str, limit: int = 500) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{key} 不能为空，且不得超过 {limit} 字符")
    return value.strip()


class MultimediaClient:
    def __init__(self, root: Path | None = None, *, factories: dict | None = None):
        if root is None:
            from atri_shared.runtime.paths import DATA_DIR
            root = DATA_DIR / "desktop" / "multimedia"
        self.root = Path(root)
        self._factories = factories or {}
        self._workers: dict[str, OwnedWorker] = {}
        self._lock = Lock()
        self._send_lock = Lock()
        self._desktop_lock = Lock()
        self._schema_lock = Lock()
        self._schema_ready = False
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
            for worker in self._workers.values():
                worker.close()

    def restore(self):
        """Desktop lifecycle only: restore explicitly enabled personal replies.

        Construction, bootstrap and status remain passive. No other platform is
        started and an account change cannot inherit the previous binding.
        """
        path = self.root / 'wechat-personal' / 'settings.json'
        try:
            if not path.exists() or json.loads(path.read_text(encoding='utf-8')).get('enabled') is not True:
                return
            return self._call('wechat-personal', 'restore', {})
        except Exception:
            # The adapter publishes restoration failures in its status/log.
            # A missing optional adapter must not prevent the desktop opening.
            import logging
            logging.getLogger(__name__).warning('WeChat auto-reply restoration did not complete')

    def _ensure_schema(self, db):
        with self._schema_lock:
            if self._schema_ready:
                return
            db.execute("CREATE TABLE IF NOT EXISTS captures (id TEXT PRIMARY KEY, platform TEXT, created REAL, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, platform TEXT, recipient TEXT, account TEXT, text TEXT, state TEXT, updated REAL)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(captures)")}
            if "fingerprint" not in columns:
                db.execute("ALTER TABLE captures ADD COLUMN fingerprint TEXT")
            # Old rows keep a NULL fingerprint, which never conflicts; only video
            # platforms dedupe, so existing chat history is preserved as-is.
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS captures_platform_fingerprint ON captures(platform, fingerprint)")
            self._schema_ready = True

    @contextmanager
    def _db(self, readonly=False):
        path = self.root / "workbench.sqlite3"
        if readonly and path.exists() and self._schema_ready:
            # Listing never needs a write lock once this instance migrated the schema.
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
            try:
                yield db
            finally:
                db.close()
            return
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=10)
        try:
            with db:
                self._ensure_schema(db)
                yield db
        finally:
            db.close()

    def status(self):
        with self._lock:
            workers = dict(self._workers)
        rows = []
        for key, item in PLATFORMS.items():
            try:
                installed = version(item["package"])
            except PackageNotFoundError:
                installed = ""
            rows.append({"id": key, **item, "version": installed,
                         "runtime": workers[key].snapshot() if key in workers else {"state": "not_started"},
                         "state": "依赖已安装，尚未验证连接" if installed else "需要安装可选依赖",
                         "install": 'uv sync --extra desktop' + (f' --extra {item["extra"]}' if item["extra"] != "desktop" else "")})
        return {"platforms": rows}

    def _worker(self, platform):
        with self._lock:
            if self._closed:
                raise ValueError("工作台正在关闭")
            if platform not in self._workers:
                factory = self._factories.get(platform)
                if factory is None:
                    from importlib import import_module
                    module, name = {
                        "wechat": ("atri_wechat.ilink", "WeixinAdapter"),
                        "wechat-desktop": ("atri_wechat.desktop", "WechatAdapter"),
                        "wechat-personal": ("atri_wechat.personal", "PersonalAdapter"),
                        "bilibili": ("atri_bilibili.adapter", "BilibiliAdapter"),
                        "douyin": ("atri_douyin.adapter", "DouyinAdapter"),
                    }[platform]
                    cls = getattr(import_module(module), name)
                    factory = lambda: cls(self.root / platform)
                self._workers[platform] = OwnedWorker(factory)
            return self._workers[platform]

    @staticmethod
    def _fingerprint(platform: str, data: dict):
        """Stable identity for a video capture, so re-reading updates one row."""
        existing = data.get("fingerprint")
        if isinstance(existing, str) and existing.strip():
            return existing.strip()[:128]
        key = data.get("url") or data.get("title")
        if not isinstance(key, str) or not key.strip():
            return None
        return hashlib.sha256(f"{platform}\n{key.strip()}".encode("utf-8")).hexdigest()

    def _capture(self, platform: str, data: dict):
        capture_id = uuid.uuid4().hex
        fingerprint = self._fingerprint(platform, data) if platform in {"bilibili", "douyin"} else None
        # Only the adapter's content result is stored; never raw cookies or QR state.
        with self._db() as db:
            if fingerprint:
                row = db.execute("SELECT id FROM captures WHERE platform=? AND fingerprint=?", (platform, fingerprint)).fetchone()
                if row is not None:
                    capture_id = row[0]
            record = {"id": capture_id, "platform": platform, "captured_at": time.time(), **data}
            db.execute(
                "INSERT INTO captures (id, platform, created, data, fingerprint) VALUES (?,?,?,?,?) "
                "ON CONFLICT(platform, fingerprint) DO UPDATE SET created=excluded.created, data=excluded.data",
                (capture_id, platform, record["captured_at"], json.dumps(record, ensure_ascii=False), fingerprint),
            )
        return record

    @staticmethod
    def _summary(data: dict) -> dict:
        """List payload: metadata only, never the full transcript."""
        text = data.get("text")
        return {"id": data.get("id", ""), "platform": data.get("platform", ""),
                "title": data.get("title", ""), "url": data.get("url", ""),
                "recipient": data.get("recipient", ""), "coverage": data.get("coverage", ""),
                "captured_at": data.get("captured_at", 0),
                "chars": len(text) if isinstance(text, str) else 0}

    def _capture_detail(self, payload: dict) -> dict:
        capture_id = payload.get("id")
        if not isinstance(capture_id, str) or not re.fullmatch(r"[0-9a-f]{32}", capture_id):
            raise ValueError("采集记录标识无效")
        with self._db(readonly=True) as db:
            row = db.execute("SELECT data FROM captures WHERE id=?", (capture_id,)).fetchone()
        if row is None:
            raise ValueError("采集记录不存在或已被清理")
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            raise ValueError("采集记录已损坏，无法读取") from None
        if not isinstance(data, dict):
            raise ValueError("采集记录已损坏，无法读取")
        return data

    def execute(self, payload: dict) -> dict:
        action = payload.get("action", "status")
        if action == "status":
            return {"ok": True, "data": self.status()}
        if action == "history":
            platforms = payload.get("platforms")
            query, params = "SELECT data FROM captures", ()
            if platforms is not None:
                if not isinstance(platforms, list) or not platforms or any(not isinstance(p, str) or p not in PLATFORMS for p in platforms):
                    raise ValueError("采集记录平台必须是非空的已支持平台列表")
                # 先按平台筛选再限量，避免微信记录挤掉较早的视频资料。
                query += " WHERE platform IN (" + ",".join("?" for _ in platforms) + ")"
                params = tuple(platforms)
            # 页面上必须能说出「共几条、只给了几条」，所以总数单独查；上限封顶，
            # 避免前端一次要几万条把页面撑爆。
            limit = payload.get("limit", HISTORY_LIMIT)
            if type(limit) is not int or not 1 <= limit <= HISTORY_LIMIT_MAX:
                raise ValueError(f"采集记录条数需为 1–{HISTORY_LIMIT_MAX} 的整数")
            with self._db(readonly=True) as db:
                rows = db.execute(query + " ORDER BY created DESC LIMIT ?", params + (limit,)).fetchall()
                total = db.execute("SELECT COUNT(*) FROM captures" + (" WHERE platform IN ("
                                    + ",".join("?" for _ in platforms) + ")" if platforms is not None else ""), params).fetchone()[0]
            items, skipped = [], 0
            for (raw,) in rows:
                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("shape")
                except (TypeError, ValueError):
                    skipped += 1
                    continue
                items.append(self._summary(data))
            return {"ok": True, "data": {"items": items, "skipped": skipped,
                                         "total": total, "limit": limit}}
        if action == "capture":
            return {"ok": True, "data": self._capture_detail(payload)}
        if action == "open-url":
            # Explicit host allowlist: the desktop host has no working
            # target=_blank, so links leave through the OS browser instead.
            import webbrowser
            if not webbrowser.open(external_url(payload)):
                raise ValueError("无法打开默认浏览器")
            return {"ok": True, "data": {"message": "已在默认浏览器打开"}}
        platform = payload.get("platform")
        if not isinstance(platform, str) or platform not in PLATFORMS:
            raise ValueError("请选择微信、哔哩哔哩或抖音")
        allowed = {
            "wechat": {"login", "login-check", "connect", "read", "draft", "send", "disconnect"},
            "wechat-desktop": {"connect", "read", "draft", "send", "disconnect"},
            "wechat-personal": {"login", "login-check", "channel-status", "start", "stop", "connect", "sessions", "read", "draft", "send", "disconnect"},
            "bilibili": {"login", "login-check", "search", "hot", "read", "open", "discuss", "disconnect"},
            "douyin": {"connect", "login-check", "search", "read", "next", "open", "discuss", "disconnect"},
        }
        if not isinstance(action, str) or action not in allowed[platform]:
            raise ValueError("该平台不支持此操作")
        if action == "draft":
            recipient = text_field(payload, "recipient", 120)
            account = text_field(payload, "account", 120)
            text = text_field(payload, "text", 4000)
            draft_id = uuid.uuid4().hex
            with self._db() as db:
                db.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?)", (draft_id, platform, recipient, account, text, "draft", time.time()))
            return {"ok": True, "data": {"id": draft_id, "recipient": recipient, "account": account, "text": text, "state": "draft"}}
        if action == "send":
            return self._send(platform, payload)
        data = self._call(platform, action, payload)
        if action in {"read", "next"}:
            data = self._capture(platform, data)
        return {"ok": True, "data": data}

    def _call(self, platform, action, payload):
        if platform not in {'wechat-desktop', 'wechat-personal'}:
            return self._worker(platform).call(action, payload)
        # Both entrances share one desktop client. Starting automatic replies
        # and taking manual desktop control must not race across bridge calls.
        with self._desktop_lock:
            if platform == 'wechat-desktop' and action != 'disconnect':
                personal = self._workers.get('wechat-personal')
                if personal and personal.call('channel-status', {}).get('running'):
                    raise ValueError('个人微信自动回复运行中，请先停止，避免争用微信窗口')
            return self._worker(platform).call(action, payload)

    def _send(self, platform, payload):
        if payload.get("confirmed") is not True:
            raise ValueError("请核对发送账号、收件人与草稿，再确认发送")
        draft_id = text_field(payload, "draft_id", 64)
        # Persist 'sending' BEFORE dispatch. An uncertain send is never retried.
        with self._send_lock:
            with self._db() as db:
                # Claim across processes too; an instance lock alone is insufficient.
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT recipient,account,text,state,platform FROM drafts WHERE id=?", (draft_id,)).fetchone()
                if row is None:
                    raise ValueError("草稿不存在，请重新保存")
                recipient, account, text, state, draft_platform = row
                if draft_platform != platform:
                    raise ValueError("草稿所属微信通道不匹配，请重新保存")
                if state != "draft":
                    return {"ok": state == "submitted", "data": {"state": state},
                            "message": "该草稿已提交" if state == "submitted" else "此前发送结果不确定，请在微信核对，勿重复发送"}
                db.execute("UPDATE drafts SET state='sending',updated=? WHERE id=?", (time.time(), draft_id))
            try:
                result = self._call(platform, "send", {"recipient": recipient, "account": account, "text": text})
            except Exception:
                with self._db() as db:
                    db.execute("UPDATE drafts SET state='unknown',updated=? WHERE id=?", (time.time(), draft_id))
                raise ValueError("微信发送未获明确回执。请先在微信核对；此草稿已锁定，避免重复发送。") from None
            with self._db() as db:
                db.execute("UPDATE drafts SET state='submitted',updated=? WHERE id=?", (time.time(), draft_id))
            return {"ok": True, "data": {"state": "submitted", **result}}
