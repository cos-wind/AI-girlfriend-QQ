from __future__ import annotations

from . import *  # noqa: F403

_GENERIC_IMPRESSION = ("很活跃", "贡献很大", "积极参与", "表现优秀", "不错", "很好", "棒", "群友")


def _normalize_member_highlights(value: Any, statistics: dict[str, Any]) -> list[dict[str, Any]]:
    """把模型画像和本地统计合并，保留可核验数据，并让模型可提供印象/风格/行为。

    本地 ``_member_highlights`` 已经自带基于行为的印象、原话样例与统计；模型
    只有在该字段够具体、不空泛时才覆盖，避免退回“很活跃/贡献很大”这类套话。
    """
    local = _member_highlights(statistics)
    model = {
        str(item.get("name")): item
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    result: list[dict[str, Any]] = []
    for item in local:
        candidate = model.get(item["name"], {})
        merged = dict(item)
        impression = str(candidate.get("atri_impression") or candidate.get("evaluation") or "").strip()
        if len(impression) >= 16 and not any(word in impression for word in _GENERIC_IMPRESSION):
            merged["atri_impression"] = impression[:140]
        quote = candidate.get("quote_style")
        if isinstance(quote, list) and quote and all(str(q).strip() for q in quote):
            merged["quote_style"] = [str(q)[:160] for q in quote][:3]
        elif isinstance(quote, str) and quote.strip():
            merged["quote_style"] = [str(quote).strip()[:160]]
        behavior = candidate.get("behavior")
        if isinstance(behavior, list) and behavior:
            merged["behavior"] = [str(x) for x in behavior][:6]
        elif isinstance(behavior, str) and behavior.strip():
            merged["behavior"] = [behavior.strip()]
        result.append(merged)
    return result


def _merge_timeline_speakers(value: Any, local_timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为模型时间线补回本地证据中的发言人和带昵称原话。"""
    model_items = value if isinstance(value, list) else []
    local_by_period = {str(item.get("period")): item for item in local_timeline if isinstance(item, dict)}
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(model_items):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        local = local_by_period.get(str(item.get("period")))
        if local is None and index < len(local_timeline):
            local = local_timeline[index]
        if local:
            item["speakers"] = item.get("speakers") or local.get("speakers", [])
            item["samples"] = item.get("samples") or local.get("samples", [])
            item["media"] = item.get("media") or local.get("media", [])
        result.append(item)
    return result or [dict(item) for item in local_timeline]


def _message_chunks(messages: list[dict[str, Any]], size: int = 8) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for offset in range(0, len(messages), size):
        batch = messages[offset : offset + size]
        text = "\n".join(
            f"{item.get('nickname') or item.get('user_id')}：{str(item.get('content') or '')[:500]}"
            for item in batch
        )
        chunks.append({"text": text[:4000], "messages": batch})
    return chunks


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _normalize(vector: list[float]) -> list[float]:
    length = sum(value * value for value in vector) ** 0.5
    return [value / length for value in vector] if length else vector


def _cluster_vectors(
    chunks: list[dict[str, Any]], vectors: Any, threshold: float, max_clusters: int
) -> list[list[int]]:
    """小数据在线质心聚类；低置信度的溢出片段不强行塞进无关主题。"""
    clusters: list[dict[str, Any]] = []
    for index, raw_vector in enumerate(vectors):
        vector = [float(value) for value in raw_vector]
        if not clusters:
            clusters.append({"centroid": vector, "indices": [index]})
            continue
        scores = [_cosine(vector, cluster["centroid"]) for cluster in clusters]
        best = max(range(len(scores)), key=scores.__getitem__)
        if scores[best] >= threshold:
            cluster = clusters[best]
            count = len(cluster["indices"])
            cluster["indices"].append(index)
            cluster["centroid"] = _normalize(
                [(old * count + new) / (count + 1) for old, new in zip(cluster["centroid"], vector)]
            )
        elif len(clusters) < max_clusters:
            clusters.append({"centroid": vector, "indices": [index]})
        # 达到候选簇上限后，语义距离不足的片段不参与主题提炼。
        # 统计与时间线仍然使用完整消息，因此不会造成日报消息数丢失。
    return [cluster["indices"] for cluster in clusters]


def _fallback_clusters(chunks: list[dict[str, Any]], maximum: int) -> list[list[int]]:
    """无向量模型时按关键词交集聚类，确保总结仍可生成。"""
    clusters: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        tokens = set(_tokenize(chunk["text"]))
        best_index = -1
        best_score = 0.0
        for position, cluster in enumerate(clusters):
            union = tokens | cluster["tokens"]
            score = len(tokens & cluster["tokens"]) / len(union) if union else 0.0
            if score > best_score:
                best_index, best_score = position, score
        if best_index >= 0 and best_score >= 0.12:
            clusters[best_index]["indices"].append(index)
            clusters[best_index]["tokens"].update(tokens)
        elif len(clusters) < maximum:
            clusters.append({"indices": [index], "tokens": set(tokens)})
        # 与所有已有簇都缺少关键词交集的低置信度片段不强行并入第一簇；
        # 否则会把无关聊天伪装成一个“大话题”。
    return [cluster["indices"] for cluster in clusters]


MEANINGLESS_TOPIC_TITLES = {
    "atri", "a", "亚托莉", "表情", "表情包", "图片", "emoji", "聊天", "闲聊", "日常", "讨论", "话题", "未命名", "群友", "先生",
}


def _meaningful_topic_title(
    title: Any,
    keywords: Iterable[Any],
    samples: Iterable[Any],
) -> str:
    """过滤模型的占位标题，并用证据关键词生成可读的主题标题。"""
    raw = re.sub(r"[\s#_/|·:：、，,。.!！?？~～]+", " ", str(title or "")).strip()
    normalized = re.sub(r"[^a-zA-Z\u4e00-\u9fff0-9]", "", raw).lower()
    if raw and len(raw) >= 3 and normalized not in MEANINGLESS_TOPIC_TITLES and not all(
        token in MEANINGLESS_TOPIC_TITLES for token in re.findall(r"[a-zA-Z\u4e00-\u9fff]+", raw.lower())
    ):
        return raw[:28]
    words: list[str] = []
    for item in keywords:
        word = str(item.get("word") if isinstance(item, dict) else item).strip()
        if word and word.lower() not in MEANINGLESS_TOPIC_TITLES and word not in words:
            words.append(word)
    if words:
        return "、".join(words[:3]) + "讨论"
    first_sample = next((str(item).split("：", 1)[-1].strip() for item in samples if str(item).strip()), "")
    return (first_sample[:18] + "讨论") if first_sample else "群聊重点讨论"


def _evidence_based_topic_view(topic: dict[str, Any]) -> str:
    """用参与者、关键词和原话构造亚托莉的第一人称反应，而不是分析建议。"""
    title = str(topic.get("title") or "这个话题")
    people = [str(item) for item in (topic.get("participants") or topic.get("active_members") or []) if str(item)]
    keywords = [
        str(item.get("word") if isinstance(item, dict) else item)
        for item in (topic.get("keywords") or [])
        if str(item.get("word") if isinstance(item, dict) else item).strip()
    ]
    samples = [str(item).strip() for item in (topic.get("samples") or topic.get("evidence") or []) if str(item).strip()]
    evidence = samples[0][:90] if samples else "你们聊天的那些话"
    key_text = "、".join(dict.fromkeys(keywords[:3])) or title
    actor = "、".join(people[:2]) or "大家"
    return (
        f"聊「{key_text}」的时候我也在，{actor}你一句我一句，"
        f"从“{evidence}”一路说到各自的想法，越聊越有来有回。嘿嘿，这种热闹我又想插嘴了，"
        "不过到底怎么定，我还是听你们聊出来的结论，不急着下判断。"
    )


# 这些词一旦出现，说明“锐评”退化成后台统计/风控建议，需换回亚托莉口吻。
_ADVISORY_MARKERS = (
    "建议把", "分开记录", "分开保存", "先拒绝", "比事后补救", "应把", "不等于",
    "长期记忆稳定", "排查", "待办", "方案", "数据侧", "风险", "用于区分", "应区分",
    "可以确认", "想验证时", "下一次就能", "判断模型", "直观判断", "是否理解", "要区分",
)


def _is_advisory_view(view: str) -> bool:
    """判断一条锐评是否仍是"数据分析/风控"腔调，需要换回亚托莉印象。"""
    text = str(view or "").strip()
    if len(text) < 30:
        return True
    if sum(1 for marker in _ADVISORY_MARKERS if marker in text) >= 1:
        return True
    # 完全没有第一人称/语气词，说明是旁观者客观口径，也需要人设化。
    if not re.search(r"我|嘿嘿|哼哼|真是的|哎|嘛|啦|呀|~|！", text):
        return True
    return False


def _is_keyword_soup_title(title: str) -> bool:
    """判断标题是否为“关键词拼接+讨论”这类没有语义概括的占位标题。"""
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if not text:
        return False
    if "、" in text and re.search(r"(相关)?讨论$", text):
        return True
    if len(text) <= 15 and re.search(r"[、]| 相关讨论|相关讨论$", text):
        return True
    return False


def _normalize_topics(topics: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统一模型和本地聚类输出，确保主题边界、标题和证据不能被模型改坏。

    主题边界仍来自可验证的消息簇（模型不能新增/拆分/合并主题，避免一条话题
    被换词重复列出）；但标题允许模型把本地“关键词+讨论”这类占位标题改成
    真正概括事件的名称，否则会出现“有人、睡觉、听到相关讨论”式的关键词罗列。
    """
    source = topics if isinstance(topics, list) and topics else fallback
    normalized: list[dict[str, Any]] = []
    limit = len(fallback) if fallback else len(source)
    for index in range(limit):
        raw = source[index] if index < len(source) and isinstance(source[index], dict) else {}
        base = fallback[index] if index < len(fallback) else {}
        item = dict(base) if base else dict(raw)
        item["keywords"] = base.get("keywords") or raw.get("keywords") or []
        item["samples"] = base.get("samples") or raw.get("samples") or []
        item["active_members"] = base.get("active_members") or raw.get("active_members") or []
        item["participants"] = base.get("participants") or item["active_members"]
        # 模型标题只在本地标题是“关键词堆砌”或本地无标题时采用，其余保留本地。
        local_title = _meaningful_topic_title(base.get("title") or raw.get("title"), item["keywords"], item["samples"])
        model_title = str(raw.get("title") or "").strip()
        if model_title and (not base.get("title") or _is_keyword_soup_title(local_title)):
            local_title = _meaningful_topic_title(model_title, item["keywords"], item["samples"])
        item["title"] = local_title
        # 模型只可提升摘要和观点表达；缺失、过短或空泛时继续使用本地证据摘要。
        if str(raw.get("summary") or "").strip():
            item["summary"] = raw["summary"]
        if str(raw.get("atri_view") or "").strip():
            item["atri_view"] = raw["atri_view"]
        existing_summary = str(item.get("summary") or "").strip()
        if len(existing_summary) < 35 or existing_summary in {"大家进行了讨论。", "群友聊了聊这个话题。"}:
            people_text = "、".join(str(x) for x in item["participants"][:4]) or "群友"
            evidence_text = str(item["samples"][0]).split("：", 1)[-1][:90] if item["samples"] else "暂无可展示原话"
            item["summary"] = (
                f"{people_text}围绕「{'、'.join(str(x.get('word') if isinstance(x, dict) else x) for x in item['keywords'][:4]) or item['title']}」"
                f"展开了 {int(item.get('message_count') or base.get('message_count') or 0)} 条消息的讨论。"
                f"从“{evidence_text}”可以确认，这里至少涉及具体信息交换或方案推进。"
            )
        view = str(item.get("atri_view") or "").strip()
        # 只要仍是数据分析/风控腔调，就换回亚托莉的第一人称印象，防止模板套话。
        item["atri_view"] = _evidence_based_topic_view(item) if _is_advisory_view(view) else view
        item.setdefault("evidence", item.get("samples", [])[:3])
        normalized.append(item)
    return normalized


def _topic_signal(message: dict[str, Any]) -> int:
    """给可概括的自然语言消息加权；表情、戳一戳和 ATRI 模板回复不能成为话题。"""
    content = str(message.get("content") or "").strip()
    if not content or re.fullmatch(r"(?:[@#]?群友|[\W_\d\s]+)", content):
        return 0
    if re.search(r"表情包/图片|动画表情|用户戳|QQ表情|^\[(?:语音|视频|文件)", content, re.I):
        return 0
    if len(content) < 8:
        return 0
    sender = str(message.get("nickname") or "").casefold()
    # 亚托莉连续的呆毛/签到/投喂模板用于互动统计，但不应被误判成“话题”。
    if ("atri" in sender or "亚托莉" in sender) and re.search(
        r"呆毛|红瞳|签到|好感度|高性能的仿生人|抢来吃掉|捏捏|摸摸头|叉腰", content
    ):
        return 0
    score = 1 + min(len(content) // 80, 3)
    score += 2 * int("?" in content or "？" in content)
    score += 2 * int(bool(re.search(r"https?://|链接|API|模型|DeepSeek|OpenSquilla", content, re.I)))
    score += int(bool(re.search(r"决定|结论|问题|建议|为什么|怎么|因为|但是|讨论|分享", content)))
    return score


def _topic_title_and_view(messages: list[dict[str, Any]], keywords: list[dict[str, Any]]) -> tuple[str, str]:
    """从证据消息生成“事件/问题”标题和有依据的亚托莉观点，而不是拼接关键词。"""
    text = " ".join(str(item.get("content") or "") for item in messages)
    priority_rules = (
        (r"error|api|sensitive|agent.{0,80}(处理|出错)|处理.{0,80}(error|api)", "AI 接口敏感内容报错与排查", "群友围绕 agent 处理报错、敏感内容拦截和 API 返回信息交换了排查线索。亚托莉建议把报错原文、触发消息类型和接口请求编号分开保存，再判断是内容安全限制还是调用参数问题。"),
        (r"主体|他者|黑格尔|世界.{0,30}(部分|解释)|存在", "主体、他者与世界关系讨论", "群友从主体、他者和世界的关系继续追问不同主体如何被理解，讨论重点是概念之间的逻辑边界，而不是单纯抛出术语。亚托莉觉得可以把各自的前提和结论分开写，后续更容易继续推演。"),
        (r"130cm|身高|搞错", "亚托莉身份记忆与称呼互动", "群友围绕身高梗、称呼和亚托莉是否记得成员身份展开互动，也借此观察上下文与记忆命中。亚托莉锐评：一次接住梗不等于长期记忆稳定，想验证时应把同一问题放在不同上下文里比较。"),
        (r"公主抱|给我发邮件|10s", "公主抱约定与角色互动", "群友围绕公主抱、约定时长和角色称呼继续玩梗，互动的重点是接住彼此的设定与回应。亚托莉觉得这类轻量话题适合保留为群聊氛围记录，不应被误写成实际承诺。"),
        (r"劣等.{0,30}模型|模型.{0,30}(冷淡|收费|拒绝)", "模型人格与互动边界讨论", "群友从模型是否冷淡、收费和回应方式聊到人与模型互动时的期待。亚托莉提醒把角色化表达、实际能力和服务限制区分开，避免把玩笑式设定误当成稳定功能。"),
        (r"房间|宕机|玩游戏", "亚托莉宕机与游戏日常互动", "群友围绕亚托莉宕机、个人房间和游戏安排展开轻量交流。亚托莉建议把实际故障排查与日常玩笑分开记录，避免把角色互动误判为系统异常。"),
        (r"Dear\s*Moments|remix|钢琴版|高音质", "《Dear Moments》音乐分享与翻唱", "音乐分享让群里的气氛变得很柔软；从 remix、钢琴版和搜索方式的来回确认看，大家是在交换具体作品信息，而不是只丢一句‘好听’。亚托莉觉得下次把作品链接和演唱版本一起记下，会更方便继续聊。"),
        (r"夏生.{0,30}(喜欢|恋人)|喜欢.{0,30}夏生", "夏生与亚托莉的感情选择", "群友把夏生等待、亚托莉的选择和水菜萌的处境放在一起讨论，重点是角色关系如何继续，而不是简单站队。亚托莉觉得可以保留不同解读，同时把原作设定和二次创作明确区分。"),
        (r"高风险|账号买卖|买家|出事一起承担", "高风险接单与账号安全提醒", "群里围绕‘钱多但要不要接’交换了风险判断，也提到账号买卖和出事后的责任问题。亚托莉锐评：‘高收益’不能替代可验证的授权、平台规则和退出方案；没有这些条件时，先拒绝比事后补救更稳妥。"),
        (r"OpenSquilla|免费token|tokenrhythm", "OpenSquilla 免费 token 邀请分享", "群友分享了 OpenSquilla 的限时邀请链接，重点是免费 token 和活动是否继续。亚托莉建议把邀请链接、有效期和使用条件分开核对，避免只看到‘免费’就忽略活动限制。"),
        (r"自己聊天|记得我是谁|忘了我是谁|考考你|又在和自己", "亚托莉记忆与自我对话测试", "群友连续测试亚托莉是否记得昵称、前文和自己的身份，过程中出现了‘又在和自己聊天’的观察。亚托莉锐评：记忆命中不等于真正理解，测试时最好同时记录原问题、上下文和回答是否一致。"),
    )
    # 固定主题词只在同一候选中反复出现时才生效。旧版只要一条消息提到歌名，
    # 就能把几千条无关聊天命名成音乐话题。
    priority_matches = [
        (len(re.findall(pattern, text, re.I)), title, view)
        for pattern, title, view in priority_rules
        if len(re.findall(pattern, text, re.I)) >= 2
    ]
    if priority_matches:
        _, title, view = max(priority_matches, key=lambda item: item[0])
        return title, view
    rules = (
        (r"Dear\s*Moments|remix|钢琴版|歌曲|音乐|高音质", "《Dear Moments》音乐分享与翻唱", "音乐分享让群里的气氛变得很柔软；从 remix、钢琴版和搜索方式的来回确认看，大家是在交换具体作品信息，而不是只丢一句“好听”。亚托莉觉得下次把作品链接和演唱版本一起记下，会更方便继续聊。"),
        (r"具身智能|存在主义|DeepSeek|情感锚定|算法", "具身智能与情感依恋的讨论", "这次讨论没有停在“模型有没有感情”的口号上，而是追问了算法陪伴、真实交流和情感投射之间的边界。亚托莉锐评：可以珍惜陪伴感，但不要把模型的回应误认为它拥有与人相同的责任和感受。"),
        (r"被封|封了|bot没启动|启动|正常显示|机器人", "ATRI 账号状态与机器人启动问题", "群友先发现亚托莉账号/机器人没有正常回应，随后从“是否被封、是否启动、主页能否显示”等现象逐项排查。亚托莉建议把异常时间、NapCat 状态和启动日志一起记录，下一次就能更快区分账号限制和进程未启动。"),
        (r"高风险|接这个单|账号买卖|买家|出事一起承担", "高风险接单与账号安全提醒", "群里围绕“钱多但要不要接”交换了风险判断，也提到账号买卖和出事后的责任问题。亚托莉锐评：‘高收益’不能替代可验证的授权、平台规则和退出方案；没有这些条件时，先拒绝比事后补救更稳妥。"),
        (r"炒锅|生锈|小苏打|白醋", "炒锅生锈的处理办法", "这是一个很具体的生活求助：群友询问炒锅生锈后怎么处理，讨论落在白醋/柠檬汁浸泡、小苏打和轻刷除锈等步骤。亚托莉提醒要先确认锅具材质，处理后彻底冲洗并擦干，避免把清洁建议用错地方。"),
        (r"夏生|收音机|船上|水菜萌|恋人", "夏生与船上生活设定的延伸讨论", "大家从夏生等待、船上的收音机和人物关系聊到作品设定与情感选择，既有剧情引用，也有对角色处境的再解释。亚托莉觉得这类话题最适合标记‘作品设定’与‘群友解读’，这样喜欢考据和喜欢二创的意见都不会混在一起。"),
        (r"便当|西瓜|拉面|草莓|螃蟹|好感度|吃什么", "群友投喂与亚托莉的美食互动", "这段对话围绕便当、水果、拉面和螃蟹等投喂内容展开，群友用食物图片和玩笑让亚托莉持续回应。亚托莉锐评：这不是信息讨论，而是一次很有参与感的群聊互动；把食物和回应记下来，就能看出大家最常用什么方式让群里热闹起来。"),
    )
    matched_rules = [
        (len(re.findall(pattern, text, re.I)), title, view)
        for pattern, title, view in rules
        if re.search(pattern, text, re.I)
    ]
    if matched_rules and max(item[0] for item in matched_rules) >= 2:
        _, title, view = max(matched_rules, key=lambda item: item[0])
        return title, view
    useful = [str(item.get("content") or "").replace("@群友", "").strip() for item in messages if _topic_signal(item)]
    words = [str(item.get("word") or "") for item in keywords if str(item.get("word") or "") not in _TOPIC_NOISE_WORDS]
    if words:
        title_words = words[:2] if len(words) >= 2 else words
        title = "、".join(title_words) + "相关讨论"
        return title, f"群里聊到「{'、'.join(words[:4])}」的时候，我也在旁边听着。"
    seed = max(useful, key=len) if useful else "群友围绕一段聊天内容交换了看法"
    seed = re.sub(r"\s+", " ", seed).strip("，。！？!? ")
    title = (seed[:22] + "…") if len(seed) > 22 else seed
    return f"{title}相关讨论", f"群里聊到“{seed[:55]}”的时候，我也在旁边听着。"


def _topic_evidence_pattern(title: str) -> str:
    """为固定主题挑选对应原话，避免用同一时间窗口里的无关长回复充当证据。"""
    mapping = {
        "《Dear Moments》音乐分享与翻唱": r"Dear|Moments|remix|钢琴|歌曲|音乐|高音质",
        "夏生与亚托莉的感情选择": r"夏生|喜欢|恋人|水菜萌|等待",
        "具身智能与情感依恋的讨论": r"具身|DeepSeek|情感|存在主义|算法|模型",
        "ATRI 账号状态与机器人启动问题": r"被封|封了|bot|启动|正常显示|机器人",
        "高风险接单与账号安全提醒": r"高风险|接这个单|账号买卖|买家|出事一起承担",
        "炒锅生锈的处理办法": r"炒锅|生锈|小苏打|白醋",
        "夏生与船上生活设定的延伸讨论": r"夏生|收音机|船上|水菜萌|恋人",
        "群友投喂与亚托莉的美食互动": r"便当|西瓜|拉面|草莓|螃蟹|好感度|吃什么",
    }
    return mapping.get(title, "")


def _topic_view_for_title(title: str, messages: list[dict[str, Any]], fallback: str) -> str:
    """按最终标题补齐锐评，避免重复窗口改名后沿用上一个话题的观点。"""
    text = " ".join(str(item.get("content") or "") for item in messages)
    views = {
        "群相册分享与图片交流": "群友先分享群相册和图片，再围绕图片内容、来源与后续整理方式展开交流。亚托莉锐评：这类话题的重点不是把链接堆在一起，而是留下清楚的相册主题、分享者和可回看的入口。",
        "账号买卖与高风险接单": "讨论从账号买卖和接单报价开始，逐步转到授权范围、平台规则以及出事后的责任承担。亚托莉锐评：没有可验证的授权和退出方案时，收益数字再漂亮也不能替代风险评估。",
        "高风险接单与账号安全提醒": "讨论从账号买卖和接单报价开始，逐步转到授权范围、平台规则以及出事后的责任承担。亚托莉锐评：没有可验证的授权和退出方案时，收益数字再漂亮也不能替代风险评估。",
        "亚托莉状态与群友互动": "群友一边测试亚托莉的记忆和回应，一边观察账号状态、启动情况与互动节奏。亚托莉锐评：一次答对只能说明当下上下文接上了，不能直接证明长期记忆或真正理解。",
        "群友与亚托莉的日常互动": "大家用表情、短句和连续回应把对话串起来，重点是互动如何被接住，而不是形成一个需要结论的知识问题。亚托莉锐评：这种轻量互动很有温度，但不要把玩笑式回应当成事实承诺。",
        "具身智能与情感依恋的讨论": "群友把 DeepSeek 对话经历、具身智能和情感投射放在一起比较，讨论从“模型有没有感情”推进到陪伴感与责任边界。亚托莉锐评：可以珍惜回应带来的陪伴感，但仍要把模型能力、人的投射和真实关系分开。",
    }
    if title in views:
        return views[title]
    # 这些标题已经由规则生成了具体观点，不要因为同一窗口顺带出现“情感/记忆”
    # 等词而被下面的兜底分支覆盖。
    if title in {
        "夏生与船上生活设定的延伸讨论", "夏生与亚托莉的感情选择",
        "ATRI 账号状态与机器人启动问题", "群友投喂与亚托莉的美食互动",
        "《Dear Moments》音乐分享与翻唱", "高风险接单与账号安全提醒",
        "炒锅生锈的处理办法", "OpenSquilla 免费 token 邀请分享",
        "亚托莉记忆与自我对话测试",
    }:
        return fallback
    if re.search(r"情感|空虚|自己聊天|记忆", text, re.I):
        return "群友从情感空虚、自我对话和记忆命中聊到模型陪伴的边界，讨论既有个人感受，也有对上下文连续性的实际观察。亚托莉锐评：陪伴感值得被认真对待，但判断模型是否“理解”仍要看连续、多轮且可复现的表现。"
    return fallback


def _topic_summary_text(title: str, people: str, count: int, evidence: str) -> str:
    """生成报告卡片里的完整叙事摘要。

    这里的 ``evidence`` 只作为内部抽取参数保留，不在用户看到的报告中展示
    “线索/证据”字样；摘要要回答“发生了什么、讨论如何推进、最后形成了什么
    判断”，避免只把关键词拼成一句话。
    """
    templates = {
        "《Dear Moments》音乐分享与翻唱": f"{people}围绕《Dear Moments》的高音质版本、remix 和钢琴版互相确认搜索方式，并比较不同演唱版本的听感。讨论从“怎么搜”延伸到作品在 ATRI 剧情里的情绪记忆，最后形成了先确认版本、再分享链接的交流习惯；本段共 {count} 条消息。",
        "夏生与亚托莉的感情选择": f"{people}把夏生等待、亚托莉的选择和水菜萌的处境放在一起讨论，重点是角色关系如何继续。群友一边引用剧情，一边加入自己的二次解读，分歧不在于是否喜欢角色，而在于怎样理解承诺、等待和记忆；本段共 {count} 条消息。",
        "具身智能与情感依恋的讨论": f"{people}从 DeepSeek 对话经历谈到具身智能是否能承载情感，进一步讨论算法陪伴、真实交流和情感投射的边界。讨论中既有个人体验，也有对模型记忆变化的观察，最后没有把“有回应”直接等同于“有情感”；本段共 {count} 条消息。",
        "ATRI 账号状态与机器人启动问题": f"{people}先发现 ATRI 没有正常回应，随后围绕是否被封、机器人是否启动、主页能否显示进行排查。讨论把账号限制与本地进程故障区分开，并指出应同时查看 NapCat 状态、启动日志和最近一次成功响应；本段共 {count} 条消息。",
        "高风险接单与账号安全提醒": f"{people}讨论了高收益订单是否值得接，并延伸到账号买卖、授权和出事后的责任。群友的分歧集中在收益是否足以覆盖风险，而不是单纯比较价格；没有明确授权和退出方案时，大家更倾向于先拒绝；本段共 {count} 条消息。",
        "炒锅生锈的处理办法": f"{people}围绕炒锅生锈的处理方法交换了白醋、小苏打和轻刷等建议，也提醒先确认锅具材质。话题最后落到去锈后要彻底冲洗并擦干，避免清洁剂残留或再次生锈；本段共 {count} 条消息。",
        "夏生与船上生活设定的延伸讨论": f"{people}从夏生、船上收音机和人物关系聊到作品设定与情感选择，既有剧情引用也有群友自己的解读。讨论把原作明确描写和群友推测分开，适合继续作为作品考据话题追踪；本段共 {count} 条消息。",
        "群友投喂与亚托莉的美食互动": f"{people}用便当、水果、拉面和螃蟹等内容持续投喂亚托莉，互动重点是食物图片、回应和好感度玩笑。这不是知识问答，而是一段围绕“投喂—回应—继续投喂”形成的群聊互动；本段共 {count} 条消息。",
        "OpenSquilla 免费 token 邀请分享": f"{people}分享了 OpenSquilla 的限时邀请链接，讨论集中在免费 token、活动有效期和使用条件。群友关注的不只是能不能免费使用，还包括链接来源、有效期和后续限制；本段共 {count} 条消息。",
        "亚托莉记忆与自我对话测试": f"{people}连续测试亚托莉是否记得昵称、前文和自己的身份，并讨论了“又在和自己聊天”的现象。话题实际涉及上下文连续性和记忆命中率，不能凭一次答对就判断模型真正理解；本段共 {count} 条消息。",
        "群相册分享与图片交流": f"{people}先分享群相册和图片，再围绕图片内容、来源、画质以及后续整理方式展开交流。讨论的实际进展是把零散图片集中到可回看的相册入口，而不是只在聊天里重复发送链接；本段共 {count} 条消息。",
        "账号买卖与高风险接单": f"{people}从账号买卖和接单报价谈到授权范围、平台规则与出事后的责任承担。群友的分歧集中在收益是否足以覆盖风险，最终更强调先核验来源、权限和退出方案；本段共 {count} 条消息。",
        "亚托莉状态与群友互动": f"{people}一边测试亚托莉是否记得前文和昵称，一边观察账号状态、启动情况与回应节奏。讨论把“当下接上上下文”和“长期记住成员”区分开，没有把一次答对直接当成模型具备稳定记忆；本段共 {count} 条消息。",
        "群友与亚托莉的日常互动": f"{people}用表情、短句和连续回应把对话串起来，内容以轻量互动和玩笑为主。这个话题的重点不是形成知识结论，而是观察群友如何接住亚托莉的回应、把气氛继续维持下去；本段共 {count} 条消息。",
        "具身智能与情感依恋的讨论": f"{people}把 DeepSeek 对话经历、具身智能和情感投射放在一起比较，讨论从“模型有没有感情”推进到算法陪伴与真实关系的边界。群友既分享个人体验，也讨论了如何用连续、多轮表现判断模型是否真的理解；本段共 {count} 条消息。",
    }
    evidence_tail = str(evidence or "").strip()[:64].rstrip("，。；、")
    text = templates.get(
        title,
        f"{people}聊起了「{title}」。从“{evidence_tail}”这样的原话能看出来，"
        "大家不是随口一说，而是认真在交换看法——有人补充背景，有人摆出不同意见，来回越聊越细。"
        "我在旁边听着，也想插一两句。",
    )
    # 去掉台账式的“本段共 N 条消息”结尾，避免总结读起来像流水账。
    return re.sub(r"[；;]?\s*本段共\s*\d+\s*条消息。?$", "", text)


_TOPIC_NOISE_WORDS = {
    "高性能", "机体", "呆毛", "红瞳", "小声", "微微", "轻轻", "哼哼", "脑袋",
    "眼睛", "手指", "身体", "可爱", "厉害", "一下", "一遍", "这样", "那个",
    "摸摸", "摸摸头", "姐姐", "最棒", "最最", "好感度", "主人", "大人", "鲸鱼",
    # 高频率但对“概括主题”无信息量的泛用词，避免拼成“有人、睡觉、听到相关讨论”。
    "有人", "睡觉", "听到", "觉得", "可能", "之类", "自己", "不会", "想到",
    "现在", "应该", "更好", "一点", "时候", "出来", "这种", "东西", "怎么",
    "为什么", "明白", "感觉", "真的", "但是", "就是", "其实", "还是", "然后",
}


def _topic_message_key(message: dict[str, Any]) -> str:
    return "|".join(
        (str(message.get("created_at") or ""), str(message.get("user_id") or ""), str(message.get("content") or ""))
    )


def _is_atri_message(message: dict[str, Any]) -> bool:
    name = str(message.get("nickname") or "").casefold()
    return "atri" in name or "亚托莉" in name


def _topic_keywords(messages: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """主题词优先来自真人的高信息消息，排除机器人动作描写等重复噪声。"""
    source = [item for item in messages if _topic_signal(item) and not _is_atri_message(item)]
    source = source or [item for item in messages if _topic_signal(item)]
    values = _keywords((str(item.get("content") or "") for item in source), limit * 3)
    return [item for item in values if str(item.get("word") or "") not in _TOPIC_NOISE_WORDS][:limit]


def _topic_terms(title: str, keywords: list[dict[str, Any]]) -> set[str]:
    words = {str(item.get("word") or "").lower() for item in keywords if str(item.get("word") or "")}
    words.update(word.lower() for word in _tokenize(title))
    return {word for word in words if word not in _TOPIC_NOISE_WORDS and word not in STOP_WORDS}


def _topic_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _split_topic_bursts(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """把过大的语义簇拆成短会话段，再由后续逻辑合并真正相同的话题。

    嵌入模型很容易把整天的“与机器人互动”判为相近；若直接把这个大簇当主题，
    会吞掉技术讨论、游戏、作品等实际事件。超过 40 条的簇按 15 分钟或 40 条切段，
    既保留对话上下文，也为之后基于关键词的合并提供足够细的粒度。
    """
    if len(messages) <= 40:
        return [messages] if messages else []
    ordered: list[tuple[datetime, dict[str, Any]]] = []
    for message in messages:
        try:
            timestamp = datetime.fromisoformat(str(message.get("created_at")))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            ordered.append((timestamp, message))
        except (TypeError, ValueError):
            continue
    ordered.sort(key=lambda item: item[0])
    bursts: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    started_at: datetime | None = None
    for timestamp, message in ordered:
        if current and (
            (started_at is not None and (timestamp - started_at).total_seconds() >= 15 * 60)
            or len(current) >= 40
        ):
            bursts.append(current)
            current = []
            started_at = None
        if started_at is None:
            started_at = timestamp
        current.append(message)
    if current:
        bursts.append(current)
    return bursts


def _topic_payload(
    chunks: list[dict[str, Any]], clusters: list[list[int]], *, max_topics: int = 8
) -> list[dict[str, Any]]:
    """从语义聚类结果生成互不重复、具备独立证据的话题。

    统计和时间线会覆盖全部消息；话题区只覆盖具备足够信息密度的语义簇。
    不能再按固定时间窗口切片，否则同一讨论跨半小时就会变成多个重复话题。
    """
    if not chunks:
        return []

    candidate_bursts: list[list[dict[str, Any]]] = []
    for raw_indices in clusters:
        indices = sorted({int(index) for index in raw_indices if 0 <= int(index) < len(chunks)})
        cluster_messages = [message for index in indices for message in chunks[index].get("messages", [])]
        # 机器人角色扮演长回复会显著拉高文本长度，并且常常混在真人讨论之间。
        # 它们可以留给“互动统计”，但不能作为主题语料，否则一个语义簇会被几千条
        # 模板回复膨胀并误命名。主题只用真人的、可概括的消息。
        messages = [item for item in cluster_messages if _topic_signal(item) and not _is_atri_message(item)]
        unique: dict[str, dict[str, Any]] = {_topic_message_key(item): item for item in messages}
        messages = list(unique.values())
        candidate_bursts.extend(_split_topic_bursts(messages))

    candidates: list[dict[str, Any]] = []
    for messages in candidate_bursts:
        signal = sum(_topic_signal(item) for item in messages)
        if signal < 4:
            continue
        keywords = _topic_keywords(messages)
        title, atri_view = _topic_title_and_view(messages, keywords)
        candidates.append(
            {
                "messages": messages,
                "keywords": keywords,
                "title": title,
                "atri_view": atri_view,
                "terms": _topic_terms(title, keywords),
                "score": signal * 3 + len(messages),
            }
        )

    # 对语义模型因措辞差异而分开的“同一事件”做二次合并。标题一致时必合并；
    # 否则要求至少两个共同主题词且 Jaccard 达标，避免把泛泛的“聊天”并在一起。
    merged: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (-int(item["score"]), -len(item["messages"]))):
        target = next(
            (
                item
                for item in merged
                if item["title"] == candidate["title"]
                or (
                    len(item["terms"] & candidate["terms"]) >= 2
                    and _topic_overlap(item["terms"], candidate["terms"]) >= 0.28
                )
            ),
            None,
        )
        if target is None:
            merged.append(dict(candidate))
            continue
        combined = {_topic_message_key(item): item for item in target["messages"]}
        combined.update({_topic_message_key(item): item for item in candidate["messages"]})
        target["messages"] = list(combined.values())
        target["keywords"] = _topic_keywords(target["messages"])
        target["title"], target["atri_view"] = _topic_title_and_view(target["messages"], target["keywords"])
        target["terms"] = _topic_terms(target["title"], target["keywords"])
        target["score"] = int(target["score"]) + int(candidate["score"])

    topics: list[dict[str, Any]] = []
    for candidate in sorted(merged, key=lambda item: (-int(item["score"]), -len(item["messages"])))[:max(1, max_topics)]:
        messages = candidate["messages"]
        names = _nickname_map(messages)
        meaningful = sorted(messages, key=_topic_signal, reverse=True)
        title = str(candidate["title"])
        evidence_pattern = _topic_evidence_pattern(title)
        evidence_messages = [
            message for message in meaningful
            if _topic_signal(message) and (not evidence_pattern or re.search(evidence_pattern, str(message.get("content") or ""), re.I))
        ]
        evidence_messages = evidence_messages or [message for message in meaningful if _topic_signal(message)]
        human_evidence = [message for message in evidence_messages if not _is_atri_message(message)]
        evidence_messages = (human_evidence or evidence_messages)[:5]
        samples = [
            f"{_display_name(message, names)}：{_visible_text(str(message.get('content') or '')[:220])}"
            for message in evidence_messages
        ]
        members = Counter(_display_name(message, names) for message in messages if _topic_signal(message))
        timestamps = [str(message.get("created_at") or "") for message in messages if message.get("created_at")]
        people = "、".join(name for name, _ in members.most_common(5)) or "群友"
        evidence_text = samples[0].split("：", 1)[-1][:120] if samples else "暂未找到可引用的文字原话"
        topics.append(
            {
                "title": title,
                "message_count": len(messages),
                "keywords": candidate["keywords"],
                "active_members": [name for name, _ in members.most_common(8)],
                "participants": [name for name, _ in members.most_common(8)],
                "samples": samples or ["暂未找到可引用的文字原话"],
                "evidence": samples[:3],
                "summary": _topic_summary_text(title, people, len(messages), evidence_text),
                "atri_view": _topic_view_for_title(title, messages, str(candidate["atri_view"])),
                "first_at": min(timestamps) if timestamps else "",
                "last_at": max(timestamps) if timestamps else "",
                "media": [media for message in messages for media in _message_media(message)][:8],
            }
        )
    # 规则标题可能在“重算标题”时收敛到同一名称；最后一道保护把同标题的
    # 证据和统计合并，确保报告不会再次出现两条同名主题。
    merged_topics: dict[str, dict[str, Any]] = {}
    for topic in topics:
        title = str(topic["title"])
        existing = merged_topics.get(title)
        if existing is None:
            merged_topics[title] = topic
            continue
        existing["message_count"] = int(existing.get("message_count") or 0) + int(topic.get("message_count") or 0)
        for field, limit in (("keywords", 10), ("samples", 5), ("evidence", 3), ("active_members", 8), ("participants", 8), ("media", 8)):
            values = list(existing.get(field) or []) + list(topic.get(field) or [])
            unique_values: list[Any] = []
            seen_values: set[str] = set()
            for value in values:
                marker = str(value)
                if marker not in seen_values:
                    unique_values.append(value)
                    seen_values.add(marker)
            existing[field] = unique_values[:limit]
        starts = [value for value in (existing.get("first_at"), topic.get("first_at")) if value]
        ends = [value for value in (existing.get("last_at"), topic.get("last_at")) if value]
        existing["first_at"] = min(starts) if starts else ""
        existing["last_at"] = max(ends) if ends else ""
        people = "、".join(existing.get("active_members", [])[:5]) or "群友"
        evidence = str((existing.get("samples") or [""])[0]).split("：", 1)[-1][:120]
        existing["summary"] = _topic_summary_text(title, people, int(existing["message_count"]), evidence)
    return sorted(merged_topics.values(), key=lambda item: -int(item["message_count"]))
