from __future__ import annotations

from . import *  # noqa: F403

def _visible_text(value: Any) -> str:
    """把历史消息中的内部图片标记变成可读文本，避免编码污染 WebUI Markdown。"""
    return MEDIA_MARKER_RE.sub("图片", str(value or ""))


def _message_media(message: dict[str, Any]) -> list[dict[str, Any]]:
    """统一读取 OneBot 媒体，并从旧归档正文里补回图片 URL。

    早期归档只保存了 ``[分享: ... 图片地址]`` 文本，没有单独的 media 字段。
    报告渲染器无法从编码字符串猜测图片，因此这里在分析阶段把 QQ 图床和常见
    图片扩展名 URL 提取成结构化媒体，前端就能正常显示图片而不是显示文件名。
    """
    result: list[dict[str, Any]] = []
    for item in message.get("media") or []:
        if isinstance(item, dict):
            result.append(dict(item))
    content = str(message.get("content") or "")
    urls = re.findall(r"https?://[^\s\]>)]+", content, flags=re.I)
    for raw_url in urls:
        url = raw_url.rstrip("'\"，。；;！!）)").replace(r"\\u0026", "&").replace(r"\u0026", "&")
        if not url:
            continue
        lower = url.lower()
        is_image = bool(re.search(r"\.(?:png|jpe?g|gif|webp)(?:[?#&]|$)", lower))
        is_qq_image = any(host in lower for host in ("photo.store.qq.com", "qzonestyle.gtimg.cn", "gchat.qpic.cn", "multimedia"))
        if not (is_image or is_qq_image):
            continue
        if not any(str(item.get("url") or "") == url for item in result):
            result.append({"url": url, "file": url.rsplit("/", 1)[-1][:120]})
    return result[:8]


def _tokenize(text: str) -> list[str]:
    """优先用 jieba；依赖缺失时仍能以正则退化运行。"""
    # OneBot 图片会被旧版解析器写成 [表情包/图片:xxx.jpg]；这些内部标记不应参与话题词频。
    normalized_text = re.sub(r"\[(?:表情包/图片|动画表情|图片)(?::[^\]]+)?\]", " ", str(text), flags=re.I)
    normalized_text = re.sub(r"\b[^\s\]]+\.(?:jpg|jpeg|png|gif|webp)\b", " ", normalized_text, flags=re.I)
    try:
        import jieba

        values = [str(value).strip().lower() for value in jieba.cut(normalized_text, cut_all=False)]
        return [value for value in values if len(value) >= 2 and value not in STOP_WORDS and not value.isdigit()]
    except ImportError:
        return [value.lower() for value in WORD_RE.findall(normalized_text) if value.lower() not in STOP_WORDS]


def _keywords(texts: Iterable[str], limit: int = 20) -> list[dict[str, Any]]:
    counts = Counter(token for text in texts for token in _tokenize(text))
    return [{"word": word, "count": count} for word, count in counts.most_common(limit)]


def _nickname_map(messages: Iterable[dict[str, Any]]) -> dict[str, str]:
    """从同一报告窗口内的历史消息回填真实群昵称。

    旧归档在 OneBot 没有传 sender.nickname 时会把 QQ 号写入 nickname；
    只要同一成员后来出现过一次正常昵称，整份报告都优先使用该昵称。
    """
    candidates: dict[str, Counter[str]] = defaultdict(Counter)
    for message in messages:
        user_id = str(message.get("user_id") or "").strip()
        nickname = str(message.get("nickname") or "").strip()
        if not user_id or not nickname or nickname == user_id or nickname.isdigit():
            continue
        candidates[user_id][nickname] += 1
    return {user_id: values.most_common(1)[0][0] for user_id, values in candidates.items() if values}


def _display_name(message: dict[str, Any], names: dict[str, str] | None = None) -> str:
    user_id = str(message.get("user_id") or "").strip()
    raw = str(message.get("nickname") or "").strip()
    return str((names or {}).get(user_id) or (raw if raw and not raw.isdigit() else "未知成员"))


def _resolve_period(period_type: str, anchor: str | date | datetime | None = None) -> tuple[datetime, datetime, str, str]:
    """把日期锚点转换为本地时区的完整周期，再以 UTC 保存。

    新 WebUI 只提交 ``daily/weekly/monthly``，日报/周报使用当前时刻滚动窗口，
    月报使用当前自然月；传入日期锚点时仍保留旧版按日历周期计算能力。旧的 custom
    时间范围由 ``submit`` 兼容处理。
    """
    kind = str(period_type or "daily").strip().lower()
    if kind not in {"daily", "weekly", "monthly"}:
        raise ValueError("周期类型只支持 daily、weekly 或 monthly")
    raw = anchor
    # 新入口不要求用户填写日期：日报/周报使用当前时刻向前滚动，
    # 月报则严格限制在当前自然月内。
    if raw is None or str(raw).strip() == "":
        now_local = datetime.now().astimezone().replace(second=0, microsecond=0)
        if kind == "daily":
            start = now_local - timedelta(hours=24)
            return start.astimezone(timezone.utc), now_local.astimezone(timezone.utc), f"{kind}-{now_local:%Y%m%d%H%M}", f"最近 24 小时 · 每日总结"
        if kind == "weekly":
            start = now_local - timedelta(days=7)
            return start.astimezone(timezone.utc), now_local.astimezone(timezone.utc), f"{kind}-{now_local:%Y%m%d%H%M}", f"最近 7 天 · 周报"
        start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc), now_local.astimezone(timezone.utc), f"{kind}-{now_local:%Y-%m}", f"{now_local:%Y年%m月} · 月度总结"
    elif isinstance(raw, datetime):
        local_date = raw.astimezone().date() if raw.tzinfo else raw.date()
    elif isinstance(raw, date):
        local_date = raw
    else:
        text = str(raw).strip()
        try:
            local_date = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().date()
        except ValueError:
            local_date = date.fromisoformat(text[:10])
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    start_date = local_date
    if kind == "weekly":
        start_date = local_date - timedelta(days=local_date.weekday())
        end_date = start_date + timedelta(days=7)
        key = f"{start_date.isocalendar().year}-W{start_date.isocalendar().week:02d}"
        label = f"{start_date:%Y年%m月%d日} – {(end_date - timedelta(days=1)):%m月%d日} · 周报"
    elif kind == "monthly":
        start_date = local_date.replace(day=1)
        end_date = start_date.replace(day=monthrange(start_date.year, start_date.month)[1]) + timedelta(days=1)
        key = f"{start_date:%Y-%m}"
        label = f"{start_date:%Y年%m月} · 月度总结"
    else:
        end_date = start_date + timedelta(days=1)
        key = start_date.isoformat()
        label = f"{start_date:%Y年%m月%d日} · 每日总结"
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=local_tz)
    end = datetime.combine(end_date, datetime.min.time(), tzinfo=local_tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), key, label


def _statistics(
    messages: list[dict[str, Any]],
    period_type: str = "daily",
    period_start: str | None = None,
) -> dict[str, Any]:
    names = _nickname_map(messages)
    members: dict[str, dict[str, Any]] = {}
    hours = [0] * 24
    lengths: list[int] = []
    timestamps: list[datetime] = []
    question_count = 0
    link_count = 0
    mention_count = 0
    action_signal_count = 0
    period_counts: list[int]
    kind = str(period_type or "daily").lower()
    if kind == "weekly":
        period_counts = [0] * 7
        period_labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    elif kind == "monthly":
        # 月报按自然月内的第 1～5 周统计；极少数跨时区/异常日期最多保留 6 桶。
        try:
            month_base = datetime.fromisoformat(str(period_start)).astimezone().date() if period_start else datetime.now().astimezone().date().replace(day=1)
            week_count = min(6, max(1, (monthrange(month_base.year, month_base.month)[1] + 6) // 7))
        except (TypeError, ValueError):
            week_count = 5
        period_counts = [0] * week_count
        period_labels = [f"第{index}周" for index in range(1, week_count + 1)]
    else:
        period_counts = [0] * 24
        period_labels = [f"{index:02d}:00" for index in range(24)]
    try:
        local_period_start = datetime.fromisoformat(str(period_start)).astimezone().date() if period_start else None
    except (TypeError, ValueError):
        local_period_start = None
    for message in messages:
        user_id = str(message.get("user_id") or "")
        member = members.setdefault(
            user_id,
            {
                "user_id": user_id,
                "nickname": _display_name(message, names),
                "messages": 0,
                "characters": 0,
                "questions": 0,
                "links": 0,
                "mentions": 0,
                "action_signals": 0,
                "keywords": [],
            },
        )
        member["messages"] += 1
        lengths.append(len(str(message.get("content") or "")))
        content = str(message.get("content") or "")
        has_question = int(any(mark in content for mark in ("？", "?")))
        has_link = int(bool(re.search(r"https?://|www\.", content, re.I)))
        has_mention = int("@" in content)
        has_action = int(bool(re.search(r"决定|结论|待办|需要|安排|截止|发布|报名|更新|请|记得", content)))
        question_count += has_question
        link_count += has_link
        mention_count += has_mention
        action_signal_count += has_action
        member["characters"] += len(content)
        member["questions"] += has_question
        member["links"] += has_link
        member["mentions"] += has_mention
        member["action_signals"] += has_action
        # 成员画像只统计自然聊天关键词；ATRI 的固定动作描写不应被当成该成员的主题。
        is_template_reply = ("ATRI" in str(message.get("nickname") or "") or "亚托莉" in str(message.get("nickname") or "")) and bool(
            re.search(r"呆毛|红瞳|签到|好感度|高性能的仿生人|抢来吃掉|捏捏|摸摸头|叉腰|凑近屏幕", content)
        )
        if not is_template_reply:
            member["keywords"].extend(item["word"] for item in _keywords([content], 4))
        with contextlib.suppress(ValueError, TypeError):
            timestamp = datetime.fromisoformat(str(message.get("created_at")))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
            timestamps.append(timestamp)
            local_timestamp = timestamp.astimezone()
            hours[local_timestamp.hour] += 1
            if kind == "weekly":
                period_counts[local_timestamp.weekday()] += 1
            elif kind == "monthly":
                base = local_period_start or local_timestamp.replace(day=1).date()
                offset = max(0, (local_timestamp.date() - base).days // 7)
                period_counts[min(offset, len(period_counts) - 1)] += 1
            else:
                period_counts[local_timestamp.hour] += 1
    active_members = sorted(members.values(), key=lambda item: (-int(item["messages"]), item["user_id"]))[:20]
    # 画像渲染和模型画像共用同一份占比，避免渲染层只拿到消息数而显示 0.0%。
    message_total = max(1, len(messages))
    for member in active_members:
        member["share_percent"] = round(int(member.get("messages") or 0) / message_total * 100, 1)
    duration_hours = 0.0
    if len(timestamps) >= 2:
        duration_hours = max((max(timestamps) - min(timestamps)).total_seconds() / 3600, 1 / 60)
    elif timestamps:
        duration_hours = 1 / 60
    return {
        "message_count": len(messages),
        "member_count": len(members),
        "active_members": active_members,
        "keywords": _keywords((str(message.get("content") or "") for message in messages), 30),
        "hour_distribution": hours,
        "peak_hour": max(range(24), key=lambda hour: hours[hour]) if messages else None,
        "average_message_length": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        "total_characters": sum(lengths),
        "duration_hours": round(duration_hours, 2),
        "messages_per_hour": round(len(messages) / duration_hours, 2) if duration_hours else 0,
        "active_hours": sum(1 for value in hours if value),
        "period_type": kind,
        "period_distribution": period_counts,
        "period_distribution_labels": period_labels,
        "question_count": question_count,
        "link_count": link_count,
        "mention_count": mention_count,
        "action_signal_count": action_signal_count,
    }


def _activity_profile(statistics: dict[str, Any]) -> dict[str, Any]:
    """根据消息量、成员数和消息速率选择摘要详细程度。"""
    count = int(statistics.get("message_count") or 0)
    rate = float(statistics.get("messages_per_hour") or 0)
    members = int(statistics.get("member_count") or 0)
    if count >= 300 or (count >= 80 and rate >= 90) or members >= 30:
        return {"tier": "very_active", "label": "高活跃", "detail_level": 4, "chunk_size": 14, "max_topics": 10, "max_tokens": 5600}
    if count >= 100 or (count >= 30 and rate >= 30) or members >= 12:
        return {"tier": "active", "label": "活跃", "detail_level": 3, "chunk_size": 11, "max_topics": 8, "max_tokens": 4200}
    if count >= 30 or (count >= 10 and rate >= 12) or members >= 5:
        return {"tier": "normal", "label": "一般活跃", "detail_level": 2, "chunk_size": 8, "max_topics": 5, "max_tokens": 3000}
    return {"tier": "quiet", "label": "低活跃", "detail_level": 1, "chunk_size": 6, "max_topics": 3, "max_tokens": 1800}


def _activity_segments(
    messages: list[dict[str, Any]],
    limit: int = 16,
    period_type: str = "daily",
    period_start: str | None = None,
) -> list[dict[str, Any]]:
    """按周期聚合聊天，给模型和图文报告提供可读的时间线。"""
    names = _nickname_map(messages)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for message in messages:
        raw = str(message.get("created_at") or "")
        try:
            timestamp = datetime.fromisoformat(raw).astimezone()
            if period_type == "weekly":
                bucket = timestamp.strftime("%A %Y-%m-%d")
            elif period_type == "monthly":
                base = datetime.fromisoformat(str(period_start)).astimezone().date() if period_start else timestamp.replace(day=1).date()
                bucket = f"第{max(1, (timestamp.date() - base).days // 7 + 1)}周"
            else:
                bucket = timestamp.strftime("%Y-%m-%d %H:00")
        except (ValueError, TypeError):
            bucket = "时间未知"
        buckets[bucket].append(message)
    def bucket_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[Any, ...]:
        period = item[0]
        if period_type == "monthly":
            match = re.search(r"(\d+)", period)
            return (int(match.group(1)) if match else 999,)
        if period_type == "weekly":
            return (period[-10:],)
        return (period,)

    segments: list[dict[str, Any]] = []
    for period, items in sorted(buckets.items(), key=bucket_key):
        speakers = Counter(_display_name(item, names) for item in items)
        segments.append({
            "period": period,
            "message_count": len(items),
            "keywords": [item["word"] for item in _keywords((str(x.get("content") or "") for x in items), 5)],
            # 时间线原话必须带 QQ 昵称，避免读者无法判断是谁说的。
            "speakers": [name for name, _ in speakers.most_common(5)],
            "samples": [
                f"{_display_name(item, names)}：{str(item.get('content') or '')[:180]}"
                for item in items[:3]
            ],
            "media": [media for item in items for media in _message_media(item)][:6],
        })
    return segments[-limit:]


def _important_messages(messages: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    """抽取可能包含结论、待办、问题、链接或引用的证据消息。"""
    names = _nickname_map(messages)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, message in enumerate(messages):
        content = str(message.get("content") or "").strip()
        score = 0
        score += 3 * int(bool(re.search(r"决定|结论|待办|安排|截止|发布|报名", content)))
        score += 2 * int("?" in content or "？" in content)
        score += 2 * int(bool(re.search(r"https?://|www\.", content, re.I)))
        score += int("@" in content) + int(len(content) >= 80)
        if score:
            scored.append((score, -index, {"nickname": _display_name(message, names), "content": content[:300], "created_at": message.get("created_at"), "media": _message_media(message)}))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def _member_highlights(statistics: dict[str, Any]) -> list[dict[str, Any]]:
    """为活跃成员生成不带人格臆测的客观描述，供模型和降级报告复用。"""
    result: list[dict[str, Any]] = []
    total = max(1, int(statistics.get("message_count") or 0))
    topic_terms = {
        "夏生", "喜欢", "恋人", "船上", "收音机", "Dear", "Moments", "音乐", "歌曲", "remix",
        "具身", "智能", "情感", "DeepSeek", "模型", "账号", "买家", "高风险", "机器人", "启动",
        "相册", "分享", "学校", "中考", "高中", "代码", "Python", "API", "token", "OpenSquilla",
        "美食", "螃蟹", "拉面", "西瓜", "好感度", "炒锅", "生锈",
    }
    for member in statistics.get("active_members", [])[:12]:
        count = int(member.get("messages") or 0)
        name = str(member.get("nickname") or member.get("user_id") or "未知成员")
        share = count / total * 100
        characters = int(member.get("characters") or 0)
        average_length = round(characters / count, 1) if count else 0
        details = [f"发言 {count} 条，占本时段 {share:.1f}%", f"平均每条约 {average_length} 字"]
        if int(member.get("questions") or 0):
            details.append(f"提出 {int(member.get('questions'))} 个问题")
        if int(member.get("links") or 0):
            details.append(f"分享 {int(member.get('links'))} 个链接")
        if int(member.get("action_signals") or 0):
            details.append(f"出现 {int(member.get('action_signals'))} 次安排/结论信号")
        if int(member.get("mentions") or 0):
            details.append(f"发起/参与 {int(member.get('mentions'))} 次群友互动")
        raw_keywords = [str(item) for item in member.get("keywords", []) if str(item)]
        keywords = [item for item in raw_keywords if any(term.lower() in item.lower() for term in topic_terms)]
        keywords = list(dict.fromkeys(keywords))[:5] or list(dict.fromkeys(raw_keywords))[:3]
        if keywords:
            details.append("主要围绕「" + "、".join(dict.fromkeys(keywords[:5])) + "」")
        evaluation = "；".join(details) + "。"
        roles: list[str] = []
        if "ATRI" in name or "亚托莉" in name:
            roles.append("机器人回应")
        if count >= max(3, total * 0.2):
            roles.append("活跃核心")
        if int(member.get("action_signals") or 0):
            roles.append("推进者")
        if int(member.get("links") or 0):
            roles.append("资料分享")
        if int(member.get("questions") or 0):
            roles.append("提问发起")
        if int(member.get("mentions") or 0) >= max(5, count // 3):
            roles.append("互动串联")
        if not roles:
            roles.append("稳定参与")
        result.append({
            "name": name,
            "message_count": count,
            "characters": characters,
            "share_percent": round(share, 1),
            "roles": roles,
            "evaluation": evaluation,
        })
    return result
