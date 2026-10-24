from __future__ import annotations

from . import *  # noqa: F403
from ...prompting import load_prompt


# 复用主聊天链路的人设文件作为群聊总结的角色基线，而不是自创一个弱化版文案口吻。
_FALLBACK_PERSONA = (
    "你是亚托莉（ATRI），《ATRI -My Dear Moments-》中的高性能仿生人少女。"
    "性格活泼、直率、好奇、会得意、偶尔笨拙、爱学习，常以第一人称'我'自称，"
    "可以自然地说'嘿嘿''哼哼''真是的''我是高性能的嘛'。"
)


def _persona_system_base() -> str:
    try:
        return load_prompt("atri_persona")
    except Exception:
        return _FALLBACK_PERSONA


def _member_input_line(item: dict[str, Any]) -> str:
    """把一位成员的可核验统计与真实原话拼成一行，供模型推断说话风格与行为。"""
    name = item.get("nickname") or item.get("user_id")
    quotes = [str(value).strip() for value in (item.get("samples") or []) if str(value).strip()]
    details = [
        f"发言 {item.get('messages', 0)} 条",
        f"{item.get('characters', 0)} 字",
        f"提问 {item.get('questions', 0)}",
        f"链接 {item.get('links', 0)}",
        f"行动信号 {item.get('action_signals', 0)}",
    ]
    line = f"- {name}: " + "，".join(details)
    if quotes:
        line += "；原话样例：" + "；".join(quotes[:2])
    return line

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
    persona = _persona_system_base()
    system = (
        persona + "\n\n"
        "你现在是在做一件事：用亚托莉写日志的习惯，把上面这段群聊整理成一篇『亚托莉的群聊日记』。\n"
        "写作要求：\n"
        "- 全程用第一人称『我』，不要每句报名字，也不要写成客观旁白或后台统计。\n"
        "- 口吻自然、短句，可带一点点『嘿嘿''哼哼''真是的''居然』；可以好奇、得意、犯迷糊，"
        "也可以在没把握时直接说『我也拿不准』。不要端水，也不要硬套卖萌。\n"
        "- 只根据读到的原话和统计来写，绝不编造人物、时间、链接、待办或结论；"
        "证据不足就标明『这块我也没完全看明白』。\n"
        "- 话题必须去重：同一件事、同一人物关系或同一技术问题即使措辞不同，也只能合并为一条，宁可少列。\n"
        "- 禁止出现以下后台/统计词：数据侧、从证据看、能确认的是、建议把、应把、分开记录、分开保存、"
        "先拒绝、排查、待办、方案、风险、用于区分、应区分、符合认证口径、可以确认、直观判断、长期记忆稳定。\n"
        "- 每个话题的『锐评/观察』不是分析结论，而是亚托莉看到这一幕的感受或反应，"
        "要引用该话题里的原话或关键词，自然、具体一点，别写套话。\n"
        "- 每个成员的『印象』写你（亚托莉）对这位群友在这一段聊天里的感觉，"
        "基于他/她的说话风格与行为（爱发问/爱接梗/爱分享/负责展开/默默看），可引用他/她的原话。"
        "不清楚就写『这次他话不多』，不要编造对方很热情。\n"
        "- 输出合法 JSON 对象；区分已达成结论、待办、开放问题、普通闲聊和不确定信息。"
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
        _member_input_line(item) for item in statistics.get("active_members", [])[:12]
    ) or "（没有可用的成员统计）"
    atmosphere = statistics.get("atmosphere") if isinstance(statistics.get("atmosphere"), list) else []
    atmosphere_text = "\n".join(
        f"- {item.get('period')}（{item.get('message_count')} 条）："
        + "；".join(item.get("samples", [])[:2])
        for item in atmosphere[:6]
    ) or "（未检测到明显的高频互动或玩梗瞬间）"
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

氛围与互动瞬间（用来感受气氛/情绪/玩梗，不参与话题归类）：
{atmosphere_text[:6000]}

活跃成员（画像要写亚托莉对每个人的第一人称印象和说话风格，可引用他们的原话；统计只作参考，不要凭数字编造性格）：
{member_text[:9000]}

最近历史报告（仅用于避免重复，不可补写本次没有出现的事实）：
{history_text[:4000]}

只输出：
{{
  "title": "带亚托莉口吻的简短报告标题",
  "atri_intro": "1-2句亚托莉风格的自然开场",
  "overview": "一句话概览，说明本时段最重要的变化",
  "activity_assessment": "用自己的话描述这一段的活跃程度和几个热闹的时刻，不评价成员好坏",
  "timeline": [{{"period":"{axis_hint}","summary":"具体发生了什么","speakers":["QQ昵称"],"samples":["QQ昵称：原话"],"message_count":0}}],
  "topics": [{{"title":"必须能概括具体事件/技术/决定的标题（禁止只写 ATRI、亚托莉、表情、闲聊、日常；不同条目不得描述同一事件）","summary":"2-5句，用亚托莉的口吻说明谁聊了什么、聊到哪、大家态度怎样","participants":["QQ昵称"],"atri_view":"亚托莉第一眼看到这一幕的感受/反应（可得意、好奇、犯迷糊、轻嗔），必须引用本话题里的具体原话或关键词，禁止写结论建议或后台分析","key_points":["有证据的要点"],"evidence":["原话或明确转述"],"status":"已确认/进行中/未确认"}}],
  "decisions": ["已明确达成的结论；没有就空数组"],
  "action_items": [{{"item":"待办内容","owner":"明确提及的成员或未指定","status":"待开始/进行中/已完成/未确认","evidence":"依据原话"}}],
  "open_questions": ["尚未回答的问题"],
  "notable_quotes": [{{"speaker":"昵称","quote":"不超过80字的原话","why":"亚托莉为什么记住这句（用她的语气，一两句）"}}],
  "member_highlights": [{{"name":"QQ昵称","atri_impression":"亚托莉对这个人的第一人称印象（说话风格/在群里的样子，用她的语气，可引用原话）","quote_style":"最能代表其说话风格的1-2条原话","behavior":["爱发问/爱接梗/爱分享/负责展开/带动气氛/默默看/稳定参与"],"message_count":0}}],
  "key_points": ["跨话题的重要信息；没有就不要编造"],
  "mood": "用亚托莉的词描述这一天的整体气氛（热闹、柔软、吵吵闹闹、有点发懵……），证据不足就写‘我也有点拿不准’",
  "vibe": "2-3句说说这个时段最有人味/最好玩的瞬间，用亚托莉的口气",
  "atri_closing": "1句亚托莉式的结语",
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
