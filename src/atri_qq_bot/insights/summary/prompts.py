from __future__ import annotations

from . import *  # noqa: F403

def _summary_prompt(
    group_id: str,
    start: str,
    end: str,
    topics: list[dict[str, Any]],
    statistics: dict[str, Any],
    *,
    period_type: str = "custom",
    profile: dict[str, Any] | None = None,
    timeline: list[dict[str, Any]] | None = None,
    important_messages: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    profile = profile or _activity_profile(statistics)
    timeline = timeline or []
    important_messages = important_messages or []
    history = history or []
    system = (
        "你是亚托莉（ATRI），负责把群聊整理成温柔、清楚、略带活泼的观察报告。"
        "可以使用‘嗯嗯，我帮大家整理好了’这类自然口吻，但不要过度卖萌，也不要冒充群成员。"
        "只能根据证据消息和统计写作；没有证据的结论、人物归因、链接、时间和待办必须留空或标记为‘未确认’，绝不编造。"
        "区分已达成结论、待办、开放问题、普通闲聊和不确定信息；输出合法 JSON 对象。"
    )
    topic_text = "\n\n".join(
        f"话题候选 {index + 1}（{topic['message_count']} 条）：\n"
        f"时间 {topic.get('first_at') or '未知'} 至 {topic.get('last_at') or '未知'}；参与者：{', '.join(topic.get('active_members', [])[:8])}\n"
        + "\n".join(f"- {sample}" for sample in topic.get("samples", []))
        for index, topic in enumerate(topics)
    )
    timeline_text = "\n".join(
        f"- {item['period']}（{item['message_count']} 条）：关键词 {', '.join(item.get('keywords', []))}；"
        + "；".join(item.get("samples", [])[:2])
        for item in timeline
    ) or "（没有可用时间线）"
    evidence_text = "\n".join(
        f"- {item.get('nickname') or '未知成员'}：{item.get('content')}"
        for item in important_messages
    ) or "（没有检测到明显的结论、问题、待办或链接消息）"
    member_text = "\n".join(
        f"- {item.get('nickname') or item.get('user_id')}: 发言 {item.get('messages', 0)} 条，"
        f"{item.get('characters', 0)} 字，提问 {item.get('questions', 0)}，链接 {item.get('links', 0)}，"
        f"行动信号 {item.get('action_signals', 0)}，关键词 {', '.join(str(x) for x in item.get('keywords', [])[:6])}"
        for item in statistics.get("active_members", [])[:12]
    ) or "（没有可用的成员统计）"
    history_text = "\n".join(
        f"- {item.get('title') or '历史报告'}：{'; '.join(item.get('key_points') or [])}"
        for item in history[:3]
    ) or "（首次生成或没有可用历史）"
    period_name = {"daily": "每日总结", "weekly": "周报", "monthly": "月度总结"}.get(period_type, "指定时间范围总结")
    axis_hint = {
        "daily": "时间线按小时（00:00–23:00）",
        "weekly": "时间线按 Monday、Tuesday、Wednesday、Thursday、Friday、Saturday、Sunday",
        "monthly": "时间线按自然月内第 1 周、第 2 周等周次",
    }.get(period_type, "时间线按实际发生时间")
    prompt = f"""请生成一份{period_name}，总结群 {group_id} 在 {start} 至 {end} 的聊天。
本报告的活跃轴为：{axis_hint}；不要把周报或月报误写成单日总结。
统计：消息 {statistics.get('message_count')} 条，成员 {statistics.get('member_count')} 人，
活跃度：{profile['label']}（{profile['tier']}），消息速率约 {statistics.get('messages_per_hour', 0)} 条/小时，
问题 {statistics.get('question_count', 0)} 个，链接 {statistics.get('link_count', 0)} 个，提及 {statistics.get('mention_count', 0)} 次。
高频词：{', '.join(item['word'] for item in statistics.get('keywords', [])[:15])}。

{topic_text[:30000]}

时间线：
{timeline_text[:12000]}

重点证据消息（优先引用这些原话，不要把推测写成事实）：
{evidence_text[:12000]}

活跃成员客观统计（评价必须引用其中至少两项，不要臆测性格）：
{member_text[:8000]}

最近历史报告（仅用于避免重复，不可补写本次没有出现的事实）：
{history_text[:4000]}

只输出：
{{
  "title": "带亚托莉风格的简短报告标题",
  "atri_intro": "1-2句自然开场",
  "overview": "一句话概览，说明本时段最重要的变化",
  "activity_assessment": "根据消息量和时间线描述活跃程度，不评价成员好坏",
  "timeline": [{{"period":"{axis_hint}","summary":"具体发生了什么","speakers":["QQ昵称"],"samples":["QQ昵称：原话"],"message_count":0}}],
  "topics": [{{"title":"必须能概括具体事件/技术/决定的标题（禁止只写 ATRI、亚托莉、表情、闲聊、日常）","summary":"2-5句，说明谁讨论了什么、进展或结论是什么","participants":["QQ昵称"],"atri_view":"必须引用本话题中的具体关键词或原话，并给出下一步/风险判断，不得写泛泛的鼓励句","key_points":["有证据的要点"],"evidence":["原话或明确转述"],"status":"已确认/进行中/未确认"}}],
  "decisions": ["已明确达成的结论；没有就空数组"],
  "action_items": [{{"item":"待办内容","owner":"明确提及的成员或未指定","status":"待开始/进行中/已完成/未确认","evidence":"依据原话"}}],
  "open_questions": ["尚未回答的问题"],
  "notable_quotes": [{{"speaker":"昵称","quote":"不超过80字的原话","why":"为什么值得保留"}}],
  "member_highlights": [{{"name":"QQ昵称","evaluation":"必须包含发言条数/占比、平均长度，以及提问、链接、待办或主要关键词等至少两项可核验事实","message_count":0}}],
  "key_points": ["跨话题的重要信息；没有就不要编造"],
  "mood": "只描述聊天整体氛围，证据不足时写‘未判断’",
  "atri_closing": "1句温柔结语",
  "summary": "带标题、分点、时间线、话题、关键进展与待办、开放问题、原话和统计的 Markdown；内容详细程度要符合 {profile['label']} 活跃度"
}}
"""
    return system, prompt


def _fallback_report(
    group_id: str,
    topics: list[dict[str, Any]],
    statistics: dict[str, Any],
    *,
    period_type: str = "custom",
    profile: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = profile or _activity_profile(statistics)
    messages = messages or []
    period_name = {"daily": "每日总结", "weekly": "周报", "monthly": "月度总结"}.get(period_type, "聊天观察报告")
    timeline = _activity_segments(messages, period_type=period_type, period_start=statistics.get("period_start"))
    important = _important_messages(messages)
    rich_topics = _normalize_topics(topics, topics)
    key_points = [
        f"{topic['title']}：约 {topic['message_count']} 条消息，涉及「{'、'.join(item['word'] for item in topic.get('keywords', [])[:4])}」"
        for topic in rich_topics[: profile["max_topics"]]
    ]
    lines = [
        f"# 群 {group_id} 聊天总结 · 亚托莉观察报告",
        "",
        "嗯嗯，我把这段时间的聊天整理好了。下面的结论都尽量贴着群友说过的话，没确认的地方我会标出来。",
        "",
        "## 一句话概览",
        f"- 本时段共有 {statistics.get('message_count', 0)} 条消息、{statistics.get('member_count', 0)} 位成员参与，整体属于 **{profile['label']}**。",
        "",
        "## 活跃度与时间线",
        f"- 消息速率：约 {statistics.get('messages_per_hour', 0)} 条/小时；活跃时段：{statistics.get('active_hours', 0)} 个小时；峰值：{statistics.get('peak_hour', '未判断')} 点。",
    ]
    for segment in timeline:
        lines.append(f"- **{segment['period']}**（{segment['message_count']} 条）：{'；'.join(_visible_text(x) for x in segment.get('samples', [])[:2])}")
    lines.extend(["", "## 话题概览与证据"])
    for topic in rich_topics[: profile["max_topics"]]:
        samples = "；".join(_visible_text(x) for x in topic.get("samples", [])[:3]) or "暂无可展示原话"
        people = "、".join(topic.get("active_members", [])[:5]) or "未识别"
        lines.append(f"### {topic['title']}（{topic['message_count']} 条）")
        lines.append(f"- 参与成员：{people}")
        lines.append(f"- 关键词：{'、'.join(item['word'] for item in topic.get('keywords', [])[:8]) or '无'}")
        lines.append(f"- 观察：{samples}")
        lines.append(f"- 亚托莉锐评：{topic['atri_view']}")
    lines.extend(["", "## 关键进展与待办"])
    if important:
        for item in important[: max(8, profile["detail_level"] * 5)]:
            lines.append(f"- {item['nickname']}：{_visible_text(item['content'])}")
    else:
        lines.append("- 暂未发现带有明确结论、待办、链接或问题标记的消息。")
    lines.extend(["", "## 重要原话与开放问题"])
    questions = [item for item in important if "?" in item["content"] or "？" in item["content"]]
    for item in questions[:8]:
        lines.append(f"- {item['nickname']} 提问： “{_visible_text(item['content'])}”")
    if not questions:
        lines.append("- 暂未识别到需要继续追踪的问题。")
    lines.extend(
        [
            "",
            "## 群聊数据小结",
            "- 活跃成员：" + "、".join(item["nickname"] for item in statistics.get("active_members", [])[:8]),
            "- 高频关键词：" + "、".join(item["word"] for item in statistics.get("keywords", [])[:16]),
            f"- 提问 {statistics.get('question_count', 0)} 个，链接 {statistics.get('link_count', 0)} 个，提及 {statistics.get('mention_count', 0)} 次。",
            "",
            "以上是亚托莉的观察报告。想继续追踪某个话题的话，可以把时间范围缩小一些，我会整理得更细。",
        ]
    )
    return {
        "title": f"亚托莉的群 {group_id} {period_name}",
        "topics": rich_topics,
        "key_points": key_points,
        "timeline": timeline,
        "activity_profile": profile,
        "important_messages": important,
        "member_highlights": _member_highlights(statistics),
        "summary": "\n".join(lines),
    }
