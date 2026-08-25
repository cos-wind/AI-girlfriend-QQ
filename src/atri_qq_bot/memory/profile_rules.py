from __future__ import annotations

from .rule_common import *  # noqa: F403

def _find_memory(items: list[dict[str, Any]], memory_key: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("memory_key") == memory_key:
            return item
    return None

def _append_source(entry: dict[str, Any], candidate: dict[str, Any], now: float) -> None:
    sources = list(entry.get("sources") or [])
    source = {
        "at": now,
        "text": _shorten(str(candidate.get("value") or ""), 120),
        "type": candidate.get("source_type", "explicit"),
    }
    if candidate.get("source_context"):
        source["source_context"] = candidate["source_context"]
    sources.append(source)
    entry["sources"] = sources[-6:]

def _memory_id(layer: str, key: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff:-]+", "_", key)
    return f"{layer}:{safe[:80]}"

def _link_related_memories(memory: dict[str, Any], memory_ids: list[str]) -> None:
    ids = [memory_id for memory_id in memory_ids if memory_id]
    if len(ids) < 2:
        return
    all_items = memory["l1"] + memory["l2"]
    for item in all_items:
        if item.get("id") not in ids:
            continue
        associations = set(item.get("associations") or [])
        associations.update(other for other in ids if other != item.get("id"))
        item["associations"] = sorted(associations)[-8:]

def _apply_user_corrections(memory: dict[str, Any], text: str, now: float) -> None:
    for value in _negative_preference_values(text):
        _remove_positive_preference_memory(memory, value)
        _upsert_l1_candidate(
            memory,
            _candidate("preference", f"讨厌:{value}", value, 0.85, "explicit", now),
            now,
        )

    if not any(word in text for word in ("不是", "不对", "我不喜欢", "别再", "不要记", "记错")):
        return
    for entry in memory.get("l1", []):
        value = str(entry.get("value") or "")
        if value and value in text:
            entry["confidence"] = max(0.0, float(entry.get("confidence", 0.6)) - 0.1)
            entry["updated_at"] = now

def _negative_preference_values(text: str) -> list[str]:
    stripped = str(text or "").strip()
    values: list[str] = []
    pattern = re.compile(
        r"(?:我)?(?:真的|很|超|也|平时|经常|常常|一直|其实)*"
        r"(?:不喜欢|不爱|讨厌|不喝|不吃|别再(?:说|提|记|推荐|给我)?|不要(?:说|提|记|推荐)?)"
        r"(?:吃|喝|看|玩|做)?\s*([^，。！？!?；;]{1,18})"
    )
    for match in pattern.finditer(stripped):
        value = _clean_value(match.group(1))
        value = re.sub(r"^成", "", value).strip()
        value = re.sub(
            r"^(?:我)?(?:真的|很|超|也|平时|经常|常常|一直|其实)*(?:爱|喜欢)(?:吃|喝|看|玩|做)?",
            "",
            value,
        ).strip()
        value = re.sub(r"^(?:我)?(?:喝|吃|看|玩|做)", "", value).strip()
        value = re.sub(r"(了|啦|呀|呢|吧)$", "", value).strip()
        if _valid_preference_value(value) and value not in values:
            values.append(value)
    return values

def _conflicts_with_values(value: str, blocked_values: list[str]) -> bool:
    return any(
        blocked and (blocked in value or value in blocked)
        for blocked in blocked_values
    )

def _remove_positive_preference_memory(memory: dict[str, Any], value: str) -> None:
    def conflicts(entry: dict[str, Any]) -> bool:
        category = str(entry.get("category") or "")
        key = str(entry.get("key") or "")
        entry_value = str(entry.get("value") or "")
        if category not in {"interest", "preference"}:
            return False
        if "讨厌" in key or "不喜欢" in key:
            return False
        return bool(value and (value in entry_value or entry_value in value or value in key))

    for bucket in ("l1", "candidates"):
        memory[bucket] = [entry for entry in memory.get(bucket, []) if not conflicts(entry)]

def _decay_event_memories(item: dict[str, Any], now: float) -> bool:
    memory = _ensure_structured_memory(item)
    today = datetime.fromtimestamp(now).date()
    last_decay = item.get("last_l2_decay_date")
    if last_decay == today.isoformat():
        return False

    days = 1
    if last_decay:
        try:
            days = max(0, (today - datetime.fromisoformat(str(last_decay)).date()).days)
        except ValueError:
            days = 1
    if days <= 0:
        return False

    changed = False
    for event in memory.get("l2", []):
        activity = max(0.0, float(event.get("activity", 1.0)) - L2_DAILY_DECAY * days)
        if activity != event.get("activity"):
            event["activity"] = round(activity, 3)
            event["state"] = "sleeping" if activity < L2_SLEEP_THRESHOLD else "active"
            changed = True
    item["last_l2_decay_date"] = today.isoformat()
    return changed

def _structured_memory_profile(
    item: dict[str, Any],
    session_l3: list[dict[str, Any]],
) -> dict[str, Any]:
    memory = _ensure_structured_memory(item)
    current_affection = float(item.get("affection_score", DEFAULT_AFFECTION))
    l1 = [
        entry
        for entry in memory.get("l1", [])
        if float(entry.get("confidence", 0.0)) >= 0.6
        and _reliable_l1_entry(entry)
    ]
    l2 = [
        entry
        for entry in memory.get("l2", [])
        if float(entry.get("activity", 0.0)) > L2_SLEEP_THRESHOLD
        and entry.get("state") != "sleeping"
        and (
            entry.get("category") in {"event", "schedule"}
            or (
                entry.get("category") == "important_interaction"
                and entry.get("importance") == "major"
            )
        )
    ]
    l2 = sorted(
        l2,
        key=lambda entry: (
            abs(float(entry.get("affection_snapshot", current_affection)) - current_affection),
            -float(entry.get("updated_at", entry.get("created_at", 0.0)) or 0.0),
        ),
    )
    candidates = [
        entry
        for entry in memory.get("candidates", [])
        if float(entry.get("confidence", 0.0)) >= 0.55
        and _reliable_l1_entry(entry)
    ]
    return {
        "l1": l1[-12:],
        "l2": l2[:12],
        "l3": list(session_l3)[-5:],
        "candidates": candidates[-8:],
    }


def _reliable_l1_entry(entry: dict[str, Any]) -> bool:
    """L1/L1候选只能作为用户特点参与检索，拒绝模型回声和临时长句。"""
    category = str(entry.get("category") or "")
    value = str(entry.get("value") or "").strip()
    if entry.get("state") in {"expired", "deleted", "rejected"}:
        return False
    if category not in {"profile_fact", "interest", "preference", "habit", "communication_style"}:
        return False
    if not value or len(value) > 64:
        return False
    if any(marker in value for marker in ("你", "亚托莉", "http://", "https://", "...", "…", "[", "]")):
        return False
    if category == "communication_style" and not any(
        marker in value
        for marker in ("默认", "不要", "别", "回复偏好", "短句", "少铺垫", "有逻辑")
    ):
        return False
    return True

def _format_recall_context(profile: dict[str, Any], user_text: str) -> str:
    structured = profile.get("structured_memory") or {}
    l1 = list(structured.get("l1") or [])
    l2 = [
        entry
        for entry in list(structured.get("l2") or [])
        if _memory_relevant(entry, user_text)
    ]
    candidates = [
        entry
        for entry in list(structured.get("candidates") or [])
        if _memory_relevant(entry, user_text)
    ]
    l3 = [
        entry
        for entry in list(structured.get("l3") or [])[-3:]
        if not is_memory_pollution_text(str(entry.get("text") or ""))
    ]

    known = [_natural_memory_line(entry) for entry in l1[-6:]]
    recent = [_natural_memory_line(entry) for entry in l2[:4]]
    tentative = [_natural_memory_line(entry, tentative=True) for entry in candidates[-3:]]
    short_term = [str(entry.get("text") or "") for entry in l3 if str(entry.get("text") or "").strip()]

    lines = [
        "这些都是平日相处慢慢记下的你的细碎日常，聊到对应话题时自然而然带出就好，不要说自己在读取记忆，也绝对不能直白说出调取记忆、刻意记录这类话语。",
        "聊天优先接住你当下正在说的内容，只有内容适配时再顺势带出过往小事，话题无关就完全不用插入过往信息。",
        "使用过往信息时带一点亚托莉式嘴硬，例如：哼，我才不是特意记的呢……不过你上次说过这件事。",
        "记忆细节模糊拿不准时，先流露心虚局促，接着认真努力回想，最后无奈坦言记不清，示例：‘唔……我应该是记得的呀，让我仔细想想…啊呀，怎么想不起来啦😭。’",
    ]
    if profile.get("affection_state"):
        lines.append("你现在对用户的自然感觉：" + str(profile["affection_state"]))
    if profile.get("group_activity_state") and user_text and _is_group_conversation(str(profile.get("conversation_id", ""))):
        lines.append("当前群聊气氛：" + str(profile["group_activity_state"]))
    if l1:
        lines.append("你知道的用户信息：" + "；".join(known))
    if l2:
        lines.append("最近相关的事：" + "；".join(recent))
    if candidates:
        lines.append("可能的用户偏好：" + "；".join(tentative))
    if l3:
        lines.append("刚才聊到：" + "；".join(short_term))

    interval = profile.get("personal_question_interval") or "五到八轮"
    lines.append(
        f"主动了解用户要克制：自然聊天中每{interval}最多问一个个人问题；不连环盘问。"
    )
    lines.append("遇到用户爱好里的细分内容不懂时，可以自然请教一句，但先回应当前消息。")
    return "\n".join(lines)

def _natural_memory_line(entry: dict[str, Any], tentative: bool = False) -> str:
    key = str(entry.get("key") or entry.get("category") or "记忆")
    value = str(entry.get("value") or "")
    key = key.split(":", 1)[0]
    if tentative:
        return f"用户可能{_natural_predicate(key, value)}"
    return f"用户{_natural_predicate(key, value)}"

def _natural_predicate(key: str, value: str) -> str:
    if not value:
        return "有一条相关背景"
    if "生日" in key:
        return f"生日是{value}"
    if "称呼" in key:
        return f"希望被叫作{value}"
    if "喜欢的食物" in key:
        return f"喜欢吃或喝{value}"
    if "兴趣" in key or "偏好" in key:
        return f"喜欢{value}"
    if "讨厌" in key:
        return f"不喜欢{value}"
    if "习惯" in key or "habit" in key:
        return f"平时习惯{value}"
    if "身份" in key or "专业" in key:
        return f"提到过自己是{value}"
    if "回复方式" in key or "communication" in key:
        return f"偏好的聊天方式是{value}"
    if "event" in key or "事件" in key:
        return f"最近提到：{value}"
    return f"提到过{value}"

def _memory_relevant(entry: dict[str, Any], user_text: str) -> bool:
    text = str(user_text or "")
    if not text:
        return False
    category = str(entry.get("category") or "")
    if category == "event" and any(word in text for word in ("今天", "明天", "日程", "安排", "提醒", "考试", "开会", "约")):
        return True
    value = str(entry.get("value") or "")
    key = str(entry.get("key") or "")
    words = set(_extract_topics(value) + _extract_topics(key))
    return any(word and word in text for word in words)

def _personal_question_interval(score: float) -> str:
    if score > 70:
        return "三到五轮"
    if score >= 30:
        return "五到八轮"
    return "很少"

def _remember_important_interaction(
    item: dict[str, Any],
    text: str,
    now: float,
    affection_event: dict[str, Any] | None,
) -> str | None:
    # L2 是事件层，不是情绪流水账。普通感谢、吐槽和一次性情绪
    # 只参与好感度计算；只有明确的重大互动才保留为长期事件。
    if not affection_event or affection_event.get("importance") != "major":
        return None
    if _is_noisy_for_long_memory(text):
        return None
    if _is_negative_quality_complaint(text):
        return None

    memory = _ensure_structured_memory(item)
    current_affection = float(item.get("affection_score", DEFAULT_AFFECTION))
    key = _important_interaction_key(text, affection_event)
    event = {
        "layer": "L2",
        "category": "important_interaction",
        "key": key,
        "value": _shorten(text, 120),
        "activity": 1.0,
        "confidence": 0.8 if affection_event.get("importance") == "major" else 0.7,
        "source": "user",
        "created_at": now,
        "updated_at": now,
        "last_mentioned_at": now,
        "state": "active",
        "associations": [],
    }
    _attach_affection_metadata(event, affection_event, current_affection)
    return _upsert_l2(memory, event, now)

def _important_interaction_key(text: str, affection_event: dict[str, Any]) -> str:
    compact = _shorten(text, 36)
    importance = str(affection_event.get("importance") or "interaction")
    sentiment = str(affection_event.get("sentiment") or "neutral")
    return f"{importance}:{sentiment}:{compact}"
