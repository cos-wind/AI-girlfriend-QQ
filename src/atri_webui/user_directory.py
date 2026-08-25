"""Unified read model for QQ users shown across the WebUI.

The directory deliberately owns identity aggregation only.  Memory, QZone,
Insights, and modality modules remain the source of truth for their own
mutations; this module gives the UI one stable identity and overview shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any) -> float:
    raw = _number(value)
    # Insights stores ISO timestamps while memory and QZone use epoch seconds.
    if raw:
        return raw / 1000 if raw > 100_000_000_000 else raw
    text = _text(value)
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.timestamp()
        except ValueError:
            pass
    return 0.0


@dataclass
class _UserAccumulator:
    user_id: str
    names: list[str] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)
    avatar: str = ""
    sources: set[str] = field(default_factory=set)
    contexts: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    message_count: int = 0
    last_seen_at: str = ""
    last_seen_ts: float = 0.0
    relationship: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)
    source_status: dict[str, str] = field(default_factory=dict)

    def observe(
        self,
        *,
        name: Any = "",
        aliases: Iterable[Any] = (),
        source: str,
        context: str = "",
        avatar: Any = "",
        messages: Any = 0,
        last_seen_at: Any = "",
        role: str = "",
        relationship: dict[str, Any] | None = None,
        capabilities: dict[str, Any] | None = None,
        source_status: dict[str, Any] | None = None,
    ) -> None:
        clean_name = _text(name)
        if clean_name and clean_name != self.user_id and clean_name not in self.names:
            self.names.append(clean_name)
        for alias in aliases:
            clean_alias = _text(alias)
            if clean_alias and clean_alias != self.user_id:
                self.aliases.add(clean_alias)
        if _text(avatar):
            self.avatar = _text(avatar)
        self.sources.add(_text(source) or "unknown")
        if _text(context):
            self.contexts.add(_text(context))
        if _text(role):
            self.roles.add(_text(role))
        self.message_count = max(self.message_count, int(_number(messages)))
        timestamp = _timestamp(last_seen_at)
        if timestamp >= self.last_seen_ts:
            self.last_seen_ts = timestamp
            self.last_seen_at = _text(last_seen_at)
        if relationship:
            self.relationship.update({key: value for key, value in relationship.items() if value not in (None, "")})
        if capabilities:
            for key, value in capabilities.items():
                self.capabilities[_text(key)] = bool(value)
        if source_status:
            self.source_status.update({str(key): _text(value) for key, value in source_status.items() if _text(value)})

    def payload(self, *, bot_qq: str = "", owner_qqs: Iterable[str] = ()) -> dict[str, Any]:
        owner_ids = {_text(value) for value in owner_qqs if _text(value)}
        is_bot = self.user_id == _text(bot_qq) and bool(_text(bot_qq))
        is_owner = self.user_id in owner_ids
        roles = set(self.roles)
        if is_bot:
            roles.add("bot")
        if is_owner:
            roles.add("owner")
        if is_bot:
            display_name = "亚托莉"
            pin_order = 0
        elif is_owner:
            display_name = "余弦寄长风"
            pin_order = 1
        else:
            display_name = self.names[0] if self.names else f"QQ {self.user_id}"
            pin_order = 2
        aliases = sorted({value for value in self.aliases if value != display_name}, key=lambda value: value.lower())
        sources = sorted(self.sources)
        contexts = sorted(self.contexts)
        capabilities = {
            "memory": "memory" in self.sources,
            "qzone": "qzone" in self.sources or "qzone_target" in self.sources,
            "like": bool(self.capabilities.get("like", False)),
            "comment": bool(self.capabilities.get("comment", False)),
            "vision": bool(self.capabilities.get("vision", False)),
            "voice": bool(self.capabilities.get("voice", False)),
        }
        return {
            "id": f"qq:{self.user_id}",
            "entity_type": "user",
            "user_id": self.user_id,
            "canonical_name": display_name,
            "display_name": display_name,
            "aliases": aliases,
            "avatar": self.avatar,
            "sources": sources,
            "contexts": contexts,
            "roles": sorted(roles),
            "pinned": pin_order < 2,
            "pin_order": pin_order,
            "message_count": self.message_count,
            "last_seen_at": self.last_seen_at,
            "last_seen_ts": self.last_seen_ts,
            "relationship": dict(self.relationship),
            "capabilities": capabilities,
            "source_status": dict(self.source_status),
        }


@dataclass
class _GroupAccumulator:
    group_id: str
    names: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    message_count: int = 0
    last_seen_at: str = ""
    last_seen_ts: float = 0.0
    capabilities: dict[str, bool] = field(default_factory=dict)
    relationship: dict[str, Any] = field(default_factory=dict)

    def observe(
        self,
        *,
        name: Any = "",
        source: str,
        messages: Any = 0,
        last_seen_at: Any = "",
        capabilities: dict[str, Any] | None = None,
        relationship: dict[str, Any] | None = None,
    ) -> None:
        clean_name = _text(name)
        if clean_name and clean_name not in self.names:
            self.names.append(clean_name)
        self.sources.add(_text(source) or "unknown")
        self.message_count = max(self.message_count, int(_number(messages)))
        timestamp = _timestamp(last_seen_at)
        if timestamp >= self.last_seen_ts:
            self.last_seen_ts = timestamp
            self.last_seen_at = _text(last_seen_at)
        for key, value in (capabilities or {}).items():
            self.capabilities[_text(key)] = bool(value)
        if relationship:
            self.relationship.update(
                {key: value for key, value in relationship.items() if value not in (None, "")}
            )

    def payload(self) -> dict[str, Any]:
        display_name = self.names[0] if self.names else f"群 {self.group_id}"
        return {
            "id": f"group:{self.group_id}",
            "entity_type": "group",
            "group_id": self.group_id,
            "canonical_name": display_name,
            "display_name": display_name,
            "aliases": self.names[1:],
            "sources": sorted(self.sources),
            "contexts": ["group"],
            "roles": ["group"],
            "capabilities": {"vision": bool(self.capabilities.get("vision")), "voice": bool(self.capabilities.get("voice"))},
            "relationship": dict(self.relationship),
            "pinned": False,
            "message_count": self.message_count,
            "last_seen_at": self.last_seen_at,
            "last_seen_ts": self.last_seen_ts,
        }


class UserDirectory:
    """Aggregate user observations into one searchable WebUI read model."""

    def __init__(
        self,
        *,
        memory_payload: dict[str, Any] | None = None,
        insights_users: Iterable[dict[str, Any]] = (),
        modality_policy: dict[str, Any] | None = None,
        qzone_targets: Iterable[dict[str, Any]] = (),
        qzone_friends: Iterable[dict[str, Any]] = (),
        insights_groups: Iterable[dict[str, Any]] = (),
        bot_qq: Any = "",
        owner_qqs: Iterable[Any] = (),
        source_status: dict[str, str] | None = None,
    ) -> None:
        self.bot_qq = _text(bot_qq)
        self.owner_qqs = [_text(value) for value in owner_qqs if _text(value)]
        self.source_status = source_status or {}
        self._users: dict[str, _UserAccumulator] = {}
        self._groups: dict[str, _GroupAccumulator] = {}
        self._ingest_memory(memory_payload or {})
        self._ingest_insights(insights_users)
        self._ingest_insights_groups(insights_groups)
        self._ingest_qzone(qzone_friends, qzone_targets)
        self._ingest_modality(modality_policy or {})
        for user_id in [self.bot_qq, *self.owner_qqs]:
            if user_id.isdigit():
                self._user(user_id).observe(source="config", role="bot" if user_id == self.bot_qq else "owner")

    def _user(self, user_id: Any) -> _UserAccumulator:
        key = _text(user_id)
        if not key.isdigit():
            raise ValueError("user_id must be numeric")
        return self._users.setdefault(key, _UserAccumulator(key))

    def _group(self, group_id: Any) -> _GroupAccumulator:
        key = _text(group_id)
        if not key.isdigit():
            raise ValueError("group_id must be numeric")
        return self._groups.setdefault(key, _GroupAccumulator(key))

    def _ingest_memory(self, payload: dict[str, Any]) -> None:
        bot_activity = payload.get("bot_activity")
        if self.bot_qq.isdigit() and isinstance(bot_activity, dict):
            self._user(self.bot_qq).observe(
                source="memory",
                role="bot",
                messages=bot_activity.get("messages"),
                last_seen_at=bot_activity.get("last_seen_at"),
            )
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("kind") == "group":
                target = item.get("target") if isinstance(item.get("target"), dict) else {}
                group_id = _text(target.get("group_id")) or _text(item.get("id")).removeprefix("group:")
                if group_id.isdigit():
                    self._group(group_id).observe(
                        name=item.get("display_name"),
                        source="memory",
                        messages=item.get("messages"),
                        last_seen_at=item.get("last_user_at"),
                        relationship={
                            "activity": item.get("activity"),
                            "activity_label": item.get("activity_label"),
                            "proactive_override": item.get("proactive_override"),
                            "summary": item.get("summary"),
                            "memory_counts": item.get("memory_counts"),
                        },
                    )
                continue
            if item.get("kind") not in {"person", "member", "private"}:
                continue
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            user_id = _text(target.get("user_id")) or _text(item.get("id")).removeprefix("person:").removeprefix("private:")
            if not user_id.isdigit():
                continue
            self._user(user_id).observe(
                name=item.get("display_name"),
                source="memory",
                context="group" if item.get("kind") == "member" else "private",
                messages=item.get("messages"),
                last_seen_at=item.get("last_user_at"),
                relationship={
                    "affection": item.get("affection"),
                    "affection_label": item.get("affection_label"),
                    "trust_tier": item.get("trust_tier"),
                    "trust_label": item.get("trust_label"),
                    "proactive_override": item.get("proactive_override"),
                    # Keep the compact memory read model available in the
                    # unified user card.  The full /api/memory payload is
                    # intentionally loaded lazily, so the first directory
                    # response can still show relationship/context data.
                    # Keep the first-card payload bounded; the full summary
                    # remains available from /api/memory when the detail view
                    # is opened.
                    "summary": str(item.get("summary") or "")[:240] or None,
                    "memory_counts": item.get("memory_counts"),
                },
            )

    def _ingest_insights(self, users: Iterable[dict[str, Any]]) -> None:
        for item in users:
            if not isinstance(item, dict):
                continue
            user_id = _text(item.get("user_id"))
            if not user_id.isdigit():
                continue
            self._user(user_id).observe(
                name=item.get("name"),
                source="insights",
                context="group",
                messages=item.get("messages"),
                last_seen_at=item.get("last_message_at"),
            )

    def _ingest_insights_groups(self, groups: Iterable[dict[str, Any]]) -> None:
        for item in groups:
            if not isinstance(item, dict):
                continue
            group_id = _text(item.get("group_id"))
            if not group_id.isdigit():
                continue
            self._group(group_id).observe(
                name=item.get("group_name"),
                source="insights",
                messages=item.get("messages"),
                last_seen_at=item.get("last_message_at"),
            )

    def _ingest_qzone(
        self,
        friends: Iterable[dict[str, Any]],
        targets: Iterable[dict[str, Any]],
    ) -> None:
        status = {"qzone": self.source_status.get("qzone", "unknown")}
        for item in friends:
            if not isinstance(item, dict):
                continue
            user_id = _text(item.get("user_id") or item.get("uin"))
            if not user_id.isdigit():
                continue
            self._user(user_id).observe(
                name=item.get("nickname") or item.get("name"),
                aliases=[item.get("remark"), item.get("card")],
                source="qzone",
                context="qzone",
                avatar=item.get("avatar"),
                source_status=status,
            )
        for item in targets:
            if not isinstance(item, dict):
                continue
            user_id = _text(item.get("user_id"))
            if not user_id.isdigit():
                continue
            self._user(user_id).observe(
                name=item.get("nickname"),
                source="qzone_target",
                context="qzone",
                capabilities={"like": item.get("enabled_like"), "comment": item.get("enabled_comment")},
                source_status=status,
            )

    def _ingest_modality(self, policy: dict[str, Any]) -> None:
        for raw_id, item in (policy.get("users") or {}).items():
            if not isinstance(item, dict):
                continue
            user_id = _text(raw_id)
            if not user_id.isdigit():
                continue
            self._user(user_id).observe(
                name=item.get("name"),
                source="modality",
                context="modality",
                capabilities={"vision": item.get("vision"), "voice": item.get("voice")},
            )
        for raw_id, item in (policy.get("groups") or {}).items():
            if not isinstance(item, dict):
                continue
            group_id = _text(raw_id)
            if not group_id.isdigit():
                continue
            self._group(group_id).observe(
                name=item.get("name"),
                source="modality",
                capabilities={"vision": item.get("vision"), "voice": item.get("voice")},
            )

    def _all(self) -> list[dict[str, Any]]:
        rows = [item.payload(bot_qq=self.bot_qq, owner_qqs=self.owner_qqs) for item in self._users.values()]
        rows.sort(key=lambda item: (int(item.get("pin_order", 2)), -float(item.get("last_seen_ts", 0)), str(item.get("canonical_name", ""))))
        return rows

    def list_users(
        self,
        *,
        query: str = "",
        source: str = "",
        context: str = "",
        capability: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        needle = _text(query).casefold()
        source = _text(source)
        context = _text(context)
        capability = _text(capability)
        rows: list[dict[str, Any]] = []
        for item in self._all():
            haystack = " ".join(
                [item["user_id"], item["canonical_name"], *item["aliases"], *item["sources"], *item["contexts"]]
            ).casefold()
            if needle and needle not in haystack:
                continue
            if source and source not in item["sources"]:
                continue
            if context and context not in item["contexts"]:
                continue
            if capability and not bool(item["capabilities"].get(capability, False)):
                continue
            rows.append(item)
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(1000, int(limit)))
        return {
            "ok": True,
            "items": rows[safe_offset : safe_offset + safe_limit],
            "total": len(rows),
            "offset": safe_offset,
            "limit": safe_limit,
            "source_status": dict(self.source_status),
        }

    def list_groups(self, *, query: str = "", limit: int = 200, offset: int = 0) -> dict[str, Any]:
        needle = _text(query).casefold()
        rows = []
        for item in self._groups.values():
            payload = item.payload()
            haystack = " ".join([payload["group_id"], payload["canonical_name"], *payload["aliases"]]).casefold()
            if needle and needle not in haystack:
                continue
            rows.append(payload)
        rows.sort(key=lambda item: (-float(item.get("last_seen_ts", 0)), str(item.get("canonical_name", ""))))
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(500, int(limit)))
        return {"ok": True, "items": rows[safe_offset : safe_offset + safe_limit], "total": len(rows), "offset": safe_offset, "limit": safe_limit}

    def overview(self, user_id: Any) -> dict[str, Any] | None:
        key = _text(user_id).removeprefix("qq:")
        if not key.isdigit() or key not in self._users:
            return None
        item = next(row for row in self._all() if row["user_id"] == key)
        item["source_status"] = {**self.source_status, **item.get("source_status", {})}
        return item

    def group_overview(self, group_id: Any) -> dict[str, Any] | None:
        key = _text(group_id).removeprefix("group:")
        if not key.isdigit() or key not in self._groups:
            return None
        return self._groups[key].payload()
