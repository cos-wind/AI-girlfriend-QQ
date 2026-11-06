from __future__ import annotations

from atri_bot.memory.rule_common import *  # noqa: F403
from atri_bot.memory.ingestion import deterministic_operations, _style_rule_value

def is_memory_pollution_text(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return False
    if has_illegal_language_or_garbage(compact):
        return True
    return any(pattern in compact for pattern in MEMORY_POLLUTION_PATTERNS)

def _ensure_structured_memory(item: dict[str, Any]) -> dict[str, Any]:
    memory = item.get("structured_memory")
    if not isinstance(memory, dict):
        memory = {}
        item["structured_memory"] = memory
    # L1=稳定用户特点，L2=带时间的事件，L3=当前会话短上下文。
    # candidates 只表示尚未达到确认门槛的候选，不应冒充已确认特点。
    for key in ("l1", "l2", "l3", "candidates"):
        if not isinstance(memory.get(key), list):
            memory[key] = []
    item.setdefault("affection_score", DEFAULT_AFFECTION)
    return memory

def _append_session_l3(
    session_l3: dict[str, list[dict[str, Any]]],
    conversation_id: str,
    text: str,
    now: float,
    memory: dict[str, Any] | None = None,
) -> None:
    if _is_noisy_for_long_memory(text):
        return
    items = list(session_l3.get(conversation_id) or [])
    # 进程重启后 session_l3 是空的，必须从持久化窗口恢复，否则第一条
    # 新消息会把磁盘中的旧 L3 全部覆盖掉。
    if not items and memory is not None:
        items = list(memory.get("l3") or [])
    entry = {
        "layer": "L3",
        "category": "session_context",
        "key": "当前会话",
        "text": _shorten(text, 120),
        "value": _shorten(text, 120),
        "source": "user",
        "at": now,
        "updated_at": now,
    }
    items.append(entry)
    session_l3[conversation_id] = items[-8:]
    if memory is not None:
        # 保存一份极短滚动窗口，重启后仍可展示和恢复上下文；它不是长期用户画像。
        memory["l3"] = list(items[-8:])

def _remember_structured_from_user(
    item: dict[str, Any],
    text: str,
    now: float,
    affection_event: dict[str, Any] | None = None,
    visibility: str = "private",
    source_context: str | None = None,
    scope_kind: str = "person",
) -> None:
    # 结构化记忆采用“先纠正冲突 -> 过滤噪声 -> 抽取 L2 事件/L1 特征 -> 建立关联”
    # 的顺序。L3 是会话滚动窗口，不在这里被误写成永久用户画像。
    memory = _ensure_structured_memory(item)
    if scope_kind != "group":
        _apply_user_corrections(memory, text, now, visibility, source_context)
    style_candidate = _actionable_style_candidate(text, now, visibility, source_context) if scope_kind != "group" else None
    style_memory_id = _upsert_l1_candidate(memory, style_candidate, now) if style_candidate else None
    if _is_negative_quality_complaint(text):
        if style_memory_id:
            _link_related_memories(memory, [style_memory_id])
        return
    _remember_important_interaction(item, text, now, affection_event)

    if _is_noisy_for_long_memory(text):
        if style_memory_id:
            _link_related_memories(memory, [style_memory_id])
        return

    new_ids: list[str] = [style_memory_id] if style_memory_id else []
    current_affection = float(item.get("affection_score", DEFAULT_AFFECTION))
    for event in _extract_l2_events(text, now, visibility, source_context, scope_kind):
        _attach_affection_metadata(event, affection_event, current_affection)
        memory_id = _upsert_l2(memory, event, now)
        if memory_id:
            new_ids.append(memory_id)

    for candidate in _extract_l1_candidates(text, now, visibility, source_context, scope_kind):
        if style_candidate and candidate["category"] == "communication_style":
            continue
        _attach_affection_metadata(candidate, affection_event, current_affection)
        memory_id = _upsert_l1_candidate(memory, candidate, now)
        if memory_id:
            new_ids.append(memory_id)

    _link_related_memories(memory, new_ids)

def _actionable_style_candidate(
    text: str,
    now: float,
    visibility: str = "private",
    source_context: str | None = None,
) -> dict[str, Any] | None:
    return next((candidate for candidate in _extract_l1_candidates(text, now, visibility, source_context)
                 if candidate["category"] == "communication_style"), None)


def _extract_l1_candidates(
    text: str, now: float, visibility: str = "private",
    source_context: str | None = None, scope_kind: str = "person",
) -> list[dict[str, Any]]:
    candidates = []
    for operation in deterministic_operations(text, now=now, visibility=visibility,
            source_context=source_context, scope_kind=scope_kind):
        if operation["layer"] != "L1":
            continue
        candidate = _candidate(operation["category"], operation["key"], operation["value"],
            operation["confidence"], operation["source_type"], now, visibility, source_context)
        candidate["evidence"] = operation["evidence"]
        candidate["sources"] = []
        _append_source(candidate, candidate, now)
        candidates.append(candidate)
    return candidates


def _extract_l2_events(
    text: str, now: float, visibility: str = "private",
    source_context: str | None = None, scope_kind: str = "person",
) -> list[dict[str, Any]]:
    return [dict(operation, activity=1.0, source="user", state="active",
                 last_mentioned_at=now, associations=[])
            for operation in deterministic_operations(text, now=now, visibility=visibility,
                source_context=source_context, scope_kind=scope_kind)
            if operation["layer"] == "L2"]


def _candidate(
    category: str,
    key: str,
    value: str,
    confidence: float,
    source_type: str,
    now: float,
    visibility: str = "private",
    source_context: str | None = None,
) -> dict[str, Any]:
    candidate = {
        "category": category,
        "key": key,
        "value": _shorten(value, 120),
        "confidence": confidence,
        "source_type": source_type,
        "evidence_count": 1,
        "created_at": now,
        "updated_at": now,
        "last_mentioned_at": now,
        "sources": [{"at": now, "text": _shorten(value, 120), "type": source_type}],
        "visibility": visibility,
    }
    if source_context:
        candidate["source_context"] = source_context
    return candidate

def _upsert_l1_candidate(
    memory: dict[str, Any],
    candidate: dict[str, Any],
    now: float,
) -> str | None:
    key = f"{candidate['category']}:{candidate['key']}"
    protected = _find_memory(memory["candidates"], key)
    if protected and (protected.get("locked") or protected.get("source_type") == "manual"):
        protected["last_mentioned_at"] = now
        return protected["id"]
    # Explicit self-reported facts need no second mention or background model.
    # Reuse the versioned operation seam, including manual-edit protection.
    if (candidate.get("source_type") == "explicit"
            and candidate.get("visibility", "private") == "private"
            and candidate.get("category") in {"profile_fact", "preference"}
            and float(candidate.get("confidence", 0)) >= 0.8):
        return apply_extraction_operation(
            {"structured_memory": memory},
            dict(candidate, layer="L1", operation="ADD", promote=True), now,
        )
    candidate_only = candidate.get("candidate_only") or candidate.get("source_type") in {"model", "implicit"}
    existing = None if candidate_only else _find_memory(memory["l1"], key)
    if existing:
        return apply_extraction_operation(
            {"structured_memory": memory},
            dict(candidate, layer="L1", operation="UPDATE", promote=False), now,
        )

    pending = _find_memory(memory["candidates"], key)
    if pending:
        if pending.get("locked"):
            pending["last_mentioned_at"] = now
            _append_source(pending, candidate, now)
            return pending["id"]
        if _has_same_evidence(pending, candidate, now):
            return pending["id"]
        same_claim = (pending.get("value") == candidate["value"]
                      and pending.get("source_type") == candidate.get("source_type"))
        pending["value"] = candidate["value"]
        for meta_key in ("evidence", "source_type", "candidate_only", "layer", "visibility", "source_context"):
            if meta_key in candidate:
                pending[meta_key] = candidate[meta_key]
        pending["candidate_only"] = bool(candidate_only)
        pending["confidence"] = min(1.0, max(float(pending.get("confidence", 0.0)), float(candidate["confidence"])))
        pending["evidence_count"] = int(pending.get("evidence_count", 1)) + 1 if same_claim else 1
        pending["updated_at"] = now
        pending["last_mentioned_at"] = now
        _append_source(pending, candidate, now)
    else:
        pending = dict(candidate)
        pending["id"] = _memory_id("candidate", key)
        pending["memory_key"] = key
        _append_source(pending, candidate, now)
        memory["candidates"].append(pending)

    if not candidate_only and int(pending.get("evidence_count", 1)) >= L1_CONFIRMATIONS_REQUIRED:
        promoted = {
            "id": _memory_id("l1", key),
            "layer": "L1",
            "category": pending["category"],
            "key": pending["key"],
            "memory_key": key,
            "value": pending["value"],
            "confidence": min(1.0, float(pending.get("confidence", 0.6))),
            "evidence_count": int(pending.get("evidence_count", 1)),
            "source": "user",
            "source_type": pending.get("source_type", "explicit"),
            "evidence": pending.get("evidence", ""),
            "sources": list(pending.get("sources") or []),
            "created_at": pending.get("created_at", now),
            "updated_at": now,
            "last_mentioned_at": now,
            "associations": [],
        }
        for meta_key in (
            "sentiment",
            "importance",
            "affection_snapshot",
            "visibility",
            "source_context",
        ):
            if meta_key in pending:
                promoted[meta_key] = pending[meta_key]
        memory["l1"].append(promoted)
        memory["candidates"] = [
            item for item in memory["candidates"] if item.get("memory_key") != key
        ][-20:]
        return promoted["id"]

    memory["candidates"] = list(memory["candidates"])[-20:]
    return None

def _upsert_l2(memory: dict[str, Any], event: dict[str, Any], now: float) -> str | None:
    key = f"{event['category']}:{event['key']}"
    existing = _find_memory(memory["l2"], key)
    if existing:
        if existing.get("locked") or existing.get("source_type") == "manual":
            existing["last_mentioned_at"] = now
            return existing["id"]
        existing["value"] = event["value"]
        existing["activity"] = 1.0
        existing["confidence"] = max(float(existing.get("confidence", 0.0)), float(event.get("confidence", 0.8)))
        existing["updated_at"] = now
        existing["last_mentioned_at"] = now
        existing["state"] = "active"
        for meta_key in ("visibility", "source_context"):
            if meta_key in event:
                existing[meta_key] = event[meta_key]
        _append_source(existing, event, now)
        return existing["id"]
    event = dict(event)
    event["id"] = _memory_id("l2", key)
    event["memory_key"] = key
    _append_source(event, event, now)
    memory["l2"].append(event)
    memory["l2"] = list(memory["l2"])[-30:]
    return event["id"]


def apply_extraction_operation(
    memory: dict[str, Any],
    operation: dict[str, Any],
    now: float,
) -> str | None:
    """应用后台提取器的 ADD/UPDATE/DELETE，保留证据和旧值。

    这个函数是结构化记忆的内部 seam：JSON、SQLite 索引和 WebUI 都只消费
    统一后的条目，不需要知道提取器来自规则还是本地模型。
    """
    layer = str(operation.get("layer") or "").upper()
    category = str(operation.get("category") or "").strip()
    key = _clean_value(str(operation.get("key") or ""))
    value = _clean_value(str(operation.get("value") or ""))
    action = str(operation.get("operation") or "ADD").upper()
    if layer not in {"L1", "L2"} or not key or (action != "DELETE" and not value):
        return None
    memory = _ensure_structured_memory(memory)
    bucket_name = "l1" if layer == "L1" else "l2"
    bucket = memory[bucket_name]
    memory_key = f"{category}:{key}"
    existing = _find_memory(bucket, memory_key)
    if existing and (existing.get("locked") or existing.get("source_type") == "manual"):
        return existing.get("id")
    if operation.get("candidate_only") or operation.get("source_type") in {"model", "implicit"}:
        # A proposal must never update a confirmed fact just because that key
        # already exists, nor may confidence bypass the candidate boundary.
        if action == "DELETE":
            return None
        return _upsert_l1_candidate(memory, dict(operation, candidate_only=True), now)
    if action == "DELETE":
        if existing:
            existing["state"] = "expired"
            existing["valid_to"] = now
            existing["updated_at"] = now
            _append_source(existing, operation, now)
            return existing.get("id")
        return None

    confidence = max(0.0, min(1.0, float(operation.get("confidence", 0.6))))
    if layer == "L1" and category not in {"profile_fact", "interest", "preference", "habit", "communication_style"}:
        return None
    if layer == "L2" and category not in {"event", "schedule", "important_interaction"}:
        return None

    if existing:
        if _has_same_evidence(existing, operation, now):
            return existing.get("id")
        if existing.get("locked") or existing.get("source_type") == "manual":
            # WebUI 手工确认的事实是最高优先级，历史回放和模型都不能覆盖。
            existing["last_mentioned_at"] = now
            return existing.get("id")
        old_value = str(existing.get("value") or "")
        if old_value and old_value != value:
            versions = list(existing.get("versions") or [])
            versions.append({"value": old_value, "at": now, "reason": "updated_by_user_evidence"})
            existing["versions"] = versions[-8:]
        existing["value"] = value
        for meta_key in ("evidence", "source_type", "subject_id", "evidence_start", "evidence_end", "visibility", "source_context"):
            if meta_key in operation:
                existing[meta_key] = operation[meta_key]
        existing["confidence"] = max(float(existing.get("confidence", 0.0)), confidence)
        existing["evidence_count"] = int(existing.get("evidence_count", 1)) + 1
        existing["updated_at"] = now
        existing["last_mentioned_at"] = now
        existing["state"] = "active"
        _append_source(existing, operation, now)
        return existing.get("id")

    promote = bool(operation.get("promote", confidence >= 0.78))
    if layer == "L1" and not promote:
        candidate = dict(operation)
        candidate["layer"] = "L1"
        return _upsert_l1_candidate(memory, candidate, now)

    entry = {
        "id": _memory_id(layer.lower(), memory_key),
        "layer": layer,
        "category": category,
        "key": key,
        "memory_key": memory_key,
        "value": value,
        "confidence": confidence,
        "evidence_count": 1,
        "source": "user",
        "source_type": operation.get("source_type", "model"),
        "evidence": _shorten(str(operation.get("evidence") or value), 180),
        "created_at": operation.get("created_at", now),
        "updated_at": now,
        "last_mentioned_at": now,
        "state": "active",
        "associations": [],
        "sources": [],
    }
    for meta_key in ("visibility", "source_context"):
        if operation.get(meta_key):
            entry[meta_key] = operation[meta_key]
    _append_source(entry, operation, now)
    bucket.append(entry)
    if layer == "L1":
        memory["candidates"] = [
            item for item in memory["candidates"] if item.get("memory_key") != memory_key
        ][-20:]
        memory["l1"] = memory["l1"][-80:]
    else:
        memory["l2"] = memory["l2"][-50:]
    return entry["id"]
