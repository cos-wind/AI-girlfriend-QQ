from __future__ import annotations

from . import *  # noqa: F403

def _schedule_signature(settings: dict[str, Any]) -> str:
    """Stable signature for fields that determine future publication slots."""
    return json.dumps(
        {
            "period_days": int(settings.get("period_days", 1) or 1),
            "posts_per_period": int(settings.get("posts_per_period", 1) or 1),
            "post_start_hour": int(settings.get("post_start_hour", 8) or 0),
            "post_end_hour": int(settings.get("post_end_hour", 23) or 0),
            "timezone": str(settings.get("timezone") or "Asia/Shanghai"),
            # Fixed/random legacy fields are intentionally excluded. The
            # module now has one scheduling model: persisted-looking,
            # deterministic jittered slots inside the configured window.
        },
        ensure_ascii=False,
        sort_keys=True,
    )

def parse_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = str(value or "").replace("，", ",").replace("\n", ",").split(",")
    return [str(item).strip() for item in values if str(item).strip()][:50]


def _period_window(settings: dict[str, Any], now: float | None = None) -> tuple[datetime, datetime, datetime]:
    current = float(now or time.time())
    zone = _zone(settings.get("timezone"))
    local = datetime.fromtimestamp(current, zone)
    days = max(1, min(31, int(settings.get("period_days", 1) or 1)))
    anchor = datetime(1970, 1, 1, tzinfo=zone).date()
    offset = (local.date() - anchor).days
    start_date = local.date() - timedelta(days=offset % days)
    start_hour = max(0, min(23, int(settings.get("post_start_hour", 8) or 0)))
    end_hour = max(0, min(24, int(settings.get("post_end_hour", 23) or 0)))
    if end_hour <= start_hour:
        end_hour = min(24, start_hour + 1)
    window_start = datetime(start_date.year, start_date.month, start_date.day, start_hour, tzinfo=zone)
    if end_hour == 24:
        window_end = datetime(start_date.year, start_date.month, start_date.day, tzinfo=zone) + timedelta(days=1)
    else:
        window_end = datetime(start_date.year, start_date.month, start_date.day, end_hour, tzinfo=zone)
    return local, window_start, window_end


def schedule_times(settings: dict[str, Any], now: float | None = None) -> list[float]:
    """Return stable, evenly distributed random slots for the current period.

    A random offset is selected inside each equal-width bucket. The seed is
    derived from the schedule signature and period start, so page refreshes,
    restarts, and 30-second ticks never reshuffle already displayed times.
    """
    _, window_start, window_end = _period_window(settings, now)
    count = max(1, min(20, int(settings.get("posts_per_period", 1) or 1)))
    signature = _schedule_signature(settings)
    period_key = window_start.strftime("%Y-%m-%d")
    seed = int.from_bytes(hashlib.sha256(f"{signature}|{period_key}".encode()).digest()[:8], "big")
    generator = random.Random(seed)
    span = max(120.0, window_end.timestamp() - window_start.timestamp())
    spacing = span / count
    # Keep a safety margin from the edges and from adjacent posts while still
    # giving every period a different natural distribution.
    return sorted(
        window_start.timestamp() + (index + generator.uniform(0.2, 0.8)) * spacing
        for index in range(count)
    )


def next_window_time(settings: dict[str, Any], now: float | None = None, posted_count: int | None = None) -> float:
    current = float(now or time.time())
    local, window_start, window_end = _period_window(settings, current)
    slots = schedule_times(settings, current)
    count = len(slots)
    posted = max(0, int(posted_count or 0))
    persisted = float(settings.get("next_post_at") or 0)
    persisted_period = str(settings.get("schedule_period_start") or "")
    if persisted and persisted_period == window_start.strftime("%Y-%m-%d") and posted < count:
        # A persisted catch-up time is authoritative until the post succeeds;
        # otherwise every dashboard read after a missed slot would move it by
        # a few milliseconds and the UI could never show a stable schedule.
        if persisted <= current + 30 or abs(persisted - slots[posted]) <= 60:
            return persisted
    if posted >= count or local >= window_end:
        next_period_start = window_start + timedelta(days=max(1, int(settings.get("period_days", 1) or 1)))
        return schedule_times(settings, next_period_start.timestamp())[0]
    if local < window_start:
        return slots[posted]
    candidate = slots[posted]
    # Preserve the earlier catch-up rule: if the process was offline at a
    # slot, publish once now, then continue at the next random slot.
    if current >= candidate + 30:
        return current
    return candidate


def topic_for_schedule(settings: dict[str, Any], now: float, slot_index: int | None = None) -> str:
    zone = _zone(settings.get("timezone"))
    local = datetime.fromtimestamp(float(now), zone)
    topics = [str(item).strip() for item in (settings.get("topic_rotation") or []) if str(item).strip()]
    if not topics:
        return "今天的生活、思考与观察"
    slots = max(1, min(20, int(settings.get("posts_per_period", 1) or 1)))
    if slot_index is None:
        scheduled_slots = schedule_times(settings, now)
        slot_index = min(range(len(scheduled_slots)), key=lambda index: abs(scheduled_slots[index] - float(now)))
    return topics[(local.toordinal() * slots + max(0, int(slot_index))) % len(topics)]


def sanitize_qzone_fact_context(raw_context: str, scheduled_at: float) -> str:
    """Keep only recent, attributable news blocks; drop calendars and encyclopedias."""
    raw = str(raw_context or "").strip()
    if not raw or "搜索失败：" in raw or "没有搜索到明确结果" in raw:
        return ""
    target = datetime.fromtimestamp(float(scheduled_at), timezone.utc)
    blocks = re.split(r"(?m)(?=^\d+\. 标题：)", raw)
    accepted: list[str] = []
    for block in blocks:
        if not re.match(r"^\d+\. 标题：", block.strip()):
            continue
        compact = block.strip()
        if any(marker in compact for marker in _UNRELIABLE_FACT_MARKERS):
            continue
        url_match = re.search(r"(?m)^\s*URL：([^\s]+)", compact)
        published_match = re.search(r"(?m)^\s*发布时间：(.+)$", compact)
        if not url_match or not published_match:
            continue
        hostname = (urlsplit(url_match.group(1).strip()).hostname or "").casefold().removeprefix("www.")
        if any(hostname == denied or hostname.endswith(f".{denied}") for denied in _UNRELIABLE_FACT_HOSTS):
            continue
        if not any(hostname == trusted or hostname.endswith(f".{trusted}") for trusted in _TRUSTED_FACT_HOST_SUFFIXES):
            continue
        published_text = published_match.group(1).strip()
        try:
            published = parsedate_to_datetime(published_text)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            age = target - published.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        if age < -timedelta(hours=12) or age > timedelta(days=7):
            continue
        accepted.append(compact)
        if len(accepted) >= 2:
            break
    if not accepted:
        return ""
    target_local = datetime.fromtimestamp(float(scheduled_at), _zone("Asia/Shanghai"))
    return (
        f"时间基准：{target_local:%Y-%m-%d %H:%M} Asia/Shanghai。"
        "以下仅为带发布时间和链接的近期媒体摘要，涉及结论时必须保留来源限定：\n"
        + "\n".join(accepted)
    )


def topic_prompt(
    settings: dict[str, Any],
    now: float | None = None,
    slot_index: int | None = None,
    recent_contents: list[str] | None = None,
    fact_context: str = "",
) -> str:
    zone = _zone(settings.get("timezone"))
    local = datetime.fromtimestamp(float(now or time.time()), zone)
    slots = max(1, min(20, int(settings.get("posts_per_period", 1) or 1)))
    if slot_index is None:
        scheduled_slots = schedule_times(settings, float(now or time.time()))
        slot_index = min(range(len(scheduled_slots)), key=lambda index: abs(scheduled_slots[index] - float(now or time.time())))
    topic = topic_for_schedule(settings, float(now or time.time()), slot_index)
    angle = POST_WRITING_ANGLES[
        (local.toordinal() * 5
         + max(0, int(slot_index or 0)) * 3)
        % len(POST_WRITING_ANGLES)
    ]
    writing_form = POST_WRITING_FORMS[
        (local.toordinal() * 3 + max(0, int(slot_index or 0)) * 5)
        % len(POST_WRITING_FORMS)
    ]
    base = str(settings.get("post_prompt") or DEFAULT_SETTINGS["post_prompt"]).strip()
    recent = [" ".join(str(item).split())[:140] for item in (recent_contents or []) if str(item).strip()][-5:]
    recent_hint = ""
    if recent:
        recent_hint = (
            "近期已经发布过的内容（只用于排重，不要复述）：\n- "
            + "\n- ".join(recent)
            + "\n"
        )
    fact_hint = ""
    if str(fact_context or "").strip():
        fact_hint = (
            "可核验的事实/最新消息上下文（只使用其中明确写出的信息，不要补写未提供的细节；"
            "如采用请自然提及来源或‘据报道’，不要伪装成亲眼所见）：\n"
            + str(fact_context).strip()[:3000]
            + "\n"
        )
    elif any(marker in topic for marker in ("热点", "新闻", "前沿", "科普", "技术", "科学", "研究")):
        fact_hint = (
            "本次没有取得通过来源校验的最新事实。不得声称出现了新论文、新研究、新产品、"
            "官方发布、现实事件或具体数据；请改写为不依赖时效信息的一般性概念科普，"
            "并避免‘最新、终于、据说、研究显示’等暗示现实进展的措辞。\n"
        )
    weekday = "一二三四五六日"[local.weekday()]
    return (
        f"{base}\n计划发布时间：{local:%Y-%m-%d %H:%M}（星期{weekday}）。"
        "正文必须贴合这个发布时间段：早晨写清晨/起床/晨光等场景，午后写当日进行中的见闻，"
        "夜间写收尾/回顾/夜色等场景；不要把夜间生成的语气原样套到早晨，也不要出现与发布时间冲突的表述。"
        f"本次主题方向：{topic}。本次切入角度：{angle}。本次写作形态：{writing_form}。"
        "请结合当前记忆、情绪和亚托莉人格自然创作，不要机械重复主题。"
        "内容必须包含具体事实、场景、概念、观察或问题之一，并严格服从本次写作形态；"
        "不要每次都使用‘观察—感悟—开放问题’结构，也不要固定以问句或人生道理结尾。"
        "禁止只堆阳光、海风、夜色、微笑等意象，"
        "禁止套用早安/晚安/想你/加油式空泛句式，禁止编造现实经历或声称自己实际看过不存在的内容。"
        "若提供了事实/最新消息，本次动态必须选用其中一个明确的信息，并用‘据报道’等方式和个人观点连接；"
        "不得用虚构的‘今天看到/窗边发现’来替代事实。"
        f"\n{fact_hint}{recent_hint}只输出可直接发布的 QQ 空间正文。"
    )


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    compact = re.sub(r"[\s，。！？；：、,.!?;:\-—…（）()]", "", str(value or ""))
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[index:index + size] for index in range(len(compact) - size + 1)}


def content_quality_issues(
    content: str,
    recent_contents: list[str] | None = None,
    *,
    fact_context: str | None = None,
    scheduled_at: float | None = None,
    timezone_value: Any = "Asia/Shanghai",
) -> list[str]:
    """Cheap deterministic gate before a generated post enters the pool."""
    text = " ".join(str(content or "").split())
    issues: list[str] = []
    if len(text) < 20:
        issues.append("正文过短，缺少具体观察和观点")
    if len(text) > 120:
        issues.append("正文过长，不适合动态阅读")
    if text and not any(mark in text for mark in "，。！？；："):
        issues.append("缺少清晰的句子推进")
    generic = ("阳光", "海风", "夜色", "微笑", "美好", "治愈", "加油", "想你")
    if sum(text.count(word) for word in generic) >= 3:
        issues.append("意象或套话密度过高")
    if re.search(r"((今天|刚刚|我刚|我在|窗边).{0,12}(看到|发现|遇到)|我看到)", text):
        issues.append("包含未经事实依据支持的虚构亲历")
    sensitive_claim = re.search(
        r"(距离.{0,16}(还有|只剩)\s*\d+\s*天|今天是.{0,16}(节|纪念日|\d{1,2}[月日])|"
        r"\d{4}[年/-]\d{1,2}[月/-]\d{1,2}|据.{0,12}(报道|消息).{0,30}\d)",
        text,
    )
    if sensitive_claim and fact_context is not None:
        claim_numbers = set(re.findall(r"\d+(?:\.\d+)?", sensitive_claim.group(0)))
        supported_numbers = set(re.findall(r"\d+(?:\.\d+)?", str(fact_context or "")))
        if not claim_numbers or not claim_numbers.issubset(supported_numbers):
            issues.append("包含事实依据未支持的数字或日期")
    if fact_context == "" and re.search(
        r"(据.{0,8}(报道|消息|说)|官方.{0,8}(发布|宣布)|研究.{0,8}(显示|发现|证明|实现)|"
        r"论文.{0,10}(说|显示|发现|提出|证明)|实验室.{0,12}(新发|发布|实现|完成)|数据显示)",
        text,
    ):
        issues.append("包含没有可靠来源的现实事件陈述")
    if scheduled_at is not None:
        scheduled = datetime.fromtimestamp(float(scheduled_at), _zone(timezone_value))
        explicit_date = re.search(r"今天(?:是|正好是)?\s*(\d{1,2})月(\d{1,2})日", text)
        if explicit_date and (int(explicit_date.group(1)), int(explicit_date.group(2))) != (scheduled.month, scheduled.day):
            issues.append("正文日期与计划发布时间不一致")
        explicit_weekday = re.search(r"今天.{0,20}?星期([一二三四五六日天])", text)
        expected_weekday = "一二三四五六日"[scheduled.weekday()]
        if explicit_weekday and explicit_weekday.group(1).replace("天", "日") != expected_weekday:
            issues.append("正文星期与计划发布时间不一致")
        if scheduled.hour >= 11 and re.search(r"(^|[。！？])\s*(早安|刚起床|清晨好)", text):
            issues.append("正文时段与计划发布时间不一致")
        if scheduled.hour < 18 and re.search(r"(^|[。！？])\s*(晚安|夜深了)", text):
            issues.append("正文时段与计划发布时间不一致")
    recent = [" ".join(str(item).split()) for item in (recent_contents or []) if str(item).strip()]
    if text and any(text == item or (len(text) >= 24 and text[:24] == item[:24]) for item in recent[-5:]):
        issues.append("与近期内容重复")
    text_grams = _character_ngrams(text)
    for item in recent[-5:]:
        item_grams = _character_ngrams(item)
        union = text_grams | item_grams
        if union and len(text_grams & item_grams) / len(union) >= 0.58:
            issues.append("与近期内容表述高度相似")
            break
    return issues

def _contains_any(text: str, words: list[str]) -> bool:
    return bool(words) and any(word.casefold() in text.casefold() for word in words)


def _zone(value: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(value or "Asia/Shanghai"))
    except Exception:
        # Windows 精简 Python 环境可能没有 tzdata；QQ 空间默认使用东八区，
        # 这里用固定偏移兜底，不能让 WebUI 的状态接口因时区库缺失崩溃。
        return timezone(timedelta(hours=8))  # type: ignore[return-value]

