from __future__ import annotations

from .rule_common import *  # noqa: F403

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
) -> None:
    # 结构化记忆采用“先纠正冲突 -> 过滤噪声 -> 抽取 L2 事件/L1 特征 -> 建立关联”
    # 的顺序。L3 是会话滚动窗口，不在这里被误写成永久用户画像。
    memory = _ensure_structured_memory(item)
    _apply_user_corrections(memory, text, now)
    style_candidate = _actionable_style_candidate(text, now, visibility, source_context)
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
    for event in _extract_l2_events(text, now, visibility, source_context):
        _attach_affection_metadata(event, affection_event, current_affection)
        memory_id = _upsert_l2(memory, event, now)
        if memory_id:
            new_ids.append(memory_id)

    for candidate in _extract_l1_candidates(text, now, visibility, source_context):
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
    stripped = str(text or "").strip()
    if not stripped:
        return None
    style_terms = (
        "别发日语", "不要发日语", "不准发日语", "别用日语", "不要用日语",
        "别发外语", "不要发外语", "只说中文", "讲中文", "正常中文",
        "别学我说话", "不要学我说话", "别复读", "不要复读",
        "别主动发消息", "不要主动发消息", "没事别发消息", "少主动",
        "别刷屏", "不要刷屏", "不要套话", "有逻辑",
    )
    short_style_request = any(word in stripped for word in ("短句", "直接", "别绕")) and any(
        word in stripped for word in ("回复", "回答", "说话", "以后", "之后", "默认", "请")
    )
    if not any(word in stripped for word in style_terms) and not short_style_request:
        return None
    return _candidate(
        "communication_style",
        "回复方式",
        _shorten(_style_rule_value(stripped), 80),
        0.8,
        "explicit",
        now,
        visibility=visibility,
        source_context=source_context,
    )

def _style_rule_value(text: str) -> str:
    if any(word in text for word in ("别发日语", "不要发日语", "不准发日语", "别用日语", "不要用日语")):
        return "默认用自然简体中文，不主动夹日语口癖"
    if any(word in text for word in ("别发外语", "不要发外语", "只说中文", "讲中文", "正常中文")):
        return "默认只用自然简体中文，避免外语和怪字符"
    if any(word in text for word in ("别学我说话", "不要学我说话", "别复读", "不要复读")):
        return "不要复读或模仿用户原句，先回应意思"
    if any(word in text for word in ("别主动发消息", "不要主动发消息", "没事别发消息", "少主动")):
        return "主动关心要更克制，避免没事频繁发消息"
    if any(word in text for word in ("别刷屏", "不要刷屏")):
        return "回复保持短句低频，不刷屏"
    if any(word in text for word in ("短句", "直接", "别绕", "不要套话", "有逻辑")):
        return "回复偏好短句、直接、有逻辑，少铺垫和套话"
    return "按用户明确要求调整回复方式"

def _extract_l1_candidates(
    text: str,
    now: float,
    visibility: str = "private",
    source_context: str | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    stripped = text.strip()
    negative_values = _negative_preference_values(stripped)

    birthday = re.search(
        r"(?:我的)?生日(?:是|在|：|:)?\s*((?:[0-9]{4}年)?[0-9]{1,2}月[0-9]{1,2}[日号]?|[0-9]{1,2}[./-][0-9]{1,2})",
        stripped,
    )
    if birthday:
        candidates.append(
            _candidate(
                "profile_fact",
                "生日",
                birthday.group(1),
                0.8,
                "explicit",
                now,
                visibility=visibility,
                source_context=source_context,
            )
        )

    nickname = re.search(r"(?:我叫|叫我|以后叫我|你可以叫我)\s*([^，。！？!?]{1,12})", stripped)
    if nickname:
        value = _clean_value(nickname.group(1))
        if value and "亚托莉" not in value:
            candidates.append(
                _candidate(
                    "profile_fact",
                    "称呼",
                    value,
                    0.8,
                    "explicit",
                    now,
                    visibility=visibility,
                    source_context=source_context,
                )
            )

    for pattern, key_prefix in (
        (r"我(?:真的|很|超|也|平时|经常|常常|一直|其实)*(?:喜欢|爱)(?:吃|喝)\s*([^，。！？!?]{1,18})", "喜欢的食物"),
        (r"我(?:真的|很|超|也|平时|经常|常常|一直|其实)*(?:喜欢|爱)(?:看|玩|做)\s*([^，。！？!?]{1,18})", "兴趣爱好"),
        (r"我(?:真的|很|超|也|平时|经常|常常|一直|其实)*(?:喜欢|爱)\s*([^，。！？!?]{1,18})", "偏好"),
        (r"(?:我)?(?:真的|很|超|也|平时|经常|常常|一直|其实)*(?:不喜欢|不爱|讨厌|不喝|不吃)(?:吃|喝|看|玩|做)?\s*([^，。！？!?]{1,18})", "讨厌"),
    ):
        for match in re.finditer(pattern, stripped):
            value = _clean_value(match.group(1))
            if _valid_preference_value(value) and not _conflicts_with_values(
                value, negative_values
            ):
                candidates.append(
                    _candidate(
                        "preference",
                        f"{key_prefix}:{value}",
                        value,
                        0.8,
                        "explicit",
                        now,
                        visibility=visibility,
                        source_context=source_context,
                    )
                )

    identity = re.search(r"(?:我是|我的专业是|我的职业是)\s*([^，。！？!?]{2,18})", stripped)
    if identity:
        value = _clean_value(identity.group(1))
        if value and not any(noise in value for noise in ("机器人", "亚托莉")):
            candidates.append(
                _candidate(
                    "profile_fact",
                    "身份/专业",
                    value,
                    0.8,
                    "explicit",
                    now,
                    visibility=visibility,
                    source_context=source_context,
                )
            )

    habit = re.search(r"我(?:平时|经常|常常|一般|每天|习惯|通常)\s*([^，。！？!?]{2,24})", stripped)
    if habit:
        value = _clean_value(habit.group(1))
        if _valid_preference_value(value):
            candidates.append(
                _candidate(
                    "habit",
                    f"习惯:{value}",
                    value,
                    0.75,
                    "explicit",
                    now,
                    visibility=visibility,
                    source_context=source_context,
                )
            )

    if any(word in stripped for word in ("短句", "直接", "别绕", "不要套话", "有逻辑")) and not _contains_any(stripped, ACTIONABLE_STYLE_HINTS):
        candidates.append(
            _candidate(
                "communication_style",
                "回复方式",
                _shorten(stripped, 80),
                0.8,
                "explicit",
                now,
                visibility=visibility,
                source_context=source_context,
            )
        )

    for word in IMPLICIT_INTEREST_HINTS:
        if word in stripped and not any(word in str(c.get("value")) for c in candidates):
            candidates.append(
                _candidate(
                    "interest",
                    f"兴趣:{word}",
                    word,
                    0.6,
                    "implicit",
                    now,
                    visibility=visibility,
                    source_context=source_context,
                )
            )

    return candidates

def _extract_l2_events(
    text: str,
    now: float,
    visibility: str = "private",
    source_context: str | None = None,
) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not any(hint in stripped for hint in EVENT_HINTS):
        return []
    if not TIME_HINT_PATTERN.search(stripped) and "持续" not in stripped and "以后" not in stripped:
        return []
    key = _event_key(stripped)
    events = [
        {
            "layer": "L2",
            "category": "event",
            "key": key,
            "value": _shorten(stripped, 120),
            "activity": 1.0,
            "confidence": 0.8,
            "source": "user",
            "created_at": now,
            "updated_at": now,
            "last_mentioned_at": now,
            "state": "active",
            "associations": [],
            "visibility": visibility,
        }
    ]
    if source_context:
        events[0]["source_context"] = source_context
    return events

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
    existing = _find_memory(memory["l1"], key)
    if existing:
        if existing.get("locked"):
            existing["last_mentioned_at"] = now
            _append_source(existing, candidate, now)
            return existing["id"]
        existing["confidence"] = min(1.0, max(float(existing.get("confidence", 0.0)), float(candidate["confidence"])) + 0.05)
        existing["evidence_count"] = int(existing.get("evidence_count", 1)) + 1
        existing["updated_at"] = now
        existing["last_mentioned_at"] = now
        _append_source(existing, candidate, now)
        return existing["id"]

    pending = _find_memory(memory["candidates"], key)
    if pending:
        if pending.get("locked"):
            pending["last_mentioned_at"] = now
            _append_source(pending, candidate, now)
            return pending["id"]
        pending["confidence"] = min(1.0, max(float(pending.get("confidence", 0.0)), float(candidate["confidence"])))
        pending["evidence_count"] = int(pending.get("evidence_count", 1)) + 1
        pending["updated_at"] = now
        pending["last_mentioned_at"] = now
        _append_source(pending, candidate, now)
    else:
        pending = dict(candidate)
        pending["id"] = _memory_id("candidate", key)
        pending["memory_key"] = key
        memory["candidates"].append(pending)

    if int(pending.get("evidence_count", 1)) >= L1_CONFIRMATIONS_REQUIRED:
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
        if existing.get("locked"):
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
        return existing["id"]
    event = dict(event)
    event["id"] = _memory_id("l2", key)
    event["memory_key"] = key
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
        existing["confidence"] = max(float(existing.get("confidence", 0.0)), confidence)
        existing["evidence_count"] = int(existing.get("evidence_count", 1)) + 1
        existing["updated_at"] = now
        existing["last_mentioned_at"] = now
        existing["state"] = "active"
        _append_source(existing, operation, now)
        return existing.get("id")

    promote = bool(operation.get("promote")) or confidence >= 0.78
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
