"""亚托莉风格群聊图文报告渲染器。

该模块只负责把已经存储的总结记录渲染成自包含 HTML，不参与消息采集、
话题聚类或模型调用。这样即使 WebUI 关闭，Markdown/JSON 导出仍不受影响。
"""

from __future__ import annotations

import html
import base64
import os
import re
from typing import Any, Iterable


def _text(value: Any, fallback: str = "") -> str:
    return html.escape(str(value if value is not None else fallback))


_MEDIA_MARKER_RE = re.compile(r"\[(?:表情包/图片|动画表情|图片)(?::[^\r\n]*?)?\]\]?", re.I)


def _clean_text(value: Any, fallback: str = "") -> str:
    """清理旧版归档留下的图片文件名/编码，避免把内部标识展示给用户。"""
    text = str(value if value is not None else fallback)
    text = _MEDIA_MARKER_RE.sub("图片", text)
    return _text(text)


def _media_html(media: Any) -> str:
    """群聊总结只保留头像，不展示消息中的图片或图片占位符。"""
    return ""


_ATRI_AVATAR_PATH = os.environ.get(
    "ATRI_REPORT_AVATAR",
    str(os.path.expanduser("~/Pictures/ATRI/atri-avatar.jpg")),
)


def _atri_avatar_src() -> str:
    """把亚托莉头像内嵌到报告，避免 WebUI 页面无法读取本地 file:// 路径。"""
    try:
        with open(_ATRI_AVATAR_PATH, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except (OSError, ValueError):
        return ""


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _stat_card(icon: str, value: Any, label: str, color: str) -> str:
    return (
        f'<div class="stat-card" style="--accent:{color}">'
        f'<div class="stat-icon">{icon}</div><strong>{_text(value, "0")}</strong>'
        f'<span>{_text(label)}</span></div>'
    )


def _hour_chart(hours: Any) -> str:
    values = [int(item or 0) for item in _items(hours)[:24]]
    values.extend([0] * (24 - len(values)))
    maximum = max(values) or 1
    bars: list[str] = []
    for hour, count in enumerate(values):
        width = round(count / maximum * 100, 2)
        tone = "coral" if count >= maximum * 0.7 else ("mint" if count >= maximum * 0.35 else "sky")
        bars.append(
            f'<div class="hour-row"><span>{hour:02d}:00</span>'
            f'<div class="hour-track"><i class="{tone}" style="width:{width}%"></i></div>'
            f'<b>{count}</b></div>'
        )
    return "".join(bars)


def _period_chart(statistics: dict[str, Any], period_type: str) -> str:
    """根据报告周期绘制统一风格的横向活跃条形图。"""
    if period_type == "daily":
        return _hour_chart(statistics.get("hour_distribution"))
    values = [int(item or 0) for item in _items(statistics.get("period_distribution"))]
    labels = [str(item) for item in _items(statistics.get("period_distribution_labels"))]
    if period_type == "weekly":
        labels = labels[:7] or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    else:
        labels = labels[: len(values)] or [f"第{index + 1}周" for index in range(len(values))]
    values.extend([0] * max(0, len(labels) - len(values)))
    maximum = max(values) or 1
    bars: list[str] = []
    for index, label in enumerate(labels):
        count = values[index] if index < len(values) else 0
        width = round(count / maximum * 100, 2)
        tone = "coral" if count >= maximum * 0.7 else ("mint" if count >= maximum * 0.35 else "sky")
        bars.append(
            f'<div class="period-row"><span>{_text(label)}</span>'
            f'<div class="hour-track"><i class="{tone}" style="width:{width}%"></i></div>'
            f'<b>{count}</b></div>'
        )
    return "".join(bars)


def _safe_topic_title(value: Any, index: int) -> str:
    """图文导出最后一道标题兜底，避免旧记录显示 ATRI/表情等占位词。"""
    title = str(value or "").strip()
    normalized = title.lower().replace(" ", "")
    if not title or normalized in {"atri", "亚托莉", "表情", "emoji", "闲聊", "日常讨论"}:
        return f"群聊重点讨论 {index + 1}"
    return title[:28]


def _topic_card(topic: dict[str, Any], index: int) -> str:
    title = _text(_safe_topic_title(topic.get("title"), index))
    summary = _clean_text(topic.get("summary") or "；".join(_items(topic.get("samples"))[:2]) or "暂无文字摘要")
    people = _items(topic.get("participants") or topic.get("active_members"))
    keywords = [item.get("word", item) if isinstance(item, dict) else item for item in _items(topic.get("keywords"))]
    points = _items(topic.get("key_points"))
    # 证据消息用于内部抽取与校验，但不直接展示在话题卡中。
    # 用户希望看到的是“讲清楚发生了什么”的摘要，而不是线索/证据列表。
    atri_view = _clean_text(topic.get("atri_view") or "亚托莉暂时没有足够信息形成额外判断。")
    people_html = "、".join(_text(item) for item in people[:8]) or "未识别"
    keyword_html = " ".join(f'<em>{_text(item)}</em>' for item in keywords[:8]) or '<em>日常讨论</em>'
    point_html = "".join(f"<li>{_text(item)}</li>" for item in points[:6])
    atri_avatar_src = _atri_avatar_src()
    atri_avatar = (
        f'<img class="atri-avatar-image" src="{_text(atri_avatar_src)}" alt="亚托莉" loading="lazy">'
        if atri_avatar_src else "A"
    )
    return f"""
    <article class="topic-card">
      <span class="washi-tape tape-topic"></span>
      <div class="topic-heading"><span class="check">☑</span><h3>{title}</h3><small>#{index + 1:02d}</small></div>
      <div class="participants">🧑‍🤝‍🧑 参与者：{people_html}</div>
      <div class="keywords">{keyword_html}</div>
      <p class="topic-summary">{summary}</p>
      <div class="atri-opinion"><div class="atri-avatar">{atri_avatar}</div><div><strong>亚托莉锐评</strong><p>{atri_view}</p></div></div>
      {f'<ul>{point_html}</ul>' if point_html else ''}
      {_media_html(topic.get("media"))}
    </article>
    """


def _member_cards(statistics: dict[str, Any], sections: dict[str, Any] | None = None) -> str:
    sections = sections or {}
    highlights = {
        str(item.get("name")): item
        for item in _items(sections.get("member_highlights"))
        if isinstance(item, dict)
    }
    cards: list[str] = []
    for index, member in enumerate(_items(statistics.get("active_members"))[:8]):
        if not isinstance(member, dict):
            continue
        name = str(member.get("nickname") or "未知成员")
        user_id = str(member.get("user_id") or "").strip()
        count = int(member.get("messages") or 0)
        evaluation = str(
            highlights.get(name, {}).get("evaluation")
            or highlights.get(name, {}).get("contribution")
            or "在本时段有稳定发言，可见度适中。"
        )
        role_items = _items(highlights.get(name, {}).get("roles"))
        role_html = " ".join(
            f'<em class="member-role">{_text(role)}</em>' for role in role_items[:3]
        )
        share = highlights.get(name, {}).get("share_percent")
        stats_line = f"{count} 条消息" + (f" · 占比 {float(share):.1f}%" if share is not None else "")
        palette = ("coral", "sky", "mint", "lavender")[index % 4]
        avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100" if user_id.isdigit() else ""
        avatar = (
            f'<div class="avatar {palette}"><img src="{avatar_url}" alt="{_text(name)}" loading="lazy" '
            f'onerror="this.style.display=\'none\'" /></div>'
            if avatar_url else f'<div class="avatar {palette}"></div>'
        )
        cards.append(
            f'<div class="member-card">{avatar}'
            f'<div class="member-copy"><strong>{_text(name)}</strong><div class="member-meta">{role_html}</div>'
            f'<small>{_text(stats_line)}</small><p>{_text(evaluation)}</p></div></div>'
        )
    return "".join(cards) or '<p class="muted">这一段时间还没有足够数据形成群友画像。</p>'


def _quote_cards(sections: dict[str, Any], important: Iterable[Any]) -> str:
    quotes = _items(sections.get("notable_quotes"))
    if not quotes:
        quotes = [
            {"speaker": item.get("nickname"), "quote": item.get("content"), "why": "被识别为重点证据"}
            for item in _items(important) if isinstance(item, dict)
        ]
    result: list[str] = []
    for item in quotes[:6]:
        if not isinstance(item, dict):
            continue
        result.append(
            f'<div class="quote-card"><div>💬 <strong>{_text(item.get("speaker") or "群友")}</strong></div>'
            f'<p>“{_text(item.get("quote") or item.get("content"))}”</p>'
            f'<small>{_text(item.get("why") or "亚托莉把这句话记在这里")}</small></div>'
        )
    return "".join(result) or '<p class="muted">暂时没有可展示的重点原话。</p>'


def group_summary_html(detail: dict[str, Any]) -> str:
    """生成自包含、可打印的亚托莉风格图文报告。"""
    statistics = detail.get("statistics") if isinstance(detail.get("statistics"), dict) else {}
    sections = statistics.get("report_sections") if isinstance(statistics.get("report_sections"), dict) else {}
    profile = statistics.get("activity_profile") if isinstance(statistics.get("activity_profile"), dict) else {}
    period_type = str(detail.get("period_type") or statistics.get("period_type") or "daily")
    period_label = _text(detail.get("period_label") or {"daily": "每日总结", "weekly": "周报", "monthly": "月度总结"}.get(period_type, "聊天观察报告"))
    group_label = _text(detail.get("group_name") or f"群 {detail.get('group_id')}")
    title = _text(detail.get("title") or f"{detail.get('group_name') or '群聊'} 聊天总结")
    start = _text(str(detail.get("period_start") or "").replace("T", " ")[:16])
    end = _text(str(detail.get("period_end") or "").replace("T", " ")[:16])
    topics = [item for item in _items(detail.get("topics")) if isinstance(item, dict)]
    timeline = [item for item in _items(sections.get("timeline")) if isinstance(item, dict)]
    if not timeline:
        timeline = [item for item in _items(sections.get("activity_segments")) if isinstance(item, dict)]
    local_timeline = [item for item in _items(statistics.get("period_timeline")) if isinstance(item, dict)]
    local_by_period = {str(item.get("period")): item for item in local_timeline}
    enriched_timeline: list[dict[str, Any]] = []
    for index, item in enumerate(timeline):
        local = local_by_period.get(str(item.get("period")))
        if local is None and index < len(local_timeline):
            local = local_timeline[index]
        merged = dict(item)
        if local:
            merged["speakers"] = merged.get("speakers") or local.get("speakers", [])
            merged["samples"] = merged.get("samples") or local.get("samples", [])
            merged["media"] = merged.get("media") or local.get("media", [])
        enriched_timeline.append(merged)
    timeline = enriched_timeline or local_timeline
    overview = sections.get("overview") or "这段时间的聊天已经整理完毕，下面是亚托莉看到的重点。"
    mood = sections.get("mood") or "未判断"
    high_point = sections.get("high_point") or (topics[0].get("summary") if topics else "暂未发现单一高光话题")
    topic_html = "".join(_topic_card(topic, index) for index, topic in enumerate(topics[:12]))
    timeline_rows: list[str] = []
    for item in timeline[:16]:
        speakers = "、".join(str(x) for x in _items(item.get("speakers"))[:6]) or "未识别"
        samples = _items(item.get("samples"))[:1]
        evidence = f'<small class="timeline-evidence">依据：{_clean_text(samples[0])}</small>' if samples else ""
        timeline_rows.append(
            f'<div class="timeline-item"><b>{_text(item.get("period"))}</b>'
            f'<span><small class="timeline-speakers">发言：{_text(speakers)}</small>'
            f'{_clean_text(item.get("summary") or "；".join(_items(item.get("samples"))[:2]) or "聊天持续进行中")}{evidence}</span>'
            f'<small>{int(item.get("message_count") or 0)} 条</small></div>'
        )
    timeline_html = "".join(timeline_rows) or '<p class="muted">暂时没有可绘制的时间线。</p>'
    tier = _text(profile.get("label") or "一般活跃")
    section_one = {
        "daily": "群聊总览和基本信息 · 24H 活跃轨迹",
        "weekly": "群聊总览和基本信息 · 每周活跃轨迹",
        "monthly": "群聊总览和基本信息 · 月度活跃轨迹",
    }.get(period_type, "群聊总览和基本信息 · 活跃轨迹")
    section_two = {"daily": "今日话题 Topics", "weekly": "本周话题 Topics", "monthly": "本月话题 Topics"}.get(period_type, "话题 Topics")
    activity_caption = {"daily": "24H 活跃轨迹", "weekly": "Monday – Sunday 活跃轨迹", "monthly": "按周活跃轨迹"}.get(period_type, "活跃轨迹")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 亚托莉图文报告</title>
<style>
:root {{ --ink:#59483f; --muted:#947f75; --coral:#f2a286; --sky:#a9dcf0; --sky-deep:#78bcd5; --mint:#c7e8d2; --pink:#f4c9d2; --apricot:#f8dfb6; --paper:#fffdf7; --line:#ded4c9; }}
* {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); font-family:"Microsoft YaHei", "Noto Sans SC", sans-serif; background-color:#fbfaf4; background-image:radial-gradient(rgba(205,195,183,.35) .8px,transparent .8px),linear-gradient(135deg,rgba(255,255,255,.6),rgba(244,235,220,.25)); background-size:18px 18px,100% 100%; }}
.toolbar {{ position:sticky;top:0;z-index:5;display:flex;justify-content:flex-end;gap:10px;padding:12px calc((100% - 900px)/2);background:#fffdf7e8;backdrop-filter:blur(8px); }}
button {{ border:1px solid #9bcddd; border-radius:999px; background:#fff3cf; color:var(--ink); padding:8px 18px; cursor:pointer;font-weight:700; }}
.sheet {{ width:min(900px,calc(100% - 28px)); margin:24px auto 80px; }}
.hero {{ position:relative; padding:46px 34px 34px; text-align:center; background:var(--paper); border:2px solid #9bcddd; border-radius:32px; box-shadow:0 8px 0 rgba(169,220,240,.42); transform:rotate(-.35deg); overflow:hidden; }}
.hero:before {{ content:""; position:absolute;top:-8px;left:38%;width:170px;height:28px;background:rgba(244,201,210,.72);transform:rotate(-2deg); }} .hero:after {{ content:"〰 〰 〰"; position:absolute;right:24px;bottom:10px;color:#8bc7db;font-size:25px;letter-spacing:5px; }}
.hero h1 {{ margin:8px 0 14px; color:#ea9679; font-family:"STKaiti","KaiTi","YouYuan","Comic Sans MS",cursive; font-size:clamp(30px,6vw,58px); line-height:1.2; text-shadow:1px 2px 0 #fff; letter-spacing:2px; }} .hero h2 {{ margin:0 0 16px;font-size:20px;font-weight:600; }} .hero p {{ margin:6px 0; }} .period {{ display:inline-block;padding:8px 16px;background:#fff1c8;border:1px solid #d9b98e;border-radius:8px;transform:rotate(1.5deg); }}
.intro {{ margin:28px 8px 20px; font-size:17px; line-height:1.9; color:#735f55; }}
.stats {{ display:grid;grid-template-columns:repeat(4,1fr);gap:14px; margin:20px 0 30px; }} .stat-card {{ position:relative;min-height:124px;padding:18px 12px;text-align:center;background:#fffefa;border:1px solid #abd7e7;border-radius:20px;box-shadow:0 5px 0 rgba(221,202,183,.45); }} .stat-card:after {{ content:"";position:absolute;right:-1px;top:-1px;border-style:solid;border-width:0 28px 28px 0;border-color:transparent #f5c6bd transparent transparent;opacity:.7; }} .stat-card:nth-child(2) {{ transform:rotate(1deg); }} .stat-card:nth-child(3) {{ transform:rotate(-.8deg); }} .stat-card:nth-child(4) {{ transform:rotate(1.2deg); }} .stat-icon {{ color:var(--sky-deep);font-size:26px; }} .stat-card strong {{ display:block;color:#e9997d;font-size:31px;margin:6px 0; }} .stat-card span {{ color:var(--muted);font-size:13px; }}
.paper-card {{ position:relative;background:rgba(255,253,247,.96); border:1px solid #d8cabc; border-radius:28px; padding:28px 30px; margin:24px 0; box-shadow:0 8px 0 rgba(172,215,228,.28); }} .section-title {{ display:flex;align-items:center;gap:10px;margin:0 0 18px;font-family:"STKaiti","KaiTi","YouYuan",cursive;font-size:28px;color:#5f706e; }} .section-title .mark {{ color:#ee9a7d; }} .section-title:after {{ content:"﹏﹏﹏"; color:#8ec8d9; margin-left:4px; font-family:serif;letter-spacing:2px; }}
.shell-deco {{ position:absolute;right:24px;top:18px;font-size:25px;opacity:.75;transform:rotate(12deg); }}
.high-point {{ background:#fff1c9;border:1px solid #e4c58d;border-radius:20px;padding:22px;font-size:19px;line-height:1.8;box-shadow:4px 5px 0 rgba(244,201,210,.45); }}
.hour-row {{ display:grid;grid-template-columns:58px 1fr 42px;gap:10px;align-items:center;margin:7px 0; }} .hour-row span,.hour-row b {{ font-variant-numeric:tabular-nums;font-size:13px; }} .hour-row b {{ text-align:right;color:var(--muted); }} .hour-track {{ height:16px;border:1px solid #9bcddd;border-radius:999px;overflow:hidden;background:#f7fbfa; }} .hour-track i {{ display:block;height:100%;border-radius:999px;min-width:4px;background:linear-gradient(90deg,#a9dcf0,#f3ab8c); }} .coral {{ background:linear-gradient(90deg,#a9dcf0,#f3ab8c) !important; }} .sky {{ background:#a9dcf0 !important; }} .mint {{ background:#c7e8d2 !important; }} .lavender {{ background:#f4c9d2 !important; }}
 .period-row {{ display:grid;grid-template-columns:116px minmax(0,1fr) 48px;gap:10px;align-items:center;margin:7px 0; }} .period-row span,.period-row b {{ font-variant-numeric:tabular-nums;font-size:13px; }} .period-row b {{ text-align:right;color:var(--muted); }}
.topic-grid {{ display:grid;grid-template-columns:1fr;gap:18px; }} .topic-card {{ position:relative;padding:26px 24px 22px;background:#fffefa;border:1px solid #d8cabc;border-radius:22px;box-shadow:0 6px 0 rgba(244,201,210,.34);background-image:linear-gradient(rgba(169,220,240,.18) 1px,transparent 1px);background-size:100% 34px; }} .washi-tape {{ position:absolute;top:-9px;left:42%;width:112px;height:23px;background:rgba(249,204,184,.68);transform:rotate(-2deg); }} .topic-heading {{ display:flex;align-items:baseline;gap:10px; }} .topic-heading h3 {{ margin:0;font-family:"STKaiti","KaiTi","YouYuan",cursive;font-size:26px;color:#5e6f6d; }} .topic-heading small {{ color:var(--muted); }} .check {{ color:#ed997b;font-size:24px; }} .participants {{ margin:14px 0 8px;color:var(--muted); }} .keywords em {{ display:inline-block;padding:3px 8px;margin:2px;background:#fce0d6;border-radius:999px;font-style:normal;font-size:12px; }} .topic-card p,.topic-card li {{ line-height:1.75; }} .topic-card ul {{ padding-left:22px; }} .topic-summary {{ font-size:16px; }} .atri-opinion {{ display:flex;gap:12px;align-items:flex-start;margin:18px 0 4px;padding:14px 16px;background:#e5f5fb;border:1px solid #a8d9e9;border-radius:18px; }} .atri-avatar {{ flex:0 0 38px;width:38px;height:38px;display:grid;place-items:center;border-radius:50%;background:#f3a288;color:#fff;border:2px solid #fff;font-family:"STKaiti","KaiTi",cursive;font-weight:700;font-size:21px;box-shadow:0 2px 0 #b5dbe5; }} .atri-opinion strong {{ color:#4e8fa5; }} .atri-opinion p {{ margin:4px 0 0; }} blockquote {{ margin:8px 0;padding:8px 12px;border-left:4px solid var(--coral);background:#fff9e4;font-size:14px; }}
.timeline {{ display:grid;grid-template-columns:1fr;gap:7px 18px;margin-top:12px; }} .timeline-item {{ display:grid;grid-template-columns:105px 1fr 48px;gap:8px;align-items:center;border-bottom:1px dashed #d8c9c0;padding:8px 0; }} .timeline-item span {{ line-height:1.5; }} .timeline-item small {{ color:var(--muted);text-align:right; }} .timeline-item .timeline-speakers {{ display:block;text-align:left;font-size:12px;color:#4e8fa5;margin-bottom:3px; }} .timeline-item .timeline-evidence {{ display:block;text-align:left;font-size:12px;color:#947f75;margin-top:3px;line-height:1.4; }} .split {{ display:grid;grid-template-columns:1fr 1fr;gap:22px; }} .split ul {{ line-height:1.9;padding-left:24px; }}
.member-grid {{ display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px; }} .member-card {{ display:flex;align-items:flex-start;gap:12px;min-width:0;padding:16px;background:#fffefa;border-radius:20px;border:1px solid #d9d0c8;box-shadow:0 4px 0 rgba(199,232,210,.6); }} .avatar {{ position:relative;overflow:hidden;width:56px;height:56px;flex:0 0 56px;display:grid;place-items:center;border-radius:50%;border:2px solid #fff;background:linear-gradient(145deg,#a9dcf0,#f4c9d2);color:#fff;font-family:"STKaiti","KaiTi",cursive;font-size:25px;font-weight:800;box-shadow:0 2px 0 #b7d9df; }} .avatar img {{ display:block;width:100%;height:100%;object-fit:cover; }} .avatar-fallback {{ position:absolute;inset:0;display:grid;place-items:center; }} .member-copy {{ min-width:0;overflow-wrap:anywhere; }} .member-copy strong {{ display:block;overflow-wrap:anywhere; }} .member-copy small {{ color:var(--muted);font-size:12px; }} .member-copy p {{ margin:6px 0 0;color:#735f55;font-size:13px;line-height:1.65;overflow-wrap:anywhere; }} .member-meta {{ margin:5px 0 2px; }} .member-role {{ display:inline-block;padding:2px 7px;margin-right:4px;border-radius:999px;background:#fff1c9;border:1px solid #e4c58d;color:#9a745e;font-size:11px;font-style:normal; }} .media-strip {{ display:flex;flex-wrap:wrap;gap:8px;margin-top:9px; }} .summary-media {{ display:block;width:auto;max-width:180px;max-height:140px;object-fit:cover;border-radius:12px;border:1px solid #b9dce8;box-shadow:0 2px 0 rgba(169,220,240,.4); }} .media-placeholder {{ display:inline-flex;align-items:center;padding:6px 10px;border-radius:10px;background:#fff1c9;color:#9a745e;font-size:13px; }}
.quote-grid {{ display:grid;grid-template-columns:repeat(2,1fr);gap:16px; }} .quote-card {{ padding:20px;background:#eee2f7;border-radius:14px;box-shadow:4px 4px 0 #d8c1e7; }} .quote-card p {{ font-size:18px;line-height:1.7; }} .quote-card small {{ color:var(--muted); }} .muted {{ color:var(--muted); }} footer {{ position:relative;text-align:center;color:#8b9e9b;padding:38px 0 20px;font-family:"STKaiti","KaiTi",cursive;font-size:18px; }} footer:before {{ content:"〰 〰 〰 〰 〰";display:block;color:#91cbd9;letter-spacing:5px;margin-bottom:12px; }}
@media(max-width:760px) {{ .stats,.topic-grid,.timeline,.split,.member-grid,.quote-grid {{ grid-template-columns:1fr; }} .hero {{ padding:34px 20px; }} .paper-card {{ padding:22px 18px; }} .toolbar {{ padding:10px 16px; }} .timeline-item {{ grid-template-columns:90px 1fr 38px; }} .period-row {{ grid-template-columns:108px minmax(0,1fr) 40px;gap:7px; }} }}
@media print {{ .toolbar {{ display:none; }} body {{ background:#fff; }} .sheet {{ width:100%;margin:0; }} .hero,.paper-card {{ break-inside:avoid; }} }}
 .member-card {{ overflow:hidden; }}
 .member-copy {{ flex:1 1 auto;min-width:0; }}
 .avatar {{ width:64px !important;height:64px !important;min-width:64px;min-height:64px;flex:0 0 64px !important;aspect-ratio:1 / 1; }}
 .avatar img {{ width:64px !important;height:64px !important;min-width:64px;min-height:64px;object-fit:cover;object-position:center; }}
 .member-role:nth-child(2) {{ background:#eee2f7;border-color:#bda5e4;color:#7653a8; }}
 :root {{ --paper:#FDF8F0;--sky:#D4ECF7;--apricot:#FDEBD0;--pink:#FCE4EC;--mint:#D5F5E3;--ink:#5d514b;--muted:#9b857b; }}
 body {{ background-color:#FDF8F0; background-image:radial-gradient(rgba(120,188,213,.18) 1px,transparent 1px),repeating-linear-gradient(0deg,rgba(255,255,255,.2) 0,rgba(255,255,255,.2) 1px,transparent 1px,transparent 5px),linear-gradient(135deg,#FDF8F0 0%,#fffaf4 52%,#FDEBD0 160%);background-size:22px 22px,100% 6px,100% 100%; }}
 .toolbar {{ background:rgba(253,248,240,.9);border-bottom:1px solid rgba(169,220,240,.45); }}
 .hero,.paper-card {{ background:rgba(253,248,240,.94);border-color:rgba(169,220,240,.72);border-radius:30px; }}
 .hero {{ box-shadow:0 9px 0 rgba(212,236,247,.72),0 16px 28px rgba(126,105,90,.08); }}
 .paper-card {{ box-shadow:0 8px 0 rgba(213,245,227,.78),0 10px 24px rgba(126,105,90,.06); }}
 .topic-card {{ background-color:#FDF8F0;box-shadow:0 6px 0 rgba(252,228,236,.78); }}
 .atri-avatar {{ overflow:hidden; }}
 .atri-avatar-image {{ display:block;width:100%;height:100%;object-fit:cover;object-position:center 34%; }}
 .avatar-fallback {{ display:none !important; }}
</style></head><body>
<div class="toolbar"><button onclick="window.print()">打印 / 保存 PDF</button><button onclick="window.close()">关闭</button></div>
<main class="sheet">
  <header class="hero"><p>🌱 ATRI · GROUP OBSERVATION</p><h1>{period_label}</h1><h2>{title}</h2><p class="period">{group_label}　{start} — {end}</p></header>
  <p class="intro">嗯嗯，我把这段时间的聊天整理好了。下面是亚托莉看到的重点；没有确认的地方，我会认真标记，不会把猜测当成事实。</p>
  <section class="stats">
    {_stat_card("▢", detail.get("message_count", 0), "消息总数", "var(--coral)")}
    {_stat_card("♧", statistics.get("member_count", 0), "参与人数", "#79c98c")}
    {_stat_card("✦", statistics.get("total_characters", 0), "总字符数", "#a778d5")}
    {_stat_card("◷", statistics.get("active_hours", 0), "活跃时段", "#69bfe7")}
  </section>
  <section class="paper-card"><span class="shell-deco">🐚</span><h2 class="section-title"><span class="mark">①</span>{section_one}</h2><div class="high-point">{_clean_text(overview)}</div><p class="muted">高光时刻：{_clean_text(high_point)}<br>聊天活跃度：{tier} · 整体氛围：{_clean_text(mood)}</p><h3>{activity_caption}</h3>{_period_chart(statistics, period_type)}<h3>聊天时间线</h3><div class="timeline">{timeline_html}</div></section>
  <section class="paper-card"><h2 class="section-title"><span class="mark">②</span>{section_two}</h2><div class="topic-grid">{topic_html or '<p class="muted">暂未形成可分组的话题。</p>'}</div></section>
  <section class="paper-card"><h2 class="section-title"><span class="mark">③</span>群友画像 · 活跃成员</h2><div class="member-grid">{_member_cards(statistics, sections)}</div></section>
  <footer>~ 今天也是充实的一天呢 ~<br><small>以上是亚托莉的群聊观察报告</small></footer>
</main></body></html>"""
