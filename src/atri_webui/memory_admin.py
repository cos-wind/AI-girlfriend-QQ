from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from atri_qq_bot.runtime.paths import MEMORY_BACKUP_DIR, MEMORY_PATH
from atri_qq_bot.retrieval import SemanticMemoryRepository


class MemoryAdmin:
    def __init__(
        self,
        memory_path: Path = MEMORY_PATH,
        backup_dir: Path = MEMORY_BACKUP_DIR,
        semantic_memory_path: Path | None = None,
    ) -> None:
        self.memory_path = memory_path
        self.backup_dir = backup_dir
        # WebUI 只读取索引状态；JSON 仍是这里所有编辑操作的唯一事实源。
        self.semantic_memory_path = semantic_memory_path or memory_path.with_name(
            "semantic_memory.sqlite3"
        )
        self._lock = threading.RLock()

    def summary(self) -> dict[str, Any]:
        data = self.load()
        conversations = self.conversations(data)
        items = []
        for user_id in person_user_ids(conversations):
            items.append(person_summary_item(conversations, user_id))
        for key, item in sorted(
            conversations.items(),
            key=lambda pair: _safe_float((pair[1] or {}).get("last_user_at") if isinstance(pair[1], dict) else 0),
            reverse=True,
        ):
            if not isinstance(item, dict) or memory_kind(key) != "group":
                continue
            items.append(memory_summary_item(key, item))
        items.sort(
            key=lambda item: (
                0 if item.get("kind") == "person" else 1,
                -_safe_float(item.get("last_user_at")),
            )
        )
        return {
            "path": str(self.memory_path),
            "conversations": len(items),
            "raw_conversations": len(conversations),
            "items": items,
            "retrieval": SemanticMemoryRepository(self.semantic_memory_path).status(),
        }

    def detail(self, query: str) -> dict[str, Any]:
        conversation_id = parse_qs(query).get("id", [""])[0]
        data = self.load()
        conversations = self.conversations(data)
        if conversation_id.startswith("person:"):
            user_id = conversation_id.split(":", 1)[1]
            related = person_related_keys(conversations, user_id)
            if not related:
                return {"ok": False, "error": "memory not found"}
            item = person_content(conversations, user_id)
            return memory_detail_payload(
                conversation_id,
                item,
                display_name=person_display_name(conversations, user_id),
                storage_id=f"private:{user_id}",
                related_conversations=related,
                group_infos=person_group_infos(conversations, user_id),
            )
        item = conversations.get(conversation_id)
        if not isinstance(item, dict):
            return {"ok": False, "error": "memory not found"}
        return memory_detail_payload(conversation_id, item)

    def save_conversation(self, conversation_id: str, content: dict[str, Any]) -> Path:
        with self._lock:
            data = self.load()
            conversations = self.conversations(data)
            storage_id = storage_memory_id(conversation_id)
            if storage_id not in conversations and not conversation_id.startswith("person:"):
                raise ValueError("会话不存在")
            if not isinstance(content, dict):
                raise ValueError("记忆内容必须是 JSON 对象")
            if storage_id not in conversations:
                user_id = storage_id.split(":", 1)[1]
                conversations[storage_id] = {
                    "target": {"message_type": "private", "user_id": user_id}
                }
            previous = (
                person_content(conversations, storage_id.split(":", 1)[1])
                if conversation_id.startswith("person:")
                else conversations.get(storage_id)
            )
            content = normalize_manual_memory_content(storage_id, content)
            # 标记编辑时刻，让消息链路中已经排队的旧画像提取结果不能覆盖
            # 用户刚刚在 WebUI 删除/修正的内容；后续新消息仍可正常提取。
            content["memory_manual_edit_at"] = time.time()
            removed_values = removed_person_values(previous, content)
            backup = self.backup("edit")
            conversations[storage_id] = content
            if removed_values:
                remove_values_from_same_person_members(
                    conversations,
                    storage_id,
                    removed_values,
                )
            self.write(data)
            return backup

    def update_relationship(
        self,
        conversation_id: str,
        affection_score: Any,
        proactive_override: Any,
        group_activity_score: Any = None,
        trust_tier: Any = None,
    ) -> tuple[Path, dict[str, Any]]:
        with self._lock:
            data = self.load()
            conversations = self.conversations(data)
            storage_id = storage_memory_id(conversation_id)
            is_group = storage_id.startswith("group:") and ":user:" not in storage_id
            if storage_id not in conversations:
                if not conversation_id.startswith("person:"):
                    raise ValueError("会话不存在")
                user_id = storage_id.split(":", 1)[1]
                conversations[storage_id] = {
                    "target": {"message_type": "private", "user_id": user_id}
                }
            item = conversations.get(storage_id)
            if not isinstance(item, dict):
                raise ValueError("会话不存在")
            if is_group:
                activity = as_float(group_activity_score)
                if activity is None:
                    raise ValueError("群聊活跃度必须是数字")
                item["group_activity_score"] = max(0.0, min(100.0, activity))
                item["last_group_activity_at"] = time.time()
            else:
                score = as_float(affection_score)
                if score is None:
                    raise ValueError("好感度必须是数字")
                item["affection_score"] = max(0.0, min(100.0, score))
                item["affection_initialized"] = True
                item["last_affection_idle_decay_at"] = time.time()
            item["proactive_override"] = normalize_proactive_override(proactive_override)
            if not is_group:
                item["trust_tier"] = normalize_trust_tier(trust_tier)
            backup = self.backup("relationship")
            self.write(data)
            relationship = {
                "affection_score": item.get("affection_score"),
                "group_activity_score": item.get("group_activity_score"),
                "proactive_override": item["proactive_override"],
            }
            if not is_group:
                relationship["trust_tier"] = item.get("trust_tier", "probation")
            return backup, relationship

    def delete_conversation(self, conversation_id: str) -> Path:
        with self._lock:
            data = self.load()
            conversations = self.conversations(data)
            if conversation_id not in conversations:
                raise ValueError("会话不存在")
            backup = self.backup("delete")
            conversations.pop(conversation_id, None)
            self.write(data)
            return backup

    def load(self) -> dict[str, Any]:
        if not self.memory_path.exists():
            return {"version": 2, "conversations": {}}
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                data = json.loads(self.memory_path.read_text(encoding="utf-8-sig", errors="replace"))
                break
            except (PermissionError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= 3:
                    if isinstance(exc, json.JSONDecodeError):
                        raise ValueError(f"记忆文件不是有效 JSON: {exc}") from exc
                    raise
                time.sleep(0.03 * (attempt + 1))
        else:  # pragma: no cover - defensive, loop either breaks or raises
            raise ValueError(f"无法读取记忆文件: {last_error}")
        return data if isinstance(data, dict) else {"version": 2, "conversations": {}}

    def conversations(self, data: dict[str, Any]) -> dict[str, Any]:
        conversations = data.setdefault("conversations", {})
        if not isinstance(conversations, dict):
            data["conversations"] = {}
            return data["conversations"]
        return conversations

    def write(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            tmp_path = self.memory_path.with_name(
                f".{self.memory_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, self.memory_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

    def backup(self, reason: str) -> Path:
        with self._lock:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            millis = int((time.time() % 1) * 1000)
            target = self.backup_dir / f"users.webui-{reason}-{timestamp}-{millis:03d}.json"
            for index in range(1, 1000):
                if not target.exists():
                    break
                target = self.backup_dir / f"users.webui-{reason}-{timestamp}-{millis:03d}-{index}.json"
            if self.memory_path.exists():
                for attempt in range(4):
                    try:
                        shutil.copy2(self.memory_path, target)
                        break
                    except PermissionError:
                        if attempt >= 3:
                            raise
                        time.sleep(0.03 * (attempt + 1))
            else:
                target.write_text(json.dumps({"version": 2, "conversations": {}}, indent=2), encoding="utf-8")
            return target


DEFAULT_MEMORY_ADMIN = MemoryAdmin()


def memory_summary() -> dict[str, Any]:
    return DEFAULT_MEMORY_ADMIN.summary()


def memory_detail(query: str) -> dict[str, Any]:
    return DEFAULT_MEMORY_ADMIN.detail(query)


def save_memory_conversation(conversation_id: str, content: dict[str, Any]) -> Path:
    return DEFAULT_MEMORY_ADMIN.save_conversation(conversation_id, content)


def update_memory_relationship(
    conversation_id: str,
    affection_score: Any,
    proactive_override: Any,
    group_activity_score: Any = None,
    trust_tier: Any = None,
) -> tuple[Path, dict[str, Any]]:
    return DEFAULT_MEMORY_ADMIN.update_relationship(
        conversation_id,
        affection_score,
        proactive_override,
        group_activity_score,
        trust_tier,
    )


def delete_memory_conversation(conversation_id: str) -> Path:
    return DEFAULT_MEMORY_ADMIN.delete_conversation(conversation_id)


def backup_memory(reason: str) -> Path:
    return DEFAULT_MEMORY_ADMIN.backup(reason)


def memory_summary_item(
    conversation_id: str,
    item: dict[str, Any],
    display_name: str | None = None,
    related_count: int = 1,
) -> dict[str, Any]:
    counts = memory_counts(item)
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    summary = natural_memory_summary(item)
    resolved_name = display_name or memory_display_name(conversation_id, item)
    proactive_state, proactive_blocked = group_proactive_state(conversation_id, item)
    return {
        "id": conversation_id,
        "kind": memory_kind(conversation_id),
        "type": memory_type_label(conversation_id),
        "display_name": resolved_name,
        "summary": summary,
        "messages": item.get("message_count", 0),
        "last_user_at": item.get("last_user_at"),
        "last_user_at_text": format_timestamp(item.get("last_user_at")),
        "last_bot_at": item.get("last_bot_at"),
        "affection": item.get("affection_score"),
        "affection_label": affection_label(item.get("affection_score")),
        "activity": item.get("group_activity_score"),
        "activity_label": group_activity_label(item.get("group_activity_score")),
        "proactive_override": normalize_proactive_override(item.get("proactive_override")),
        "trust_tier": normalize_trust_tier(item.get("trust_tier")),
        "trust_label": trust_tier_label(item.get("trust_tier")),
        "proactive_state": proactive_state,
        "proactive_blocked": proactive_blocked,
        "target": target,
        "related_count": related_count,
        "history_count": len(item.get("history") or []),
        "memory_counts": counts,
        "searchable": " ".join(
            [
                conversation_id,
                resolved_name,
                str(target.get("user_id") or ""),
                str(target.get("group_id") or ""),
                summary,
            ]
        ),
    }


def person_summary_item(conversations: dict[str, Any], user_id: str) -> dict[str, Any]:
    item = person_content(conversations, user_id)
    related = person_related_keys(conversations, user_id)
    summary = memory_summary_item(
        f"person:{user_id}",
        item,
        display_name=person_display_name(conversations, user_id),
        related_count=len(related),
    )
    summary["searchable"] = f"{summary.get('searchable', '')} {' '.join(related)}"
    return summary


def memory_detail_payload(
    conversation_id: str,
    item: dict[str, Any],
    display_name: str | None = None,
    storage_id: str | None = None,
    related_conversations: list[str] | None = None,
    group_infos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": True,
        "id": conversation_id,
        "kind": memory_kind(conversation_id),
        "type": memory_type_label(conversation_id),
        "display_name": display_name or memory_display_name(conversation_id, item),
        "natural": natural_memory_detail(item),
        "affection_label": affection_label(item.get("affection_score")),
        "activity_label": group_activity_label(item.get("group_activity_score")),
        "proactive_override": normalize_proactive_override(item.get("proactive_override")),
        "trust_tier": normalize_trust_tier(item.get("trust_tier")),
        "trust_label": trust_tier_label(item.get("trust_tier")),
        "memory_counts": memory_counts(item),
        "layers": memory_layers(item),
        "history_count": len(item.get("history") or []),
        "content": item,
    }
    if storage_id:
        payload["storage_id"] = storage_id
    if related_conversations is not None:
        payload["related_conversations"] = related_conversations
    if group_infos is not None:
        payload["group_infos"] = group_infos
    return payload


def storage_memory_id(memory_id: str) -> str:
    if memory_id.startswith("person:"):
        return "private:" + memory_id.split(":", 1)[1]
    return memory_id


def person_user_ids(conversations: dict[str, Any]) -> list[str]:
    ids = {
        user_id
        for key, item in conversations.items()
        if isinstance(item, dict)
        for user_id in [person_user_id(key, item)]
        if user_id
    }
    return sorted(
        ids,
        key=lambda user_id: _safe_float(person_content(conversations, user_id).get("last_user_at")),
        reverse=True,
    )


def person_user_id(conversation_id: str, item: dict[str, Any]) -> str:
    if memory_kind(conversation_id) not in {"private", "member", "person"}:
        return ""
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    user_id = str(
        target.get("user_id")
        or parse_memory_id_piece(conversation_id, "private")
        or parse_memory_id_piece(conversation_id, "user")
        or ""
    )
    return user_id.strip()


def person_related_keys(conversations: dict[str, Any], user_id: str) -> list[str]:
    related = [
        key
        for key, item in conversations.items()
        if isinstance(item, dict) and person_user_id(key, item) == str(user_id)
    ]
    return sorted(
        related,
        key=lambda key: (
            0 if key == f"private:{user_id}" else 1,
            -_safe_float(
                conversations.get(key, {}).get("last_user_at")
                if isinstance(conversations.get(key), dict)
                else 0
            ),
            key,
        ),
    )


def person_content(conversations: dict[str, Any], user_id: str) -> dict[str, Any]:
    related = person_related_keys(conversations, user_id)
    private_id = f"private:{user_id}"
    base = conversations.get(private_id) if isinstance(conversations.get(private_id), dict) else {}
    merged = dict(base)
    merged["target"] = {"message_type": "private", "user_id": user_id}
    merged["message_count"] = sum_int(conversations, related, "message_count")
    merged["bot_reply_count"] = sum_int(conversations, related, "bot_reply_count")
    merged["last_user_at"] = max_float(conversations, related, "last_user_at")
    merged["last_bot_at"] = max_float(conversations, related, "last_bot_at")
    merged["history"] = merged_history(conversations, related)
    merged["structured_memory"] = merged_structured_memory(conversations, related)
    merged["related_conversations"] = related
    return merged


def person_group_infos(conversations: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    for key in person_related_keys(conversations, user_id):
        if memory_kind(key) != "member":
            continue
        item = conversations.get(key)
        if not isinstance(item, dict):
            continue
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        group_id = str(target.get("group_id") or parse_memory_id_piece(key, "group") or "")
        history = item.get("history") if isinstance(item.get("history"), list) else []
        infos.append(
            {
                "id": key,
                "group_id": group_id,
                "nickname": latest_nickname(history),
                "display_name": memory_display_name(key, item),
                "messages": item.get("message_count", 0),
                "last_user_at": item.get("last_user_at"),
                "last_user_at_text": format_timestamp(item.get("last_user_at")),
                "memory_counts": memory_counts(item),
                "summary": natural_memory_summary(item),
            }
        )
    return infos


def person_display_name(conversations: dict[str, Any], user_id: str) -> str:
    for key in person_related_keys(conversations, user_id):
        item = conversations.get(key)
        if not isinstance(item, dict):
            continue
        history = item.get("history") if isinstance(item.get("history"), list) else []
        nickname = latest_nickname(history)
        if nickname:
            return f"{nickname}（QQ {user_id} / 统一人物档案）"
    return f"QQ {user_id}（统一人物档案）"


def merged_structured_memory(
    conversations: dict[str, Any],
    related: list[str],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"l1": [], "l2": [], "l3": [], "candidates": []}
    for bucket in ("l1", "l2", "candidates"):
        seen: set[str] = set()
        for key in related:
            item = conversations.get(key)
            if not isinstance(item, dict):
                continue
            structured = item.get("structured_memory")
            if not isinstance(structured, dict):
                continue
            for entry in structured.get(bucket, []):
                if not isinstance(entry, dict):
                    continue
                identity = str(
                    entry.get("memory_key")
                    or f"{entry.get('category')}:{entry.get('key')}:{entry.get('value')}"
                )
                if identity in seen:
                    continue
                copied = dict(entry)
                copied.setdefault("source_conversation", key)
                result[bucket].append(copied)
                seen.add(identity)
    # L3 是会话级上下文，人物档案只保留私聊主档案的窗口，不能把多个群聊上下文拼成一份。
    private_key = next((key for key in related if key.startswith("private:")), "")
    private_item = conversations.get(private_key)
    if isinstance(private_item, dict):
        structured = private_item.get("structured_memory")
        if isinstance(structured, dict):
            result["l3"] = [
                dict(entry)
                for entry in structured.get("l3", [])
                if isinstance(entry, dict)
            ][-8:]
    return result


def merged_history(conversations: dict[str, Any], related: list[str]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for key in related:
        item = conversations.get(key)
        if not isinstance(item, dict):
            continue
        for entry in item.get("history") or []:
            if isinstance(entry, dict):
                copied = dict(entry)
                copied.setdefault("source_conversation", key)
                history.append(copied)
    history.sort(key=lambda entry: as_float(entry.get("at")) or 0.0)
    return history[-300:]


def sum_int(conversations: dict[str, Any], keys: list[str], field: str) -> int:
    return sum(
        int((conversations.get(key) or {}).get(field) or 0)
        for key in keys
        if isinstance(conversations.get(key), dict)
    )


def max_float(conversations: dict[str, Any], keys: list[str], field: str) -> float:
    values = [
        as_float((conversations.get(key) or {}).get(field)) or 0.0
        for key in keys
        if isinstance(conversations.get(key), dict)
    ]
    return max(values or [0.0])


def memory_kind(conversation_id: str) -> str:
    if conversation_id.startswith("person:"):
        return "person"
    if conversation_id.startswith("private:"):
        return "private"
    if ":user:" in conversation_id:
        return "member"
    if conversation_id.startswith("group:"):
        return "group"
    return "unknown"


def memory_type_label(conversation_id: str) -> str:
    kind = memory_kind(conversation_id)
    return {
        "person": "人物档案",
        "private": "私聊",
        "member": "群内用户",
        "group": "群聊",
    }.get(kind, "未知")


def memory_display_name(conversation_id: str, item: dict[str, Any]) -> str:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    history = item.get("history") if isinstance(item.get("history"), list) else []
    nickname = latest_nickname(history)
    user_id = str(
        target.get("user_id")
        or parse_memory_id_piece(conversation_id, "private")
        or parse_memory_id_piece(conversation_id, "user")
        or ""
    )
    group_id = str(target.get("group_id") or parse_memory_id_piece(conversation_id, "group") or "")
    kind = memory_kind(conversation_id)
    if kind == "private":
        return f"{nickname}（QQ {user_id}）" if nickname else f"QQ {user_id or conversation_id.removeprefix('private:')}"
    if kind == "member":
        user_piece = user_id or parse_memory_id_piece(conversation_id, "user")
        group_piece = group_id or parse_memory_id_piece(conversation_id, "group")
        return (
            f"{nickname}（群 {group_piece} / QQ {user_piece}）"
            if nickname
            else f"群 {group_piece} 的 QQ {user_piece}"
        )
    if kind == "group":
        return f"群 {group_id or conversation_id.removeprefix('group:')}"
    return nickname or conversation_id


def parse_memory_id_piece(conversation_id: str, kind: str) -> str:
    if kind == "private" and conversation_id.startswith("private:"):
        return conversation_id.split(":", 1)[1]
    if kind == "group" and conversation_id.startswith("group:"):
        parts = conversation_id.split(":")
        return parts[1] if len(parts) > 1 else ""
    if kind == "user" and ":user:" in conversation_id:
        return conversation_id.rsplit(":user:", 1)[1]
    return ""


def latest_nickname(history: list[Any]) -> str:
    for entry in reversed(history[-300:]):
        if not isinstance(entry, dict):
            continue
        nickname = clean_plain(str(entry.get("nickname") or ""))
        if nickname:
            return nickname[:40]
    return ""


def natural_memory_summary(item: dict[str, Any]) -> str:
    lines = [line for line in natural_memory_detail(item).splitlines() if line.strip()]
    return "；".join(lines[:3])[:220] or "暂无可读摘要，可能只有原始聊天统计。"


def natural_memory_detail(item: dict[str, Any]) -> str:
    lines: list[str] = []
    layers = memory_layers(item)
    l1 = layers["l1"]
    l2 = layers["l2"]
    candidates = layers["candidates"]
    rules = item.get("accepted_iteration_rules") if isinstance(item.get("accepted_iteration_rules"), list) else []

    profile_lines = natural_memory_values(
        [
            m
            for m in l1
            if str(m.get("category") or "") in {"profile_fact", "interest", "preference", "habit"}
        ],
        limit=6,
    )
    if profile_lines:
        lines.append("用户信息：" + "；".join(profile_lines))

    style_lines = natural_memory_values(
        [m for m in l1 if str(m.get("category") or "") == "communication_style"],
        limit=4,
    )
    if style_lines:
        lines.append("聊天习惯：" + "；".join(style_lines))

    event_lines = natural_memory_values(l2, limit=6)
    if event_lines:
        lines.append("最近重要事件：" + "；".join(event_lines))

    candidate_lines = natural_memory_values(candidates, limit=3)
    if candidate_lines:
        lines.append("待确认偏好：" + "；".join(candidate_lines))

    clean_rules = [
        shorten_plain(str(rule.get("rule") or ""), 42)
        for rule in rules
        if isinstance(rule, dict) and useful_plain_text(str(rule.get("rule") or ""))
    ][:4]
    if clean_rules:
        lines.append("用户明确要求：" + "；".join(clean_rules))

    if not lines:
        lines.append("暂无已确认的 L1 用户特点或活跃的 L2 事件；L3 当前会话请打开对应分页查看。")
    return "\n".join(lines)


def memory_layers(item: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """给 WebUI 返回严格按三级记忆定义分组的数据。

    L1 只包含已经确认的用户特点；L2 只包含事件和日程；
    L3 只包含滚动会话上下文。候选记忆单独返回，避免一次聊天被误显示成用户事实。
    """
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l1 = [
        entry
        for entry in structured.get("l1", [])
        if isinstance(entry, dict)
        and _displayable_trait_entry(entry)
    ]
    l2 = [
        entry
        for entry in structured.get("l2", [])
        if isinstance(entry, dict)
        and entry.get("category") in {"event", "schedule", "important_interaction"}
    ]
    l3 = [entry for entry in structured.get("l3", []) if isinstance(entry, dict)]
    if not l3:
        # 兼容旧记忆文件：旧版本没有持久化 L3，暂时把最近 8 条历史映射为
        # 会话上下文展示；它只进入 L3，不会进入用户特点或事件层。
        history = item.get("history") if isinstance(item.get("history"), list) else []
        for entry in history[-8:]:
            if not isinstance(entry, dict):
                continue
            text = clean_plain(str(entry.get("text") or ""))
            if not text:
                continue
            l3.append(
                {
                    "layer": "L3",
                    "category": "session_context",
                    "key": "历史兼容窗口",
                    "text": text,
                    "value": text,
                    "role": entry.get("role") or "user",
                    "at": entry.get("at"),
                }
            )
    candidates = [
        entry
        for entry in structured.get("candidates", [])
        if isinstance(entry, dict) and _displayable_trait_entry(entry)
    ]
    return {"l1": l1, "l2": l2, "l3": l3[-8:], "candidates": candidates}


def _displayable_trait_entry(entry: dict[str, Any]) -> bool:
    """过滤明显的模型回声、URL 和过长临时句，避免污染用户特点面板。"""
    category = str(entry.get("category") or "")
    value = clean_plain(str(entry.get("value") or ""))
    if str(entry.get("state") or "active") in {"expired", "deleted", "rejected"}:
        return False
    if category not in {"profile_fact", "interest", "preference", "habit", "communication_style"}:
        return False
    if not useful_plain_text(value) or len(value) > 64:
        return False
    if any(marker in value for marker in ("你", "亚托莉", "http://", "https://", "...", "…")):
        return False
    if category == "communication_style" and not any(
        marker in value
        for marker in ("默认", "不要", "别", "回复偏好", "短句", "少铺垫", "有逻辑")
    ):
        return False
    return True


def natural_memory_values(memories: list[dict[str, Any]], limit: int = 5) -> list[str]:
    result: list[str] = []
    for memory in memories:
        value = clean_plain(str(memory.get("value") or memory.get("key") or ""))
        category = str(memory.get("category") or "").strip()
        if not useful_plain_text(value):
            continue
        label = memory_category_label(category)
        result.append(f"{label}{shorten_plain(value, 42)}" if label else shorten_plain(value, 42))
        if len(result) >= limit:
            break
    return result


def memory_category_label(category: str) -> str:
    return {
        "interest": "兴趣：",
        "preference": "偏好：",
        "profile_fact": "资料：",
        "habit": "习惯：",
        "communication_style": "说话习惯：",
        "schedule": "日程：",
        "event": "事件：",
        "important_interaction": "互动：",
    }.get(category, "")


def normalize_manual_memory_content(conversation_id: str, content: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(content)
    is_group = conversation_id.startswith("group:") and ":user:" not in conversation_id
    if is_group:
        normalized["group_activity_score"] = clamp_float(
            normalized.get("group_activity_score"), 0.0, 100.0, 0.0
        )
        normalized["last_group_activity_at"] = time.time()
    else:
        normalized["affection_score"] = clamp_float(
            normalized.get("affection_score"), 0.0, 100.0, 0.0
        )
        normalized["affection_initialized"] = True
        normalized["last_affection_idle_decay_at"] = time.time()
    normalized["proactive_override"] = normalize_proactive_override(
        normalized.get("proactive_override")
    )
    if not is_group:
        normalized["trust_tier"] = normalize_trust_tier(normalized.get("trust_tier"))
    structured = normalized.get("structured_memory")
    if not isinstance(structured, dict):
        structured = {}
    normalized["structured_memory"] = structured
    default_visibility = default_memory_visibility(conversation_id)
    now = time.time()
    for layer in ("l1", "l2", "l3", "candidates"):
        entries = structured.get(layer)
        if not isinstance(entries, list):
            structured[layer] = []
            continue
        normalized_entries = []
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            entry = dict(raw)
            category = clean_plain(str(entry.get("category") or "profile_fact")) or "profile_fact"
            if layer == "l3":
                category = "session_context"
            key = clean_plain(str(entry.get("key") or entry.get("memory_key") or category))
            value = clean_plain(str(entry.get("value") or ""))
            entry["category"] = category
            entry["key"] = key
            entry["value"] = value
            memory_key = f"{category}:{key}"
            entry["memory_key"] = memory_key
            entry["id"] = str(entry.get("id") or memory_id(layer, memory_key))
            entry["source"] = "webui"
            entry["source_type"] = entry.get("source_type") or "manual"
            entry["locked"] = True
            entry["visibility"] = entry.get("visibility") or default_visibility
            entry["updated_at"] = now
            entry.setdefault("created_at", now)
            if layer == "l1":
                entry["layer"] = "L1"
                entry["confidence"] = clamp_float(entry.get("confidence"), 0.0, 1.0, 0.85)
            elif layer == "l2":
                entry["layer"] = "L2"
                entry["confidence"] = clamp_float(entry.get("confidence"), 0.0, 1.0, 0.75)
                entry["activity"] = clamp_float(entry.get("activity"), 0.0, 1.0, 1.0)
                entry.setdefault("state", "active")
            elif layer == "l3":
                entry["layer"] = "L3"
                entry["category"] = "session_context"
                entry["text"] = clean_plain(str(entry.get("text") or value))
                entry["value"] = entry["text"]
                entry["key"] = key or "当前会话"
                entry["memory_key"] = f"session_context:{entry['key']}"
                entry["source"] = entry.get("source") or "webui"
            else:
                entry["confidence"] = clamp_float(entry.get("confidence"), 0.0, 1.0, 0.75)
                entry["evidence_count"] = max(1, int(as_float(entry.get("evidence_count")) or 1))
            normalized_entries.append(entry)
        structured[layer] = normalized_entries
    return normalized


def normalize_proactive_override(value: Any) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in {"auto", "allow", "deny"} else "auto"


def normalize_trust_tier(value: Any) -> str:
    normalized = str(value or "probation").strip().lower()
    return normalized if normalized in {"probation", "approved", "trusted", "blocked"} else "probation"


def trust_tier_label(value: Any) -> str:
    return {
        "probation": "观察中",
        "approved": "白名单",
        "trusted": "可信用户",
        "blocked": "已屏蔽",
    }[normalize_trust_tier(value)]


def default_memory_visibility(conversation_id: str) -> str:
    if conversation_id.startswith("group:") and ":user:" in conversation_id:
        group_id = parse_memory_id_piece(conversation_id, "group")
        return f"group:{group_id}" if group_id else "public"
    if conversation_id.startswith("group:"):
        group_id = parse_memory_id_piece(conversation_id, "group")
        return f"group:{group_id}" if group_id else "public"
    return "private"


def memory_id(layer: str, key: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff:-]+", "_", key)
    return f"{layer}:{safe[:80]}"


def clamp_float(value: Any, low: float, high: float, default: float) -> float:
    number = as_float(value)
    if number is None:
        number = default
    return max(low, min(high, number))


def removed_person_values(previous: Any, current: dict[str, Any]) -> set[str]:
    if not isinstance(previous, dict):
        return set()
    before = positive_person_values(previous)
    after = positive_person_values(current)
    return before - after


def positive_person_values(item: dict[str, Any]) -> set[str]:
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    values: set[str] = set()
    for bucket in ("l1", "candidates"):
        for entry in structured.get(bucket, []):
            if not isinstance(entry, dict) or not is_positive_person_entry(entry):
                continue
            value = clean_plain(str(entry.get("value") or ""))
            if value:
                values.add(value)
    return values


def is_positive_person_entry(entry: dict[str, Any]) -> bool:
    category = str(entry.get("category") or "")
    key = str(entry.get("key") or "")
    if category not in {"interest", "preference", "habit", "profile_fact"}:
        return False
    return "讨厌" not in key and "不喜欢" not in key


def remove_values_from_same_person_members(
    conversations: dict[str, Any],
    conversation_id: str,
    values: set[str],
) -> None:
    if not conversation_id.startswith("private:") or not values:
        return
    user_id = conversation_id.split(":", 1)[1]
    for key, item in conversations.items():
        if not key.endswith(f":user:{user_id}") or not isinstance(item, dict):
            continue
        structured = item.get("structured_memory")
        if not isinstance(structured, dict):
            continue
        for bucket in ("l1", "candidates"):
            entries = structured.get(bucket)
            if not isinstance(entries, list):
                continue
            structured[bucket] = [
                entry
                for entry in entries
                if not (
                    isinstance(entry, dict)
                    and is_positive_person_entry(entry)
                    and clean_plain(str(entry.get("value") or "")) in values
                )
            ]


def memory_counts(item: dict[str, Any]) -> dict[str, int]:
    layers = memory_layers(item)
    l1 = layers["l1"]
    l2 = layers["l2"]
    # 旧 history 映射出的兼容 L3 只用于查看，不计入结构化记忆统计。
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l3 = [m for m in structured.get("l3", []) if isinstance(m, dict)]
    candidates = layers["candidates"]
    return {
        "l1": len(l1),
        "l2": len(l2),
        "l3": len(l3),
        "candidates": len(candidates),
        "total": len(l1) + len(l2) + len(l3) + len(candidates),
    }


def format_timestamp(value: Any) -> str:
    timestamp = as_float(value)
    if not timestamp or timestamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def affection_label(value: Any) -> str:
    score = as_float(value)
    if score is None:
        return "普通"
    if score >= 84:
        return "非常亲近"
    if score >= 68:
        return "亲近"
    if score >= 42:
        return "自然"
    if score >= 24:
        return "克制"
    return "保持距离"


def group_activity_label(value: Any) -> str:
    score = as_float(value)
    if score is None:
        return "普通"
    if score >= 72:
        return "热闹"
    if score >= 38:
        return "普通"
    return "冷清"


def group_proactive_state(conversation_id: str, item: dict[str, Any]) -> tuple[str, bool]:
    if memory_kind(conversation_id) != "group":
        return "", False
    max_days = configured_group_silence_days()
    last_user_at = as_float(item.get("last_user_at"))
    if not last_user_at:
        return "未建立主动发言目标", True
    elapsed_days = max(0.0, (time.time() - last_user_at) / 86400)
    if max_days <= 0:
        return "主动发言未按天数限制", False
    if elapsed_days > max_days:
        return f"已静默 {elapsed_days:.1f} 天，停止主动发言", True
    return f"{elapsed_days:.1f} 天内有消息，可低频主动", False


def configured_group_silence_days() -> int:
    # Import here so tests can use MemoryAdmin with arbitrary paths without loading .env.
    from atri_qq_bot.config import load_config

    try:
        return int(load_config().group_proactive_max_silence_days)
    except Exception:
        return 3


def useful_plain_text(text: str) -> bool:
    text = clean_plain(text)
    if not text or len(text) < 2:
        return False
    if re.fullmatch(r"[\W_0-9]+", text):
        return False
    return True


def clean_plain(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or looks_like_bad_text(text):
        return ""
    return text


def looks_like_bad_text(text: str) -> bool:
    if "\ufffd" in text:
        return True
    if re.search(r"(閿焲闁縷锟?){2,}", text):
        return True
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_count < 6:
        return False
    mojibake_hits = len(re.findall(r"[缂佸鐒﹀ù锝囧У濡叉悂宕ュΔ鍐╃暠闁诲妽閸╂盯骞嬮幋婊呯憹]", text))
    return mojibake_hits / max(chinese_count, 1) > 0.65


def shorten_plain(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float:
    return as_float(value) or 0.0
