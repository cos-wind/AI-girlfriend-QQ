"""Upcoming text is a reusable draft, invalidated by context/settings changes."""
import hashlib
import json


def draft_key(engine, conversation_id, event_type, policy):
    item = engine.memory._conversation(conversation_id)
    payload = {key: item.get(key) for key in (
        "history", "summary", "structured_memory", "memory_manual_edit_at",
        "last_user_at", "last_bot_at", "affection_score", "trust", "proactive_override",
        "next_proactive_at", "recent_proactive_messages")}
    payload.update(event=event_type, policy=policy, config=repr(engine.config))
    from atri_bot.persona.core import load_prompt, PERSONA_PROMPT, LANGUAGE_GUARD_PROMPT
    payload["prompts"] = [load_prompt(name) for name in ("proactive", "proactive_topic_rule")]
    payload["persona"] = [PERSONA_PROMPT, LANGUAGE_GUARD_PROMPT]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def current_draft(engine, conversation_id, event_type, policy, now):
    item = engine.memory._conversation(conversation_id)
    draft = item.get("proactive_draft") or {}
    if (draft.get("key") == draft_key(engine, conversation_id, event_type, policy)
            and 0 <= now - float(draft.get("created_at", 0)) < 86400
            and draft.get("text") and item.get("next_proactive_at")
            and now <= float(item["next_proactive_at"]) + 300):
        return draft
    return None
