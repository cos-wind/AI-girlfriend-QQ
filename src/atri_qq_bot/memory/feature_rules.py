from __future__ import annotations

from .rule_common import *  # noqa: F403

def _emoji_count(text: str) -> int:
    unicode_emoji = len(re.findall(r"[\U0001f300-\U0001faff]", text))
    qq_faces = text.count("[表情]") + text.count("[图片]")
    kaomoji = len(re.findall(r"[\(\（][^()\n]{1,14}[\)\）]", text))
    return unicode_emoji + qq_faces + kaomoji

def _style_flags(text: str) -> dict[str, bool]:
    return {
        "correction_count": any(word in text for word in CORRECTION_HINTS),
        "direct_request_count": any(word in text for word in DIRECT_HINTS),
        "comfort_request_count": any(word in text for word in COMFORT_HINTS),
        "abstract_signal_count": any(word in text for word in ABSTRACT_HINTS),
    }

def _message_features(text: str) -> dict[str, int]:
    return {
        "emoji": 1 if _emoji_count(text) > 0 else 0,
        "question": 1 if ("?" in text or "？" in text) else 0,
        "image_or_sticker": 1 if any(word in text for word in ("[表情包/图片", "[动画表情", "[QQ表情")) else 0,
        "correction": 1 if any(word in text for word in CORRECTION_HINTS) else 0,
        "direct_request": 1 if any(word in text for word in DIRECT_HINTS) else 0,
        "comfort": 1 if any(word in text for word in COMFORT_HINTS) else 0,
        "abstract": 1 if any(word in text for word in ABSTRACT_HINTS) else 0,
    }

def _merge_feature_counts(item: dict[str, Any], features: dict[str, int]) -> None:
    counts = dict(item.get("feature_counts") or {})
    for key, value in features.items():
        if value:
            counts[key] = int(counts.get(key, 0)) + int(value)
    item["feature_counts"] = counts

def _append_iteration_rule(item: dict[str, Any], bucket_name: str, rule: dict[str, Any]) -> None:
    rules = [old for old in list(item.get(bucket_name) or []) if isinstance(old, dict)]
    rule_text = str(rule.get("rule") or "")
    rules = [old for old in rules if str(old.get("rule") or "") != rule_text]
    rules.append(rule)
    item[bucket_name] = rules[-12:]

def _iteration_rule_text(user_text: str, action: str, reason: str) -> str:
    text = user_text.strip()
    lowered = text.lower()
    if action == "accept":
        if any(word in text for word in ("思考过程", "分析过程", "意图识别")) or "thinking" in lowered or "<think>" in lowered:
            return "禁止把思考过程、分析过程、意图识别、Thinking 或 <think> 内容发给用户。"
        if any(word in text for word in ("接住", "什么接不接住")):
            return "不要把“接住”“我接住了”当口头禅，改用具体回答和自然口语。"
        if any(word in text for word in ("固定文案", "固定预设", "模板", "套话")):
            return "禁用固定文案循环复用，按当前上下文动态生成回复。"
        if any(word in text for word in ("人机", "莫名其妙", "奇怪的话", "说怪话")):
            return "发现回复像机器或莫名其妙时，下一轮必须回到用户当前问题本身。"
        if any(word in text for word in ("深海", "灯塔", "水下", "海底", "海风", "比喻", "原作意象")):
            return "非剧情话题禁用深海、灯塔、水下、海风等原作意象比喻。"
        if any(word in text for word in ("群聊", "私聊", "场景", "差异化")):
            return "群聊偏轻吐槽和玩梗，私聊偏陪伴和具体关心。"
        if any(word in text for word in ("核心", "重点", "答非所问", "错位", "没懂")):
            return "回复前先抓用户当前消息核心，第一句直接作答。"
        if any(word in text for word in ("空泛", "套话", "模板")):
            return "拒绝空泛套话，每次至少给具体判断、建议、吐槽或安慰动作。"
        if any(word in text for word in ("重复", "循环", "复读")):
            return "避免重复旧句式和循环安慰，必要时换角度重写。"
        if any(word in text for word in ("烂梗", "生硬", "网络梗")):
            return "可以轻微日常玩笑，但禁止生硬堆砌网络烂梗。"
        return f"采纳用户纠错：{_shorten(text, 80)}"

    if action == "pushback":
        return f"保留判断，不盲目采纳：{_shorten(text or reason, 80)}"

    return f"驳回越界或破坏人设的修正：{_shorten(text or reason, 80)}"

def _append_history(
    item: dict[str, Any],
    role: str,
    text: str,
    now: float,
    actor_id: int | str | None = None,
    nickname: str | None = None,
) -> None:
    if is_memory_pollution_text(text):
        return
    history = list(item.get("history") or [])
    entry: dict[str, Any] = {
        "at": now,
        "role": role,
        "text": _shorten(text, 300),
    }
    if actor_id is not None:
        entry["actor_id"] = str(actor_id)
    if nickname:
        entry["nickname"] = str(nickname)
    history.append(entry)
    item["history"] = history[-HISTORY_LIMIT:]

def _shorten(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."

def _extract_topics(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{3,}", text)
    return [word for word in words if word not in TOPIC_STOPWORDS][:8]

def _merge_topics(old_topics: Any, new_topics: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for word in list(new_topics) + list(old_topics or []):
        if _is_safe_topic(word) and word not in merged:
            merged.append(word)
    return merged[:12]

def _safe_topics(topics: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for topic in topics:
        word = str(topic).strip()
        if _is_safe_topic(word) and word not in result:
            result.append(word)
    return result[:12]

def _is_safe_topic(word: str) -> bool:
    if not word or word in TOPIC_STOPWORDS or word in MEMORY_TOPIC_BLOCKLIST:
        return False
    if is_memory_pollution_text(word):
        return False
    if any(pattern in word for pattern in ("任务", "系统", "进度条", "调试", "处理")):
        return False
    return True
