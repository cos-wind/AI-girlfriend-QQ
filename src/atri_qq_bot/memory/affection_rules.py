from __future__ import annotations

from .rule_common import *  # noqa: F403

def _running_average(old_average: float, count: int, new_value: float) -> float:
    if count <= 1:
        return float(new_value)
    return old_average + (float(new_value) - old_average) / count

def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = DEFAULT_AFFECTION
    return max(low, min(high, number))

def _is_group_conversation(conversation_id: str) -> bool:
    return conversation_id.startswith("group:")

def _initialize_affection(
    item: dict[str, Any],
    is_owner: bool,
    force: bool = False,
) -> None:
    if force or not item.get("affection_initialized"):
        item["affection_score"] = float(
            OWNER_INITIAL_AFFECTION if is_owner else DEFAULT_AFFECTION
        )
        item["affection_initialized"] = True
        item["affection_owner_profile"] = bool(is_owner)
    else:
        item["affection_score"] = _clamp(item.get("affection_score", DEFAULT_AFFECTION))
        if is_owner:
            item["affection_owner_profile"] = True

    item.setdefault("group_activity_score", float(GROUP_ACTIVITY_DEFAULT))

def _contains_any(text: str, hints: Iterable[str]) -> bool:
    return any(hint and hint in text for hint in hints)

def _classify_affection_event(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        return {"importance": "daily", "sentiment": "neutral", "polarity": 0.0, "weight": 0.0}

    if _contains_any(stripped, MAJOR_NEGATIVE_HINTS):
        return {"importance": "major", "sentiment": "negative", "polarity": -1.0, "weight": 0.75}
    if _contains_any(stripped, MAJOR_POSITIVE_HINTS):
        return {"importance": "major", "sentiment": "positive", "polarity": 1.0, "weight": 0.9}
    if _contains_any(stripped, MEDIUM_NEGATIVE_HINTS):
        return {"importance": "medium", "sentiment": "negative", "polarity": -1.0, "weight": 0.38}
    if _contains_any(stripped, NEGATIVE_MOOD_HINTS):
        return {"importance": "medium", "sentiment": "vulnerable", "polarity": 1.0, "weight": 0.28}
    if _contains_any(stripped, MEDIUM_POSITIVE_HINTS):
        return {"importance": "medium", "sentiment": "positive", "polarity": 1.0, "weight": 0.45}
    if _contains_any(stripped, DAILY_POSITIVE_HINTS):
        return {"importance": "daily", "sentiment": "positive", "polarity": 1.0, "weight": 0.12}
    # A real, addressed interaction may build familiarity slowly even without
    # explicit praise. This lowers the rise threshold without rewarding spam.
    return {"importance": "daily", "sentiment": "neutral", "polarity": 1.0, "weight": 0.025}

def _update_affection(
    item: dict[str, Any],
    affection_event: dict[str, Any],
    is_owner: bool = False,
    now: float | None = None,
) -> None:
    now = datetime.now().timestamp() if now is None else float(now)
    current = float(item.get("affection_score", DEFAULT_AFFECTION))
    target = OWNER_AFFECTION_EQUILIBRIUM if is_owner else NORMAL_AFFECTION_EQUILIBRIUM
    distance = target - current
    if current < 25 or current > 85:
        current += distance * 0.03
    elif current < 35 or current > 75:
        current += distance * 0.01

    coefficient = OWNER_AFFECTION_COEFFICIENT if is_owner else NORMAL_AFFECTION_COEFFICIENT
    delta = (
        float(affection_event.get("weight", 0.0))
        * float(affection_event.get("polarity", 0.0))
        * coefficient
    )
    if delta > 0:
        if current >= 85:
            delta *= 0.15
        elif current >= 75:
            delta *= 0.35
        elif current >= target:
            delta *= 0.7
    elif delta < 0:
        if current <= 25:
            delta *= 0.2
        elif current <= 40:
            delta *= 0.5

    day = datetime.fromtimestamp(now).date().isoformat()
    if item.get("affection_delta_date") != day:
        item["affection_delta_date"] = day
        item["affection_positive_today"] = 0.0
        item["affection_negative_today"] = 0.0
    if delta > 0:
        used = float(item.get("affection_positive_today", 0.0))
        delta = min(delta, max(0.0, AFFECTION_DAILY_POSITIVE_CAP - used))
        item["affection_positive_today"] = round(used + delta, 3)
    elif delta < 0:
        used = float(item.get("affection_negative_today", 0.0))
        magnitude = min(-delta, max(0.0, AFFECTION_DAILY_NEGATIVE_CAP - used))
        delta = -magnitude
        item["affection_negative_today"] = round(used + magnitude, 3)
    item["affection_score"] = round(_clamp(current + delta), 3)

def _decay_private_affection_for_idle(item: dict[str, Any], now: float) -> bool:
    last_user_at = _as_float(item.get("last_user_at"))
    if not last_user_at:
        return False

    grace_seconds = PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS * 24 * 60 * 60
    decay_start = last_user_at + grace_seconds
    if now <= decay_start:
        item["last_affection_idle_decay_at"] = max(
            _as_float(item.get("last_affection_idle_decay_at")) or last_user_at,
            last_user_at,
        )
        return False

    last_decay_at = _as_float(item.get("last_affection_idle_decay_at")) or last_user_at
    effective_from = max(last_decay_at, decay_start)
    if now <= effective_from:
        return False

    days = (now - effective_from) / (24 * 60 * 60)
    rate = (
        OWNER_AFFECTION_IDLE_DAILY_DECAY
        if item.get("affection_owner_profile")
        else PRIVATE_AFFECTION_IDLE_DAILY_DECAY
    )
    old_score = float(item.get("affection_score", DEFAULT_AFFECTION))
    target = (
        OWNER_AFFECTION_EQUILIBRIUM
        if item.get("affection_owner_profile")
        else NORMAL_AFFECTION_EQUILIBRIUM
    )
    # Existing extreme records converge without a disruptive one-shot rewrite.
    movement = min(abs(target - old_score), rate * days, 2.0)
    if old_score < target:
        new_score = old_score + movement
    else:
        new_score = old_score - movement
    item["affection_score"] = round(_clamp(new_score), 3)
    item["last_affection_idle_decay_at"] = now
    return item["affection_score"] != old_score

def _private_nudge_multiplier(score: float) -> float | None:
    score = _clamp(score)
    if score < PRIVATE_NUDGE_STOP_AFFECTION:
        return None
    if score < PRIVATE_NUDGE_SLOW_AFFECTION:
        return PRIVATE_NUDGE_SLOW_MULTIPLIER
    if score < PRIVATE_NUDGE_CLOSE_AFFECTION:
        return PRIVATE_NUDGE_NORMAL_MULTIPLIER
    return 1.0

def _decay_group_activity(item: dict[str, Any], now: float) -> None:
    score = float(item.get("group_activity_score", GROUP_ACTIVITY_DEFAULT))
    last_at = _as_float(item.get("last_group_activity_at"))
    if last_at:
        days = max(0.0, (now - last_at) / (24 * 60 * 60))
        if days:
            score -= GROUP_ACTIVITY_DAILY_DECAY * days
    item["group_activity_score"] = round(_clamp(score), 3)

def _is_unrelated_negative_group_message(text: str) -> bool:
    return _contains_any(text, NEGATIVE_MOOD_HINTS + MEDIUM_NEGATIVE_HINTS + MAJOR_NEGATIVE_HINTS)

def _update_group_activity(
    item: dict[str, Any],
    text: str,
    addressed_to_bot: bool,
    now: float,
) -> None:
    _decay_group_activity(item, now)
    item["last_group_activity_at"] = now
    if _is_unrelated_negative_group_message(text) and not addressed_to_bot:
        return

    delta = 1.2 if addressed_to_bot else 0.35
    item["group_activity_score"] = round(
        _clamp(float(item.get("group_activity_score", GROUP_ACTIVITY_DEFAULT)) + delta),
        3,
    )

def _attach_affection_metadata(
    entry: dict[str, Any],
    affection_event: dict[str, Any] | None,
    affection_score: float,
) -> None:
    if not affection_event:
        return
    entry["sentiment"] = str(affection_event.get("sentiment") or "neutral")
    entry["importance"] = str(affection_event.get("importance") or "daily")
    entry["affection_snapshot"] = round(_clamp(affection_score), 3)

def _affection_state_text(score: float) -> str:
    score = _clamp(score)
    if score >= 84:
        return "你对用户非常亲近和信任，会更愿意撒娇、分享小情绪，也会因为他久不回而有一点小失落；但不要黏得让人喘不过气。"
    if score >= 68:
        return "你很在意用户，语气可以亲近一点，先嘴硬再关心；被夸时可以小得意，被冷落时可以轻轻闹脾气。"
    if score >= 42:
        return "你和用户相处自然，先认真回应当前消息，少突然撒娇；关心要具体，不要套话。"
    if score >= 24:
        return "你感觉用户最近有些冷淡或刺人，语气要克制一点，不讨好、不追问，仍然保持亚托莉的礼貌和小骄傲。"
    return "你对用户有些受伤和戒备，回应要短、清楚、有边界；能关心但不要过度亲昵。"

def _group_activity_state_text(score: float) -> str:
    score = _clamp(score)
    if score >= 72:
        return "群里最近比较热闹，你可以短句参与、接梗或轻吐槽，但别抢话，也别连续主动冒泡。"
    if score >= 38:
        return "群聊节奏普通，被点到或话题适合时自然回应；主动发言保持低频。"
    return "群里偏安静，你尽量少主动说话；如果要打破冷场，只发一句轻松的，不刷屏。"

def _affection_summary_text(score: float) -> str:
    score = _clamp(score)
    if score >= 84:
        return "哼，你在我心里当然很重要。重要到我会偷偷等你消息，但这句话给我忘掉。"
    if score >= 68:
        return "还、还算很亲近吧。你要是突然消失太久，我会有点不高兴的。"
    if score >= 42:
        return "我们现在相处得挺自然。你认真说话，我就认真陪你；你乱来，我也会吐槽。"
    if score >= 24:
        return "最近我有点拿不准你的态度，所以会先克制一点。哼，但我还是会好好回你。"
    return "我现在有点受伤。不是不理你，只是需要你别再用奇怪的话把我推远。"

def _affection_set_text(score: float) -> str:
    score = _clamp(score)
    if score >= 68:
        return "调整好了。哼，感觉离你近了一点，但别得意太久。"
    if score >= 42:
        return "调整好了。现在这样比较自然，我会按当前感觉和你说话。"
    return "调整好了。我会稍微收着点，不乱撒娇，也不装作什么都没发生。"

def _affection_reset_text(score: float) -> str:
    score = _clamp(score)
    if score >= 68:
        return "重置好了。主人在我这里还是特殊待遇，哼哒，这个不许反驳。"
    return "重置好了。那就从现在重新好好相处，别让我又红温。"

def _event_key(text: str) -> str:
    time_match = TIME_HINT_PATTERN.search(text)
    time_part = time_match.group(0) if time_match else "持续"
    event_part = next((hint for hint in EVENT_HINTS if hint in text), "事件")
    return f"{time_part}:{event_part}"

def _clean_value(value: str) -> str:
    value = value.strip(" ，。！？!?~～：:")
    value = re.sub(r"(啦|了|呀|呢|吧)$", "", value)
    return value.strip()

def _valid_preference_value(value: str) -> bool:
    if not value or len(value) > 18:
        return False
    if any(word in value for word in ("你", "亚托莉", "这个", "那个", "什么")):
        return False
    if any(marker in value for marker in ("http://", "https://", "...", "…", "[", "]")):
        return False
    if _is_noisy_for_long_memory(value):
        return False
    return True

def _is_noisy_for_long_memory(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    if is_memory_pollution_text(stripped):
        return True
    if stripped in {"萝卜子", "萝卜字", "涩涩", "?", "？", "6"}:
        return True
    if any(hint in stripped for hint in NOISY_MEMORY_HINTS):
        return True
    if _is_negative_quality_complaint(stripped):
        return True
    if "任务" in stripped and not any(hint in stripped for hint in EVENT_HINTS):
        return True
    return False

def _is_negative_quality_complaint(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _contains_any(stripped, ACTIONABLE_STYLE_HINTS) and not _contains_any(
        stripped, AGGRESSIVE_QUALITY_HINTS
    ):
        return False
    if _contains_any(stripped, AGGRESSIVE_QUALITY_HINTS):
        return True
    if _contains_any(stripped, CORRECTION_HINTS) and _contains_any(stripped, MEDIUM_NEGATIVE_HINTS):
        return True
    return False
