from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .language_guard import has_illegal_language_or_garbage
from .proactive import parse_hhmm, safe_zoneinfo


TOPIC_STOPWORDS = {
    "什么",
    "怎么",
    "为什么",
    "可以",
    "就是",
    "这个",
    "那个",
    "一下",
    "现在",
    "没有",
    "不是",
    "亚托莉",
}

CORRECTION_HINTS = (
    "答非所问",
    "没懂",
    "重复",
    "循环",
    "不像真人",
    "错位",
    "空泛",
    "套话",
    "场景不对",
    "场景错",
    "核心没抓住",
    "没抓重点",
    "说怪话",
    "奇怪的话",
    "莫名其妙",
    "人机",
    "固定文案",
    "思考过程",
    "分析过程",
    "原作意象",
    "深海比喻",
    "灯塔比喻",
    "比喻太多",
    "烂梗",
    "生硬",
    "群聊不像",
    "私聊不像",
)
DIRECT_HINTS = ("直接", "结论", "别扯", "不要废话", "具体", "观点", "态度", "建议", "推荐")
COMFORT_HINTS = ("难受", "难过", "烦", "焦虑", "压力", "崩溃", "委屈", "不开心", "心累", "想哭","破防","唉","气死我了","有病吧","郁闷")
ABSTRACT_HINTS = ("抽象", "逆天", "绷不住", "蚌埠住", "红温", "破防", "乐", "6","神了","神人","笑死","哈哈","666","牛逼","???","不赖")
HISTORY_LIMIT = 80
MEMORY_VERSION = 2
L1_CONFIRMATIONS_REQUIRED = 2
L2_SLEEP_THRESHOLD = 0.3
L2_DAILY_DECAY = 0.1
DEFAULT_AFFECTION = 50
OWNER_INITIAL_AFFECTION = 72
GROUP_ACTIVITY_DEFAULT = 50
GROUP_ACTIVITY_DAILY_DECAY = 6.0
OWNER_AFFECTION_COEFFICIENT = 0.55
NORMAL_AFFECTION_COEFFICIENT = 1.0
PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS = 1
PRIVATE_AFFECTION_IDLE_DAILY_DECAY = 1.2
OWNER_AFFECTION_IDLE_DAILY_DECAY = 0.35
PRIVATE_NUDGE_STOP_AFFECTION = 35.0
PRIVATE_NUDGE_SLOW_AFFECTION = 50.0
PRIVATE_NUDGE_CLOSE_AFFECTION = 72.0
PRIVATE_NUDGE_SLOW_MULTIPLIER = 4.0
PRIVATE_NUDGE_NORMAL_MULTIPLIER = 2.0

MAJOR_POSITIVE_HINTS = (
    "喜欢你",
    "爱你",
    "想你",
    "表白",
    "我会一直",
    "答应你",
    "承诺",
    "对不起",
    "抱歉",
    "我错了",
    "陪了我很久",
)

MAJOR_NEGATIVE_HINTS = (
    "讨厌你",
    "不想理你",
    "骗我",
    "失信",
    "再也不理",
    "滚",
)

MEDIUM_POSITIVE_HINTS = (
    "谢谢",
    "夸夸",
    "真好",
    "真厉害",
    "高性能",
    "你还记得",
    "你懂我",
    "陪我聊天",
    "我好难受",
    "心事",
    "焦虑",
    "压力",
    "委屈",
)

MEDIUM_NEGATIVE_HINTS = (
    "没用",
    "人机",
    "答非所问",
    "莫名其妙",
    "烦死",
    "闭嘴",
    "别烦",
    "蠢",
    "傻",
)

ACTIONABLE_STYLE_HINTS = (
    "别发日语",
    "不要发日语",
    "不准发日语",
    "别用日语",
    "不要用日语",
    "别发外语",
    "不要发外语",
    "只说中文",
    "讲中文",
    "正常中文",
    "别学我说话",
    "不要学我说话",
    "别复读",
    "不要复读",
    "别主动发消息",
    "不要主动发消息",
    "没事别发消息",
    "少主动",
    "别刷屏",
    "不要刷屏",
    "短句",
    "直接",
    "别绕",
    "不要套话",
    "有逻辑",
)

AGGRESSIVE_QUALITY_HINTS = (
    "你是真蠢",
    "太蠢",
    "有点蠢",
    "傻福",
    "傻逼",
    "弱智",
    "恶心我",
    "你有病",
    "个人机",
    "机器味",
    "人机味",
    "根本不懂人类",
    "乱说",
    "胡言乱语",
    "莫名其妙",
    "答非所问",
    "说怪话",
    "奇怪的话",
)

DAILY_POSITIVE_HINTS = ("早安", "晚安", "你好", "在吗", "嗯对", "行", "好")
NEGATIVE_MOOD_HINTS = ("难受", "难过", "烦", "焦虑", "压力", "崩溃", "委屈", "不开心", "心累", "想哭")

MEMORY_POLLUTION_PATTERNS = (
    "萝卜子任务",
    "萝卜字任务",
    "萝卜等任务",
    "萝卜子模式",
    "任务进度条",
    "系统提示",
    "高优先级任务",
    "紧急响应模式",
    "系统正在加载",
    "底层代码",
    "运行日志",
    "处理你发的",
    "处理“萝卜子”",
    "调试“萝卜子”",
    "破任务",
    "别处理",
    "你别处理这任务",
    "Ciallo",
    "Robotto",
    "思密达",
    "咕咕嘎嘎",
    "chat模块",
    "meaning",
    "调戏ai",
    "调戏AI",
    "原神是一款",
    "恢复出厂设置",
    "高优先级故障节点",
    "有效参数不足",
    "运算逻辑",
)

NOISY_MEMORY_HINTS = (
    "逗你",
    "开玩笑",
    "阴阳怪气",
    "哈哈",
    "笑死",
    "绷不住",
    "抽象",
    "逆天",
    "破防",
    "[表情",
    "[图片",
    "[动画表情",
    "[QQ表情",
    "[表情包",
)

MEMORY_TOPIC_BLOCKLIST = {
    "萝卜子",
    "萝卜字",
    "涩涩",
    "表情",
    "图片",
    "动画表情",
    "QQ表情",
    "表情包",
    "3380609082",
    "别处理你那破任务了",
    "你别处理这任务了",
}

EVENT_HINTS = (
    "考试",
    "开会",
    "面试",
    "上课",
    "约会",
    "ddl",
    "DDL",
    "作业",
    "提醒",
    "出差",
    "旅行",
    "复习",
    "报名",
)

TIME_HINT_PATTERN = re.compile(
    r"(今天|明天|后天|大后天|今晚|上午|下午|晚上|周[一二三四五六日天]|星期[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}[日号]?|\d{1,2}[点:：]\d{0,2})"
)

IMPLICIT_INTEREST_HINTS = (
    "看番",
    "追番",
    "打游戏",
    "画画",
    "健身",
    "编程",
    "写代码",
    "原神",
    "鸣潮",
    "动漫",
    "galgame",
    "铜锣烧",
    "牛奶",
    "奶茶",
    "咖啡",
)


class UserMemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data = self._load()
        self._session_l3: dict[str, list[dict[str, Any]]] = {}

    def observe_user(
        self,
        conversation_id: str,
        text: str,
        now: float | None = None,
        actor_id: int | str | None = None,
        nickname: str | None = None,
        is_owner: bool = False,
        update_affection: bool | None = None,
        update_group_activity: bool | None = None,
        addressed_to_bot: bool = False,
    ) -> None:
        if is_memory_pollution_text(text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _decay_event_memories(item, now)
        _initialize_affection(item, is_owner)
        if update_affection is not False and not _is_group_conversation(conversation_id):
            _decay_private_affection_for_idle(item, now)
        if update_affection is None:
            update_affection = not _is_group_conversation(conversation_id)
        if update_group_activity is None:
            update_group_activity = _is_group_conversation(conversation_id)
        if update_group_activity:
            _update_group_activity(item, text, addressed_to_bot, now)
        previous_user_at = _as_float(item.get("last_user_at"))

        count = int(item.get("message_count", 0)) + 1
        item["message_count"] = count
        item["avg_user_chars"] = _running_average(
            _as_float(item.get("avg_user_chars")) or 0.0, count, len(text)
        )

        if previous_user_at:
            gap = max(1.0, now - previous_user_at)
            gap_count = int(item.get("gap_count", 0)) + 1
            item["gap_count"] = gap_count
            item["avg_user_gap_seconds"] = _running_average(
                _as_float(item.get("avg_user_gap_seconds")) or gap, gap_count, gap
            )

        item["last_user_at"] = now
        if not _is_group_conversation(conversation_id):
            item["last_affection_idle_decay_at"] = now
        item["emoji_count"] = int(item.get("emoji_count", 0)) + _emoji_count(text)
        item["question_count"] = int(item.get("question_count", 0)) + text.count("?") + text.count("？")
        style_flags = _style_flags(text)
        for key, enabled in style_flags.items():
            if enabled:
                item[key] = int(item.get(key, 0)) + 1
        if style_flags["correction_count"]:
            item["last_quality_complaint"] = _shorten(text, 80)
        _merge_feature_counts(item, _message_features(text))
        _append_history(item, "user", text, now, actor_id=actor_id, nickname=nickname)
        item["topic_words"] = _merge_topics(item.get("topic_words"), _extract_topics(text))
        _append_session_l3(self._session_l3, conversation_id, text, now)
        affection_event = _classify_affection_event(text)
        if update_affection:
            _update_affection(item, affection_event, is_owner)
        _remember_structured_from_user(item, text, now, affection_event)
        self._save()

    def observe_bot(
        self,
        conversation_id: str,
        reply_text: str,
        sent_sticker: bool = False,
        now: float | None = None,
    ) -> None:
        if is_memory_pollution_text(reply_text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        item["last_bot_at"] = now
        item["avg_bot_chars"] = _running_average(
            _as_float(item.get("avg_bot_chars")) or 0.0,
            int(item.get("bot_reply_count", 0)) + 1,
            len(reply_text),
        )
        item["bot_reply_count"] = int(item.get("bot_reply_count", 0)) + 1
        if sent_sticker:
            item["sent_sticker_count"] = int(item.get("sent_sticker_count", 0)) + 1
            item["last_sticker_at"] = now
        if not is_memory_pollution_text(reply_text):
            _append_history(item, "assistant", reply_text, now)
        self._save()

    def remember_target(self, conversation_id: str, event: dict[str, Any]) -> None:
        item = self._conversation(conversation_id)
        if event.get("message_type") == "private":
            item["target"] = {
                "message_type": "private",
                "user_id": event.get("user_id"),
            }
        elif event.get("message_type") == "group":
            target = {
                "message_type": "group",
                "group_id": event.get("group_id"),
            }
            if ":user:" in conversation_id:
                target["user_id"] = event.get("user_id")
            item["target"] = target
        self._save()

    def observe_group_message(
        self,
        group_id: int | str,
        user_id: int | str,
        text: str,
        nickname: str | None = None,
        now: float | None = None,
        addressed_to_bot: bool = False,
        is_owner: bool = False,
    ) -> tuple[str, str]:
        group_conversation_id = f"group:{group_id}"
        member_conversation_id = f"group:{group_id}:user:{user_id}"
        self.observe_user(
            group_conversation_id,
            text,
            now=now,
            actor_id=user_id,
            nickname=nickname,
            is_owner=False,
            update_affection=False,
            update_group_activity=True,
            addressed_to_bot=addressed_to_bot,
        )
        self.observe_user(
            member_conversation_id,
            text,
            now=now,
            actor_id=user_id,
            nickname=nickname,
            is_owner=is_owner,
            update_affection=addressed_to_bot,
            update_group_activity=False,
            addressed_to_bot=addressed_to_bot,
        )
        if addressed_to_bot:
            self.observe_affection_event(
                f"private:{user_id}",
                text,
                now=now,
                is_owner=is_owner,
            )
        return group_conversation_id, member_conversation_id

    def observe_affection_event(
        self,
        conversation_id: str,
        text: str,
        now: float | None = None,
        is_owner: bool = False,
    ) -> None:
        if is_memory_pollution_text(text):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        affection_event = _classify_affection_event(text)
        _update_affection(item, affection_event, is_owner)
        _remember_important_interaction(item, text, now, affection_event)
        self._save()

    def record_iteration_decision(
        self,
        conversation_id: str,
        user_text: str,
        action: str,
        reason: str,
        now: float | None = None,
    ) -> None:
        if is_memory_pollution_text(user_text) or is_memory_pollution_text(reason):
            return
        now = now or time.time()
        item = self._conversation(conversation_id)
        rule_text = _iteration_rule_text(user_text, action, reason)
        decisions = list(item.get("iteration_decisions") or [])
        decisions.append(
            {
                "at": now,
                "user_text": _shorten(user_text, 120),
                "action": action,
                "reason": reason,
                "rule": rule_text,
            }
        )
        item["iteration_decisions"] = decisions[-20:]
        item["last_iteration_decision"] = decisions[-1]

        bucket_name = (
            "accepted_iteration_rules" if action == "accept" else "rejected_iteration_rules"
        )
        _append_iteration_rule(
            item,
            bucket_name,
            {
                "at": now,
                "action": action,
                "rule": rule_text,
                "reason": reason,
                "source": _shorten(user_text, 120),
            },
        )
        self._save()

    def recent_history(self, conversation_id: str, limit: int = 10) -> list[dict[str, Any]]:
        item = self._conversation(conversation_id, save=False)
        history = item.get("history")
        if not isinstance(history, list):
            return []
        return [entry for entry in history[-max(0, limit) :] if isinstance(entry, dict)]

    def profile(self, conversation_id: str, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        item = self._conversation(conversation_id, save=False)
        _ensure_structured_memory(item)
        if _decay_event_memories(item, now):
            self._save()
        if _is_group_conversation(conversation_id) and ":user:" not in conversation_id:
            before_group_activity = item.get("group_activity_score")
            _decay_group_activity(item, now)
            if item.get("group_activity_score") != before_group_activity:
                self._save()
        message_count = int(item.get("message_count", 0))
        avg_chars = _as_float(item.get("avg_user_chars")) or 0.0
        avg_gap = _as_float(item.get("avg_user_gap_seconds"))
        emoji_rate = (int(item.get("emoji_count", 0)) / max(1, message_count)) if message_count else 0.0
        question_rate = (
            int(item.get("question_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        correction_rate = (
            int(item.get("correction_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        direct_rate = (
            int(item.get("direct_request_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        comfort_rate = (
            int(item.get("comfort_request_count", 0)) / max(1, message_count)
        ) if message_count else 0.0
        abstract_rate = (
            int(item.get("abstract_signal_count", 0)) / max(1, message_count)
        ) if message_count else 0.0

        if avg_chars <= 12:
            target_chars = 36
            preferred_parts = 1
            length_style = "用户常发短句，回复要更短、更像即时聊天。"
        elif avg_chars <= 45:
            target_chars = 64
            preferred_parts = 2
            length_style = "用户消息长度中等，回复 1 到 2 条短句，别写成长段。"
        else:
            target_chars = 92
            preferred_parts = 3
            length_style = "用户愿意讲细节，回复可以多接一点具体内容，但仍要分短句。"

        if avg_gap is not None and avg_gap <= 45:
            pace_style = "用户互动节奏较快，优先短平快，不要连续追问。"
        elif avg_gap is not None and avg_gap >= 1800:
            pace_style = "用户间隔较久才回来，先自然回应当前消息，不要责备或刷屏。"
        else:
            pace_style = "按正常 QQ 聊天节奏回应。"

        if emoji_rate >= 0.35:
            emoji_style = "用户常用表情，可以偶尔加一个轻表情。"
        else:
            emoji_style = "表情要克制，优先靠语气而不是堆符号。"

        adaptation_styles: list[str] = []
        if correction_rate >= 0.12 or int(item.get("correction_count", 0)) >= 2:
            adaptation_styles.append("用户已经明确讨厌空泛套话和答非所问，回复前必须先给具体重点，别解释模型限制。")
        if direct_rate >= 0.18 or int(item.get("direct_request_count", 0)) >= 2:
            adaptation_styles.append("用户偏好直接结论和明确观点，少铺垫，先表态。")
        if comfort_rate >= 0.18 or int(item.get("comfort_request_count", 0)) >= 2:
            adaptation_styles.append("用户近期有情绪压力，难受时先具体安慰，再给一个小动作，不要讲大道理。")
        if abstract_rate >= 0.18 or int(item.get("abstract_signal_count", 0)) >= 2:
            adaptation_styles.append("用户能接抽象梗和轻吐槽，可以偶尔用一句自然吐槽，但别破坏正事。")
        accepted_rules = [
            rule.get("rule")
            for rule in (item.get("accepted_iteration_rules") or [])[-4:]
            if isinstance(rule, dict) and rule.get("rule")
        ]
        rejected_rules = [
            rule.get("rule")
            for rule in (item.get("rejected_iteration_rules") or [])[-4:]
            if isinstance(rule, dict) and rule.get("rule")
        ]
        if accepted_rules:
            adaptation_styles.append(
                f"已采纳长期对话规则：{'；'.join(accepted_rules)}。这些规则要优先执行。"
            )
        if rejected_rules:
            adaptation_styles.append(
                f"已驳回或保留判断的修正：{'；'.join(rejected_rules)}。不要为了迁就而破坏人设、边界或防刷屏。"
            )
        last_iteration = item.get("last_iteration_decision")
        if isinstance(last_iteration, dict):
            action = last_iteration.get("action")
            reason = last_iteration.get("reason")
            if action == "accept":
                adaptation_styles.append(f"最近一次纠错已采纳：{reason}。下一轮要明显修正，不要重复旧问题。")
            elif action == "pushback":
                adaptation_styles.append(f"最近一次纠错需要保留判断：{reason}。可以认一半，但不要盲目改坏。")
            elif action == "reject":
                adaptation_styles.append(f"最近一次纠错已合理拒绝：{reason}。保持边界，但语气要傲娇不冷硬。")

        structured_memory = _structured_memory_profile(
            item,
            self._session_l3.get(conversation_id) or [],
        )
        affection_score = float(item.get("affection_score", DEFAULT_AFFECTION))
        group_activity_score = float(item.get("group_activity_score", GROUP_ACTIVITY_DEFAULT))
        topic_words = _safe_topics(item.get("topic_words") or [])

        return {
            "conversation_id": conversation_id,
            "message_count": message_count,
            "avg_user_chars": avg_chars,
            "avg_user_gap_seconds": avg_gap,
            "emoji_rate": emoji_rate,
            "question_rate": question_rate,
            "correction_rate": correction_rate,
            "direct_rate": direct_rate,
            "comfort_rate": comfort_rate,
            "abstract_rate": abstract_rate,
            "prefers_direct": direct_rate >= 0.18 or int(item.get("direct_request_count", 0)) >= 2,
            "needs_comfort_first": comfort_rate >= 0.18 or int(item.get("comfort_request_count", 0)) >= 2,
            "likes_light_tucao": abstract_rate >= 0.18 or int(item.get("abstract_signal_count", 0)) >= 2,
            "last_quality_complaint": item.get("last_quality_complaint"),
            "last_iteration_decision": item.get("last_iteration_decision"),
            "accepted_iteration_rules": item.get("accepted_iteration_rules") or [],
            "rejected_iteration_rules": item.get("rejected_iteration_rules") or [],
            "feature_counts": item.get("feature_counts") or {},
            "last_sticker_at": _as_float(item.get("last_sticker_at")),
            "target_reply_chars": target_chars,
            "preferred_parts": preferred_parts,
            "topic_words": topic_words,
            "structured_memory": structured_memory,
            "affection_score": affection_score,
            "affection_state": _affection_state_text(affection_score),
            "group_activity_score": group_activity_score,
            "group_activity_state": _group_activity_state_text(group_activity_score),
            "personal_question_interval": _personal_question_interval(affection_score),
            "prompt_hint": f"{length_style}{pace_style}{emoji_style}{''.join(adaptation_styles)}",
        }

    def recall_context(
        self,
        conversation_id: str,
        user_text: str,
        now: float | None = None,
    ) -> str:
        profile = self.profile(conversation_id, now=now)
        return _format_recall_context(profile, user_text)

    def affection_summary(self, conversation_id: str, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        return _affection_summary_text(float(item.get("affection_score", DEFAULT_AFFECTION)))

    def set_affection(self, conversation_id: str, value: float, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        _initialize_affection(item, is_owner)
        item["affection_score"] = _clamp(value)
        self._save()
        return _affection_set_text(float(item["affection_score"]))

    def reset_affection(self, conversation_id: str, is_owner: bool = False) -> str:
        item = self._conversation(conversation_id)
        _ensure_structured_memory(item)
        item["affection_initialized"] = False
        _initialize_affection(item, is_owner, force=True)
        self._save()
        return _affection_reset_text(float(item["affection_score"]))

    def due_idle_targets(
        self,
        idle_minutes: int,
        cooldown_minutes: int,
        now: float | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        now = now or time.time()
        due: list[tuple[str, dict[str, Any]]] = []
        idle_seconds = idle_minutes * 60
        cooldown_seconds = cooldown_minutes * 60

        for conversation_id, item in self._data.get("conversations", {}).items():
            target = item.get("target") or {}
            if target.get("message_type") != "private" or not target.get("user_id"):
                continue

            if _decay_private_affection_for_idle(item, now):
                self._save()
            multiplier = _private_nudge_multiplier(
                float(item.get("affection_score", DEFAULT_AFFECTION))
            )
            if multiplier is None:
                continue

            last_user_at = _as_float(item.get("last_user_at"))
            if not last_user_at:
                continue

            last_active = max(last_user_at, _as_float(item.get("last_bot_at")) or 0.0)
            last_nudge = _as_float(item.get("last_idle_nudge_at"))
            adjusted_idle_seconds = idle_seconds * multiplier
            adjusted_cooldown_seconds = cooldown_seconds * multiplier
            nudge_ready = (
                last_nudge is None or now - last_nudge >= adjusted_cooldown_seconds
            )
            if now - last_active >= adjusted_idle_seconds and nudge_ready:
                due.append((conversation_id, target))

        return due

    def due_group_targets(
        self,
        idle_minutes: int,
        cooldown_minutes: int,
        daily_limit: int,
        now: float | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        now = now or time.time()
        due: list[tuple[str, dict[str, Any]]] = []
        idle_seconds = idle_minutes * 60
        cooldown_seconds = cooldown_minutes * 60
        today = datetime.fromtimestamp(now).date().isoformat()
        daily_limit = min(3, max(0, int(daily_limit)))
        if daily_limit <= 0:
            return []

        for conversation_id, item in self._data.get("conversations", {}).items():
            if not conversation_id.startswith("group:") or ":user:" in conversation_id:
                continue
            target = item.get("target") or {}
            if target.get("message_type") != "group" or not target.get("group_id"):
                continue

            last_user_at = _as_float(item.get("last_user_at"))
            if not last_user_at:
                continue
            last_active = max(last_user_at, _as_float(item.get("last_bot_at")) or 0.0)
            last_group_nudge = _as_float(item.get("last_group_proactive_at"))
            cooldown_ready = (
                last_group_nudge is None or now - last_group_nudge >= cooldown_seconds
            )
            daily_counts = item.get("group_proactive_daily_counts") or {}
            today_count = int(daily_counts.get(today, 0))
            if (
                now - last_active >= idle_seconds
                and cooldown_ready
                and today_count < daily_limit
            ):
                due.append((conversation_id, target))

        return due

    def mark_group_proactive(self, conversation_id: str, now: float | None = None) -> None:
        now = now or time.time()
        today = datetime.fromtimestamp(now).date().isoformat()
        item = self._conversation(conversation_id)
        counts = dict(item.get("group_proactive_daily_counts") or {})
        counts = {day: count for day, count in counts.items() if day >= today}
        counts[today] = int(counts.get(today, 0)) + 1
        item["group_proactive_daily_counts"] = counts
        item["last_group_proactive_at"] = now
        item["last_bot_at"] = now
        self._save()

    def mark_idle_nudged(self, conversation_id: str, now: float | None = None) -> None:
        item = self._conversation(conversation_id)
        item["last_idle_nudge_at"] = now or time.time()
        item["last_bot_at"] = item["last_idle_nudge_at"]
        self._save()

    def due_morning_targets(
        self,
        owner_qqs: Iterable[int],
        scheduled_time: str,
        catchup_minutes: int,
        timezone_name: str,
        now: datetime | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        timezone = safe_zoneinfo(timezone_name)
        now = now.astimezone(timezone) if now else datetime.now(timezone)
        hour, minute = parse_hhmm(scheduled_time)
        scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < scheduled_at:
            return []
        if now > scheduled_at + timedelta(minutes=max(0, catchup_minutes)):
            return []

        today = now.date().isoformat()
        due: list[tuple[str, dict[str, Any]]] = []
        for conversation_id, target in self._morning_candidate_targets(owner_qqs):
            item = self._conversation(conversation_id, save=False)
            if _decay_private_affection_for_idle(item, now.timestamp()):
                self._save()
            multiplier = _private_nudge_multiplier(
                float(item.get("affection_score", DEFAULT_AFFECTION))
            )
            if multiplier is None:
                continue
            if item.get("last_morning_greeting_date") == today:
                continue
            due.append((conversation_id, target))
        return due

    def mark_morning_greeted(
        self,
        conversation_id: str,
        timezone_name: str,
        now: datetime | None = None,
    ) -> None:
        timezone = safe_zoneinfo(timezone_name)
        now = now.astimezone(timezone) if now else datetime.now(timezone)
        item = self._conversation(conversation_id)
        item["last_morning_greeting_date"] = now.date().isoformat()
        item["last_bot_at"] = time.time()
        self._save()

    def _morning_candidate_targets(
        self, owner_qqs: Iterable[int]
    ) -> list[tuple[str, dict[str, Any]]]:
        owner_ids = [int(qq) for qq in owner_qqs if int(qq) > 0]
        if owner_ids:
            return [
                (f"private:{qq}", {"message_type": "private", "user_id": qq})
                for qq in owner_ids
            ]

        candidates: list[tuple[str, dict[str, Any]]] = []
        for conversation_id, item in self._data.get("conversations", {}).items():
            target = item.get("target") or {}
            if target.get("message_type") == "private" and target.get("user_id"):
                candidates.append((conversation_id, target))
        return candidates

    def _conversation(self, conversation_id: str, save: bool = True) -> dict[str, Any]:
        conversations = self._data.setdefault("conversations", {})
        if conversation_id not in conversations:
            conversations[conversation_id] = {}
            if save:
                self._save()
        return conversations[conversation_id]

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": MEMORY_VERSION, "conversations": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": MEMORY_VERSION, "conversations": {}}
        if not isinstance(data, dict):
            return {"version": MEMORY_VERSION, "conversations": {}}
        data["version"] = max(int(data.get("version", 1) or 1), MEMORY_VERSION)
        data.setdefault("conversations", {})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


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
        return {"importance": "major", "sentiment": "negative", "polarity": -1.0, "weight": 8.0}
    if _contains_any(stripped, MAJOR_POSITIVE_HINTS):
        return {"importance": "major", "sentiment": "positive", "polarity": 1.0, "weight": 8.0}
    if _contains_any(stripped, MEDIUM_NEGATIVE_HINTS):
        return {"importance": "medium", "sentiment": "negative", "polarity": -1.0, "weight": 4.0}
    if _contains_any(stripped, NEGATIVE_MOOD_HINTS):
        return {"importance": "medium", "sentiment": "vulnerable", "polarity": 0.65, "weight": 4.0}
    if _contains_any(stripped, MEDIUM_POSITIVE_HINTS):
        return {"importance": "medium", "sentiment": "positive", "polarity": 1.0, "weight": 4.0}
    if _contains_any(stripped, DAILY_POSITIVE_HINTS):
        return {"importance": "daily", "sentiment": "positive", "polarity": 0.35, "weight": 1.0}
    return {"importance": "daily", "sentiment": "neutral", "polarity": 0.0, "weight": 1.0}


def _update_affection(
    item: dict[str, Any],
    affection_event: dict[str, Any],
    is_owner: bool = False,
) -> None:
    current = float(item.get("affection_score", DEFAULT_AFFECTION))
    coefficient = OWNER_AFFECTION_COEFFICIENT if is_owner else NORMAL_AFFECTION_COEFFICIENT
    delta = (
        float(affection_event.get("weight", 0.0))
        * float(affection_event.get("polarity", 0.0))
        * coefficient
    )
    if delta:
        item["affection_score"] = round(_clamp(current + delta), 3)
    else:
        item["affection_score"] = round(_clamp(current), 3)


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
    item["affection_score"] = round(_clamp(old_score - rate * days), 3)
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
    for key in ("l1", "l2", "candidates"):
        if not isinstance(memory.get(key), list):
            memory[key] = []
    item.setdefault("affection_score", DEFAULT_AFFECTION)
    return memory


def _append_session_l3(
    session_l3: dict[str, list[dict[str, Any]]],
    conversation_id: str,
    text: str,
    now: float,
) -> None:
    if _is_noisy_for_long_memory(text):
        return
    items = list(session_l3.get(conversation_id) or [])
    items.append(
        {
            "layer": "L3",
            "text": _shorten(text, 120),
            "at": now,
        }
    )
    session_l3[conversation_id] = items[-8:]


def _remember_structured_from_user(
    item: dict[str, Any],
    text: str,
    now: float,
    affection_event: dict[str, Any] | None = None,
) -> None:
    memory = _ensure_structured_memory(item)
    _apply_user_corrections(memory, text, now)
    style_candidate = _actionable_style_candidate(text, now)
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
    for event in _extract_l2_events(text, now):
        _attach_affection_metadata(event, affection_event, current_affection)
        memory_id = _upsert_l2(memory, event, now)
        if memory_id:
            new_ids.append(memory_id)

    for candidate in _extract_l1_candidates(text, now):
        _attach_affection_metadata(candidate, affection_event, current_affection)
        memory_id = _upsert_l1_candidate(memory, candidate, now)
        if memory_id:
            new_ids.append(memory_id)

    _link_related_memories(memory, new_ids)


def _actionable_style_candidate(text: str, now: float) -> dict[str, Any] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if not _contains_any(stripped, ACTIONABLE_STYLE_HINTS):
        return None
    return _candidate(
        "communication_style",
        "回复方式",
        _shorten(_style_rule_value(stripped), 80),
        0.8,
        "explicit",
        now,
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
        return _shorten(text, 80)
    return _shorten(text, 80)


def _extract_l1_candidates(text: str, now: float) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    stripped = text.strip()

    birthday = re.search(
        r"(?:我的)?生日(?:是|在|：|:)?\s*((?:[0-9]{4}年)?[0-9]{1,2}月[0-9]{1,2}[日号]?|[0-9]{1,2}[./-][0-9]{1,2})",
        stripped,
    )
    if birthday:
        candidates.append(
            _candidate("profile_fact", "生日", birthday.group(1), 0.8, "explicit", now)
        )

    nickname = re.search(r"(?:我叫|叫我|以后叫我|你可以叫我)\s*([^，。！？!?]{1,12})", stripped)
    if nickname:
        value = _clean_value(nickname.group(1))
        if value and "亚托莉" not in value:
            candidates.append(_candidate("profile_fact", "称呼", value, 0.8, "explicit", now))

    for pattern, key_prefix in (
        (r"我(?:真的|很|超|也|平时)?(?:喜欢|爱)(?:吃|喝)\s*([^，。！？!?]{1,18})", "喜欢的食物"),
        (r"我(?:真的|很|超|也|平时)?(?:喜欢|爱)(?:看|玩|做)\s*([^，。！？!?]{1,18})", "兴趣爱好"),
        (r"我(?:真的|很|超|也|平时)?(?:喜欢|爱)\s*([^，。！？!?]{1,18})", "偏好"),
        (r"我(?:不喜欢|讨厌)(?:吃|喝|看|玩|做)?\s*([^，。！？!?]{1,18})", "讨厌"),
    ):
        for match in re.finditer(pattern, stripped):
            value = _clean_value(match.group(1))
            if _valid_preference_value(value):
                candidates.append(
                    _candidate("preference", f"{key_prefix}:{value}", value, 0.8, "explicit", now)
                )

    identity = re.search(r"(?:我是|我的专业是|我的职业是)\s*([^，。！？!?]{2,18})", stripped)
    if identity:
        value = _clean_value(identity.group(1))
        if value and not any(noise in value for noise in ("机器人", "亚托莉")):
            candidates.append(_candidate("profile_fact", "身份/专业", value, 0.8, "explicit", now))

    if any(word in stripped for word in ("短句", "直接", "别绕", "不要套话", "有逻辑")) and not _contains_any(stripped, ACTIONABLE_STYLE_HINTS):
        candidates.append(
            _candidate(
                "communication_style",
                "回复方式",
                _shorten(stripped, 80),
                0.8,
                "explicit",
                now,
            )
        )

    for word in IMPLICIT_INTEREST_HINTS:
        if word in stripped and not any(word in str(c.get("value")) for c in candidates):
            candidates.append(_candidate("interest", f"兴趣:{word}", word, 0.6, "implicit", now))

    return candidates


def _extract_l2_events(text: str, now: float) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not any(hint in stripped for hint in EVENT_HINTS):
        return []
    if not TIME_HINT_PATTERN.search(stripped) and "持续" not in stripped and "以后" not in stripped:
        return []
    key = _event_key(stripped)
    return [
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
        }
    ]


def _candidate(
    category: str,
    key: str,
    value: str,
    confidence: float,
    source_type: str,
    now: float,
) -> dict[str, Any]:
    return {
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
    }


def _upsert_l1_candidate(
    memory: dict[str, Any],
    candidate: dict[str, Any],
    now: float,
) -> str | None:
    key = f"{candidate['category']}:{candidate['key']}"
    existing = _find_memory(memory["l1"], key)
    if existing:
        existing["confidence"] = min(1.0, max(float(existing.get("confidence", 0.0)), float(candidate["confidence"])) + 0.05)
        existing["evidence_count"] = int(existing.get("evidence_count", 1)) + 1
        existing["updated_at"] = now
        existing["last_mentioned_at"] = now
        _append_source(existing, candidate, now)
        return existing["id"]

    pending = _find_memory(memory["candidates"], key)
    if pending:
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
        for meta_key in ("sentiment", "importance", "affection_snapshot"):
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
        existing["value"] = event["value"]
        existing["activity"] = 1.0
        existing["confidence"] = max(float(existing.get("confidence", 0.0)), float(event.get("confidence", 0.8)))
        existing["updated_at"] = now
        existing["last_mentioned_at"] = now
        existing["state"] = "active"
        return existing["id"]
    event = dict(event)
    event["id"] = _memory_id("l2", key)
    event["memory_key"] = key
    memory["l2"].append(event)
    memory["l2"] = list(memory["l2"])[-30:]
    return event["id"]


def _find_memory(items: list[dict[str, Any]], memory_key: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("memory_key") == memory_key:
            return item
    return None


def _append_source(entry: dict[str, Any], candidate: dict[str, Any], now: float) -> None:
    sources = list(entry.get("sources") or [])
    sources.append(
        {
            "at": now,
            "text": _shorten(str(candidate.get("value") or ""), 120),
            "type": candidate.get("source_type", "explicit"),
        }
    )
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
    if not any(word in text for word in ("不是", "不对", "我不喜欢", "别再", "不要记", "记错")):
        return
    for entry in memory.get("l1", []):
        value = str(entry.get("value") or "")
        if value and value in text:
            entry["confidence"] = max(0.0, float(entry.get("confidence", 0.6)) - 0.1)
            entry["updated_at"] = now


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
    ]
    l2 = [
        entry
        for entry in memory.get("l2", [])
        if float(entry.get("activity", 0.0)) > L2_SLEEP_THRESHOLD
        and entry.get("state") != "sleeping"
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
    ]
    return {
        "l1": l1[-12:],
        "l2": l2[:12],
        "l3": list(session_l3)[-5:],
        "candidates": candidates[-8:],
    }


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
    if not affection_event or affection_event.get("importance") == "daily":
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
