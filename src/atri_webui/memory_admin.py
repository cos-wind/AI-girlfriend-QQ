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


class MemoryAdmin:
    def __init__(self, memory_path: Path = MEMORY_PATH, backup_dir: Path = MEMORY_BACKUP_DIR) -> None:
        self.memory_path = memory_path
        self.backup_dir = backup_dir
        self._lock = threading.RLock()

    def summary(self) -> dict[str, Any]:
        data = self.load()
        conversations = self.conversations(data)
        items = []
        for key, item in sorted(
            conversations.items(),
            key=lambda pair: _safe_float((pair[1] or {}).get("last_user_at") if isinstance(pair[1], dict) else 0),
            reverse=True,
        ):
            if not isinstance(item, dict):
                continue
            counts = memory_counts(item)
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            summary = natural_memory_summary(item)
            display_name = memory_display_name(key, item)
            proactive_state, proactive_blocked = group_proactive_state(key, item)
            items.append(
                {
                    "id": key,
                    "kind": memory_kind(key),
                    "type": memory_type_label(key),
                    "display_name": display_name,
                    "summary": summary,
                    "messages": item.get("message_count", 0),
                    "last_user_at": item.get("last_user_at"),
                    "last_user_at_text": format_timestamp(item.get("last_user_at")),
                    "last_bot_at": item.get("last_bot_at"),
                    "affection": item.get("affection_score"),
                    "affection_label": affection_label(item.get("affection_score")),
                    "activity": item.get("group_activity_score"),
                    "activity_label": group_activity_label(item.get("group_activity_score")),
                    "proactive_state": proactive_state,
                    "proactive_blocked": proactive_blocked,
                    "target": target,
                    "history_count": len(item.get("history") or []),
                    "memory_counts": counts,
                    "searchable": " ".join(
                        [
                            key,
                            display_name,
                            str(target.get("user_id") or ""),
                            str(target.get("group_id") or ""),
                            summary,
                        ]
                    ),
                }
            )
        return {"path": str(self.memory_path), "conversations": len(items), "items": items}

    def detail(self, query: str) -> dict[str, Any]:
        conversation_id = parse_qs(query).get("id", [""])[0]
        data = self.load()
        conversations = self.conversations(data)
        item = conversations.get(conversation_id)
        if not isinstance(item, dict):
            return {"ok": False, "error": "memory not found"}
        return {
            "ok": True,
            "id": conversation_id,
            "kind": memory_kind(conversation_id),
            "type": memory_type_label(conversation_id),
            "display_name": memory_display_name(conversation_id, item),
            "natural": natural_memory_detail(item),
            "affection_label": affection_label(item.get("affection_score")),
            "activity_label": group_activity_label(item.get("group_activity_score")),
            "memory_counts": memory_counts(item),
            "history_count": len(item.get("history") or []),
            "content": item,
        }

    def save_conversation(self, conversation_id: str, content: dict[str, Any]) -> Path:
        with self._lock:
            data = self.load()
            conversations = self.conversations(data)
            if conversation_id not in conversations:
                raise ValueError("会话不存在")
            if not isinstance(content, dict):
                raise ValueError("记忆内容必须是 JSON 对象")
            backup = self.backup("edit")
            conversations[conversation_id] = content
            self.write(data)
            return backup

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
        try:
            data = json.loads(self.memory_path.read_text(encoding="utf-8-sig", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"记忆文件不是有效 JSON: {exc}") from exc
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
                shutil.copy2(self.memory_path, target)
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


def delete_memory_conversation(conversation_id: str) -> Path:
    return DEFAULT_MEMORY_ADMIN.delete_conversation(conversation_id)


def backup_memory(reason: str) -> Path:
    return DEFAULT_MEMORY_ADMIN.backup(reason)


def memory_kind(conversation_id: str) -> str:
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
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l1 = [m for m in structured.get("l1", []) if isinstance(m, dict)]
    l2 = [m for m in structured.get("l2", []) if isinstance(m, dict)]
    candidates = [m for m in structured.get("candidates", []) if isinstance(m, dict)]
    rules = item.get("accepted_iteration_rules") if isinstance(item.get("accepted_iteration_rules"), list) else []
    topics = item.get("topic_words") if isinstance(item.get("topic_words"), list) else []
    history = item.get("history") if isinstance(item.get("history"), list) else []

    profile_lines = natural_memory_values(
        [m for m in l1 if str(m.get("category") or "") in {"profile_fact", "interest"}],
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

    clean_topics = [shorten_plain(str(x), 18) for x in topics if useful_plain_text(str(x))][:8]
    if clean_topics:
        lines.append("常聊话题：" + "、".join(clean_topics))

    clean_rules = [
        shorten_plain(str(rule.get("rule") or ""), 42)
        for rule in rules
        if isinstance(rule, dict) and useful_plain_text(str(rule.get("rule") or ""))
    ][:4]
    if clean_rules:
        lines.append("用户明确要求：" + "；".join(clean_rules))

    recent = []
    for entry in history[-10:]:
        if not isinstance(entry, dict):
            continue
        role = "用户" if entry.get("role") == "user" else "亚托莉"
        text = clean_plain(str(entry.get("text") or ""))
        if text:
            recent.append(f"{role}：{shorten_plain(text, 40)}")
    if recent:
        lines.append("最近聊天：" + " / ".join(recent[-4:]))

    if not lines:
        lines.append("暂无可读摘要。可以打开详情查看或编辑原始 JSON。")
    return "\n".join(lines)


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
        "profile_fact": "资料：",
        "communication_style": "说话习惯：",
        "schedule": "日程：",
        "event": "事件：",
        "important_interaction": "互动：",
    }.get(category, "")


def memory_counts(item: dict[str, Any]) -> dict[str, int]:
    structured = item.get("structured_memory") if isinstance(item.get("structured_memory"), dict) else {}
    l1 = [m for m in structured.get("l1", []) if isinstance(m, dict)]
    l2 = [m for m in structured.get("l2", []) if isinstance(m, dict)]
    candidates = [m for m in structured.get("candidates", []) if isinstance(m, dict)]
    return {
        "l1": len(l1),
        "l2": len(l2),
        "candidates": len(candidates),
        "total": len(l1) + len(l2) + len(candidates),
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
