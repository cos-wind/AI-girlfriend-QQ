"""语音/视觉能力的 QQ 成员与群聊白名单。

配置由 WebUI 写入 JSON，OneBot 进程在每次能力调用前读取（带 mtime 缓存），
因此保存后无需重启即可生效。白名单开关默认关闭，保证旧配置升级后行为不变。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .paths import MODALITY_ACCESS_PATH


_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_MTIME_NS: int | None = None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _default() -> dict[str, Any]:
    return {
        "version": 2,
        "vision_allowlist_enabled": False,
        "voice_allowlist_enabled": False,
        "users": {},
        "groups": {},
    }


def _normalize(payload: Any) -> dict[str, Any]:
    result = _default()
    if not isinstance(payload, dict):
        return result
    result["vision_allowlist_enabled"] = _as_bool(payload.get("vision_allowlist_enabled", False))
    result["voice_allowlist_enabled"] = _as_bool(payload.get("voice_allowlist_enabled", False))
    raw_users = payload.get("users")
    if isinstance(raw_users, list):
        # 兼容 WebUI 早期可能提交的列表结构。
        raw_users = {str(item.get("user_id")): item for item in raw_users if isinstance(item, dict)}
    if isinstance(raw_users, dict):
        for raw_id, raw_user in raw_users.items():
            user_id = str(raw_id or "").strip()
            if not user_id.isdigit() or not isinstance(raw_user, dict):
                continue
            result["users"][user_id] = {
                "name": str(raw_user.get("name") or "").strip()[:120],
                "vision": _as_bool(raw_user.get("vision", False)),
                "voice": _as_bool(raw_user.get("voice", False)),
            }
    raw_groups = payload.get("groups")
    if isinstance(raw_groups, list):
        raw_groups = {
            str(item.get("group_id")): item
            for item in raw_groups
            if isinstance(item, dict)
        }
    if isinstance(raw_groups, dict):
        for raw_id, raw_group in raw_groups.items():
            group_id = str(raw_id or "").strip()
            if not group_id.isdigit() or not isinstance(raw_group, dict):
                continue
            result["groups"][group_id] = {
                "name": str(raw_group.get("name") or "").strip()[:120],
                "vision": _as_bool(raw_group.get("vision", False)),
                "voice": _as_bool(raw_group.get("voice", False)),
            }
    return result


def load_modality_access(*, force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME_NS
    path = MODALITY_ACCESS_PATH
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = None
    with _LOCK:
        if not force and _CACHE is not None and mtime_ns == _CACHE_MTIME_NS:
            return json.loads(json.dumps(_CACHE, ensure_ascii=False))
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        _CACHE = _normalize(payload)
        _CACHE_MTIME_NS = mtime_ns
        return json.loads(json.dumps(_CACHE, ensure_ascii=False))


def save_modality_access(payload: dict[str, Any]) -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME_NS
    normalized = _normalize(payload)
    path = MODALITY_ACCESS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        _CACHE = normalized
        try:
            _CACHE_MTIME_NS = path.stat().st_mtime_ns
        except OSError:
            _CACHE_MTIME_NS = None
    return json.loads(json.dumps(normalized, ensure_ascii=False))


def is_modality_allowed(
    user_id: Any,
    modality: str,
    *,
    group_id: Any = None,
) -> bool:
    """允许指定成员或指定群聊使用能力；白名单关闭时兼容性放行。"""
    user_key = str(user_id or "").strip()
    group_key = str(group_id or "").strip()
    name = "vision" if str(modality).strip().lower() == "vision" else "voice"
    policy = load_modality_access()
    if not bool(policy.get(f"{name}_allowlist_enabled", False)):
        return True
    user = policy.get("users", {}).get(user_key)
    if isinstance(user, dict) and bool(user.get(name, False)):
        return True
    group = policy.get("groups", {}).get(group_key)
    return bool(isinstance(group, dict) and group.get(name, False))


def is_event_modality_allowed(event: dict[str, Any], modality: str) -> bool:
    """OneBot 事件授权的单一 interface，避免各 caller 遗漏群聊范围。"""
    group_id = event.get("group_id") if event.get("message_type") == "group" else None
    return is_modality_allowed(
        event.get("user_id"),
        modality,
        group_id=group_id,
    )
