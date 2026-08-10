from __future__ import annotations

import json
import random
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..proactive.time_utils import parse_hhmm, safe_zoneinfo
from ..prompting import render_prompt
from ..runtime.paths import VOICE_BEHAVIOR_PATH


DEFAULT_VOICE_BEHAVIOR: dict[str, Any] = {
    "version": 1,
    "enabled": True,
    "explicit_requests_enabled": True,
    "explicit_delivery_guard_enabled": True,
    "reply_to_voice_enabled": True,
    "reply_voice_probability": 35,
    "emotional_reply_voice_probability": 70,
    "private_autonomous_enabled": True,
    "private_min_affection": 70,
    "private_min_messages": 5,
    "group_autonomous_enabled": False,
    "group_min_activity": 65,
    "group_min_messages": 20,
    "proactive_voice_enabled": False,
    "original_clip_enabled": True,
    "quality_gate_enabled": True,
    "quality_max_error_rate": 0.12,
    "quality_retries": 1,
    "singing_enabled": True,
    "quiet_start": "00:30",
    "quiet_end": "07:00",
    "timezone": "Asia/Shanghai",
    "calls_enabled": False,
    "call_min_affection": 85,
    "call_min_messages": 20,
    "call_base_url": "http://127.0.0.1:8787",
    "call_expiry_minutes": 10,
    "call_max_minutes": 30,
}


@dataclass(frozen=True)
class VoicePolicyDecision:
    allowed: bool
    reason: str


def default_voice_behavior() -> dict[str, Any]:
    return deepcopy(DEFAULT_VOICE_BEHAVIOR)


def load_voice_behavior(path: Path | None = None) -> dict[str, Any]:
    target = path or VOICE_BEHAVIOR_PATH
    if not target.exists():
        return default_voice_behavior()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_voice_behavior()
    try:
        return normalize_voice_behavior(payload)
    except ValueError:
        return default_voice_behavior()


def save_voice_behavior(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = path or VOICE_BEHAVIOR_PATH
    policy = normalize_voice_behavior(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.with_suffix(".bak").write_bytes(target.read_bytes())
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return policy


def normalize_voice_behavior(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("语音行为配置必须是 JSON 对象")
    policy = default_voice_behavior()
    for key in (
        "enabled",
        "explicit_requests_enabled",
        "explicit_delivery_guard_enabled",
        "reply_to_voice_enabled",
        "private_autonomous_enabled",
        "group_autonomous_enabled",
        "proactive_voice_enabled",
        "original_clip_enabled",
        "quality_gate_enabled",
        "singing_enabled",
        "calls_enabled",
    ):
        if key in payload:
            policy[key] = _as_bool(payload[key])
    for key in (
        "private_min_affection",
        "group_min_activity",
        "call_min_affection",
        "reply_voice_probability",
        "emotional_reply_voice_probability",
    ):
        if key in payload:
            policy[key] = _bounded_float(payload[key], 0, 100, key)
    if "quality_max_error_rate" in payload:
        policy["quality_max_error_rate"] = _bounded_float(
            payload["quality_max_error_rate"],
            0,
            1,
            "quality_max_error_rate",
        )
    for key, minimum, maximum in (
        ("private_min_messages", 0, 100000),
        ("group_min_messages", 0, 100000),
        ("call_min_messages", 0, 100000),
        ("call_expiry_minutes", 1, 1440),
        ("call_max_minutes", 1, 240),
        ("quality_retries", 0, 3),
    ):
        if key in payload:
            policy[key] = _bounded_int(payload[key], minimum, maximum, key)
    for key in ("quiet_start", "quiet_end"):
        if key in payload:
            value = str(payload[key]).strip()
            parse_hhmm(value)
            policy[key] = value
    if "timezone" in payload:
        timezone_name = str(payload["timezone"]).strip() or "Asia/Shanghai"
        safe_zoneinfo(timezone_name)
        policy["timezone"] = timezone_name
    if "call_base_url" in payload:
        base_url = str(payload["call_base_url"]).strip().rstrip("/")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("通话地址必须以 http:// 或 https:// 开头")
        policy["call_base_url"] = base_url
    return policy


def voice_policy_prompt(
    conversation_id: str,
    profile: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> str:
    policy = policy or load_voice_behavior()
    is_group = _is_group(conversation_id)
    if is_group:
        eligible = (
            policy["enabled"]
            and policy["group_autonomous_enabled"]
            and float(profile.get("group_activity_score", 0)) >= policy["group_min_activity"]
            and int(profile.get("message_count", 0)) >= policy["group_min_messages"]
        )
        relation = (
            f"群活跃度 {float(profile.get('group_activity_score', 0)):.1f}，"
            f"消息数 {int(profile.get('message_count', 0))}"
        )
    else:
        eligible = (
            policy["enabled"]
            and policy["private_autonomous_enabled"]
            and float(profile.get("affection_score", 0)) >= policy["private_min_affection"]
            and int(profile.get("message_count", 0)) >= policy["private_min_messages"]
        )
        relation = (
            f"好感度 {float(profile.get('affection_score', 0)):.1f}，"
            f"消息数 {int(profile.get('message_count', 0))}"
        )
    explicit = "允许" if policy["explicit_requests_enabled"] else "禁止"
    autonomous = "允许" if eligible else "不允许"
    return render_prompt(
        "voice_policy",
        explicit=explicit,
        autonomous=autonomous,
        relation=relation,
    )


def evaluate_voice_request(
    conversation_id: str,
    profile: dict[str, Any],
    reason: str,
    policy: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> VoicePolicyDecision:
    policy = policy or load_voice_behavior()
    if not policy["enabled"]:
        return VoicePolicyDecision(False, "语音行为总开关未启用")
    normalized_reason = str(reason or "autonomous").strip().lower()
    if normalized_reason == "explicit_request":
        return VoicePolicyDecision(
            bool(policy["explicit_requests_enabled"]),
            "用户明确要求语音" if policy["explicit_requests_enabled"] else "已禁止明确请求触发语音",
        )
    if normalized_reason == "voice_reply" and policy["reply_to_voice_enabled"]:
        return VoicePolicyDecision(True, "允许用语音回应用户语音")
    if normalized_reason == "proactive" and not policy["proactive_voice_enabled"]:
        return VoicePolicyDecision(False, "主动消息语音未启用")
    if _in_quiet_hours(policy, now):
        return VoicePolicyDecision(False, "当前处于语音免打扰时段")

    if _is_group(conversation_id):
        if not policy["group_autonomous_enabled"]:
            return VoicePolicyDecision(False, "群聊自主语音未启用")
        if float(profile.get("group_activity_score", 0)) < policy["group_min_activity"]:
            return VoicePolicyDecision(False, "群活跃度未达到自主语音阈值")
        if int(profile.get("message_count", 0)) < policy["group_min_messages"]:
            return VoicePolicyDecision(False, "群消息量未达到自主语音阈值")
        return VoicePolicyDecision(True, "群聊自主语音条件已满足")

    if not policy["private_autonomous_enabled"]:
        return VoicePolicyDecision(False, "私聊自主语音未启用")
    if float(profile.get("affection_score", 0)) < policy["private_min_affection"]:
        return VoicePolicyDecision(False, "好感度未达到自主语音阈值")
    if int(profile.get("message_count", 0)) < policy["private_min_messages"]:
        return VoicePolicyDecision(False, "私聊消息量未达到自主语音阈值")
    return VoicePolicyDecision(True, "私聊自主语音条件已满足")


def evaluate_reply_voice_choice(
    conversation_id: str,
    profile: dict[str, Any],
    policy: dict[str, Any] | None = None,
    *,
    explicit_request: bool = False,
    replying_to_voice: bool = False,
    emotional_context: bool = False,
    random_value: float | None = None,
    now: datetime | None = None,
) -> VoicePolicyDecision:
    policy = policy or load_voice_behavior()
    if not policy["enabled"]:
        return VoicePolicyDecision(False, "语音行为总开关未启用")
    if explicit_request:
        return evaluate_voice_request(
            conversation_id,
            profile,
            "explicit_request",
            policy,
            now,
        )
    if replying_to_voice and policy["reply_to_voice_enabled"]:
        return VoicePolicyDecision(True, "用户发来语音，本轮允许模型选择语音回应")

    eligibility = evaluate_voice_request(
        conversation_id,
        profile,
        "autonomous",
        policy,
        now,
    )
    if not eligibility.allowed:
        return eligibility

    probability = float(policy.get("reply_voice_probability", 35))
    if emotional_context:
        probability = max(
            probability,
            float(policy.get("emotional_reply_voice_probability", 70)),
        )
    if probability <= 0:
        return VoicePolicyDecision(False, "本轮语音回复概率为 0%")
    if probability >= 100:
        return VoicePolicyDecision(True, "本轮已开放语音回复选择")
    roll = random.random() if random_value is None else float(random_value)
    if roll < probability / 100:
        return VoicePolicyDecision(True, "本轮命中语音回复概率，交由模型结合语境选择")
    return VoicePolicyDecision(False, "本轮未命中语音回复概率")


def evaluate_call_request(
    conversation_id: str,
    profile: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> VoicePolicyDecision:
    policy = policy or load_voice_behavior()
    if _is_group(conversation_id):
        return VoicePolicyDecision(False, "通话邀请只支持私聊")
    if not policy["calls_enabled"]:
        return VoicePolicyDecision(False, "实时通话未启用")
    if not policy["call_base_url"]:
        return VoicePolicyDecision(False, "尚未配置可访问的通话地址")
    if float(profile.get("affection_score", 0)) < policy["call_min_affection"]:
        return VoicePolicyDecision(False, "好感度未达到通话阈值")
    if int(profile.get("message_count", 0)) < policy["call_min_messages"]:
        return VoicePolicyDecision(False, "互动消息量未达到通话阈值")
    return VoicePolicyDecision(True, "通话条件已满足")


def _is_group(conversation_id: str) -> bool:
    return conversation_id.startswith("group:") and ":user:" not in conversation_id


def _in_quiet_hours(policy: dict[str, Any], now: datetime | None) -> bool:
    timezone = safe_zoneinfo(str(policy.get("timezone") or "Asia/Shanghai"))
    local_now = now.astimezone(timezone) if now else datetime.now(timezone)
    start_hour, start_minute = parse_hhmm(str(policy["quiet_start"]))
    end_hour, end_minute = parse_hhmm(str(policy["quiet_end"]))
    current = local_now.hour * 60 + local_now.minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    return min(maximum, max(minimum, parsed))


def _bounded_float(value: Any, minimum: float, maximum: float, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    return min(maximum, max(minimum, parsed))
