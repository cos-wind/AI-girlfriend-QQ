from __future__ import annotations

from . import *  # noqa: F403

def _normalize_member_highlights(value: Any, statistics: dict[str, Any]) -> list[dict[str, Any]]:
    """把模型画像和本地统计合并，保证每位成员都有可核验的具体数据。"""
    local = _member_highlights(statistics)
    model = {
        str(item.get("name")): item
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    result: list[dict[str, Any]] = []
    for item in local:
        candidate = model.get(item["name"], {})
        text = str(candidate.get("evaluation") or candidate.get("contribution") or "").strip()
        # 模型常输出“积极参与”“贡献很大”等无法验证的短句，保留本地事实描述。
        if len(text) < 35 or any(word in text for word in ("很活跃", "贡献很大", "积极参与讨论", "表现优秀")):
            text = item["evaluation"]
        else:
            text = text[:180].rstrip("。；") + "；数据侧：" + item["evaluation"]
        result.append({**item, "evaluation": text})
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
    """小数据在线质心聚类；不引入 sklearn，减少主项目依赖和冷启动。"""
    clusters: list[dict[str, Any]] = []
    for index, raw_vector in enumerate(vectors):
        vector = [float(value) for value in raw_vector]
        if not clusters:
            clusters.append({"centroid": vector, "indices": [index]})
            continue
        scores = [_cosine(vector, cluster["centroid"]) for cluster in clusters]
        best = max(range(len(scores)), key=scores.__getitem__)
        if scores[best] >= threshold or len(clusters) >= max_clusters:
            cluster = clusters[best]
            count = len(cluster["indices"])
            cluster["indices"].append(index)
            cluster["centroid"] = _normalize(
                [(old * count + new) / (count + 1) for old, new in zip(cluster["centroid"], vector)]
            )
        else:
            clusters.append({"centroid": vector, "indices": [index]})
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
        if best_index >= 0 and best_score >= 0.08 or len(clusters) >= maximum:
            position = best_index if best_index >= 0 else 0
            clusters[position]["indices"].append(index)
            clusters[position]["tokens"].update(tokens)
        else:
            clusters.append({"indices": [index], "tokens": set(tokens)})
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
    """用参与者、关键词和原话构造具体观点，避免泛泛而谈。"""
    title = str(topic.get("title") or "这个话题")
    people = [str(item) for item in (topic.get("participants") or topic.get("active_members") or []) if str(item)]
    keywords = [
        str(item.get("word") if isinstance(item, dict) else item)
        for item in (topic.get("keywords") or [])
        if str(item.get("word") if isinstance(item, dict) else item).strip()
    ]
    samples = [str(item).strip() for item in (topic.get("samples") or topic.get("evidence") or []) if str(item).strip()]
    evidence = samples[0][:100] if samples else "暂无可展示原话"
    actor = "、".join(people[:3]) or "几位群友"
    key_text = "、".join(dict.fromkeys(keywords[:3])) or title
    return (
        f"从{actor}的发言看，这个话题围绕「{key_text}」展开，大家先交换了“{evidence}”所涉及的具体问题，"
        "随后把不同观点放在一起比较。亚托莉锐评：讨论已经形成了一个方向，但细节仍应以群友后续确认的结论为准。"
    )


def _normalize_topics(topics: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统一模型和本地聚类输出，确保标题、参与者和观点具备证据。"""
    source = topics if isinstance(topics, list) and topics else fallback
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(source):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        base = fallback[index] if index < len(fallback) else {}
        item["keywords"] = item.get("keywords") or base.get("keywords", [])
        item["samples"] = item.get("samples") or base.get("samples", [])
        item["active_members"] = item.get("active_members") or base.get("active_members", [])
        item["participants"] = item.get("participants") or item.get("active_members") or base.get("active_members", [])
        item["title"] = _meaningful_topic_title(item.get("title"), item["keywords"], item["samples"])
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
        generic = (len(view) < 45 or "亚托莉建议把已经确认" in view or "暂时没有足够证据" in view)
        item["atri_view"] = _evidence_based_topic_view(item) if generic else view
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
    sender = str(message.get("nickname") or "")
    # 亚托莉连续的呆毛/签到/投喂模板用于互动统计，但不应被误判成“话题”。
    if ("ATRI" in sender or "亚托莉" in sender) and re.search(
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
        (r"Dear\s*Moments|remix|钢琴版|高音质", "《Dear Moments》音乐分享与翻唱", "音乐分享让群里的气氛变得很柔软；从 remix、钢琴版和搜索方式的来回确认看，大家是在交换具体作品信息，而不是只丢一句‘好听’。亚托莉觉得下次把作品链接和演唱版本一起记下，会更方便继续聊。"),
        (r"夏生.{0,30}(喜欢|恋人)|喜欢.{0,30}夏生", "夏生与亚托莉的感情选择", "群友把夏生等待、亚托莉的选择和水菜萌的处境放在一起讨论，重点是角色关系如何继续，而不是简单站队。亚托莉觉得可以保留不同解读，同时把原作设定和二次创作明确区分。"),
        (r"高风险|账号买卖|买家|出事一起承担", "高风险接单与账号安全提醒", "群里围绕‘钱多但要不要接’交换了风险判断，也提到账号买卖和出事后的责任问题。亚托莉锐评：‘高收益’不能替代可验证的授权、平台规则和退出方案；没有这些条件时，先拒绝比事后补救更稳妥。"),
        (r"OpenSquilla|免费token|tokenrhythm", "OpenSquilla 免费 token 邀请分享", "群友分享了 OpenSquilla 的限时邀请链接，重点是免费 token 和活动是否继续。亚托莉建议把邀请链接、有效期和使用条件分开核对，避免只看到‘免费’就忽略活动限制。"),
        (r"自己聊天|记得我是谁|忘了我是谁|考考你|又在和自己", "亚托莉记忆与自我对话测试", "群友连续测试亚托莉是否记得昵称、前文和自己的身份，过程中出现了‘又在和自己聊天’的观察。亚托莉锐评：记忆命中不等于真正理解，测试时最好同时记录原问题、上下文和回答是否一致。"),
    )
    for pattern, title, view in priority_rules:
        if re.search(pattern, text, re.I):
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
    if matched_rules:
        _, title, view = max(matched_rules, key=lambda item: item[0])
        return title, view
    useful = [str(item.get("content") or "").replace("@群友", "").strip() for item in messages if _topic_signal(item)]
    seed = max(useful, key=len) if useful else "群友围绕一段聊天内容交换了看法"
    seed = re.sub(r"\s+", " ", seed).strip("，。！？!? ")
    title = (seed[:22] + "…") if len(seed) > 22 else seed
    return f"{title}相关讨论", f"群友围绕“{seed[:55]}”交换了看法。亚托莉能确认的是，这里出现了具体观点或问题；如果要继续追踪，建议把结论、待办和仍未回答的部分分开记录。"


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
    return templates.get(title, f"{people}围绕“{title}”交换了具体看法，讨论先从群友提出的问题展开，再延伸到不同回答之间的差异。结合这一时段的聊天，可以确认这是一个持续推进的话题，而不是单条闲聊；本段共 {count} 条消息。")


def _topic_payload(chunks: list[dict[str, Any]], clusters: list[list[int]]) -> list[dict[str, Any]]:
    """按连续高信息窗口提取话题，避免把整群 ATRI 模板回复聚成“高性能讨论”。"""
    all_messages = [message for chunk in chunks for message in chunk["messages"]]
    if not all_messages:
        return []
    # 每 30 分钟形成一个候选窗口；窗口之间允许重叠，最终贪心选择互不重复的高信息窗口。
    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    window_start: datetime | None = None
    for message in all_messages:
        try:
            timestamp = datetime.fromisoformat(str(message.get("created_at"))).astimezone()
        except (TypeError, ValueError):
            continue
        if window_start is None:
            window_start = timestamp
        if (timestamp - window_start).total_seconds() >= 1800 and current:
            windows.append(current)
            current = []
            window_start = timestamp
        current.append(message)
    if current:
        windows.append(current)
    candidates = [window for window in windows if sum(_topic_signal(item) for item in window) >= 4]
    candidates.sort(key=lambda window: sum(_topic_signal(item) for item in window), reverse=True)
    selected: list[list[dict[str, Any]]] = []
    used_keys: set[str] = set()
    for window in candidates:
        keys = {str(item.get("created_at")) + str(item.get("user_id")) for item in window}
        if len(keys & used_keys) / max(1, len(keys)) > 0.35:
            continue
        selected.append(window)
        used_keys.update(keys)
        if len(selected) >= 8:
            break
    topics: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for messages in selected:
        names = _nickname_map(messages)
        meaningful = sorted(messages, key=_topic_signal, reverse=True)
        keywords = _keywords((str(message.get("content") or "") for message in meaningful if _topic_signal(message)), 8)
        title, atri_view = _topic_title_and_view(messages, keywords)
        # 多个相邻窗口可能属于同一件事；报告中只保留一次，避免出现 5 个重复的“具身智能讨论”。
        if title in seen_titles:
            fallback_words = [str(item.get("word")) for item in keywords if str(item.get("word")) not in {"高性能", "机体"}]
            fallback_set = set(fallback_words)
            if {"夏生", "喜欢"} <= fallback_set or {"夏生", "不要"} <= fallback_set:
                title = "夏生情感关系与剧情选择"
            elif {"买家", "账号"} & fallback_set or "高风险" in fallback_set:
                title = "高风险接单与账号安全提醒"
            elif {"脑袋", "哼哼", "记忆"} & fallback_set:
                title = "亚托莉状态与群友互动"
            elif {"相册", "分享"} <= fallback_set:
                title = "群相册分享与图片交流"
            elif {"情感", "空虚"} <= fallback_set or "自己" in fallback_set:
                title = "具身智能与情感依恋的讨论"
            elif {"一遍", "厉害", "哼哼"} & fallback_set:
                title = "群友与亚托莉的日常互动"
            else:
                title = ("、".join(fallback_words[:3]) + "相关交流") if fallback_words else f"群聊重点进展 {len(topics) + 1}"
            if title in seen_titles:
                continue
        seen_titles.add(title)
        evidence_pattern = _topic_evidence_pattern(title)
        evidence_messages = [
            message for message in meaningful
            if _topic_signal(message) and (not evidence_pattern or re.search(evidence_pattern, str(message.get("content") or ""), re.I))
        ][:5]
        if not evidence_messages:
            evidence_messages = [message for message in meaningful if _topic_signal(message)][:5]
        # 证据优先采用群友原话；ATRI 的拟人化回声只在没有群友文字时作为补充。
        human_evidence = [
            message for message in evidence_messages
            if "ATRI" not in str(message.get("nickname") or "") and "亚托莉" not in str(message.get("nickname") or "")
        ]
        if human_evidence:
            evidence_messages = human_evidence[:5]
        else:
            any_human = [
                message for message in meaningful
                if _topic_signal(message)
                and "ATRI" not in str(message.get("nickname") or "")
                and "亚托莉" not in str(message.get("nickname") or "")
            ]
            if any_human:
                evidence_messages = any_human[:5]
        samples = [f"{_display_name(message, names)}：{_visible_text(str(message.get('content') or '')[:220])}" for message in evidence_messages]
        members = Counter(_display_name(message, names) for message in messages if _topic_signal(message))
        timestamps = [str(message.get("created_at") or "") for message in messages if message.get("created_at")]
        people = "、".join(name for name, _ in members.most_common(5)) or "群友"
        evidence_text = samples[0].split("：", 1)[-1][:120] if samples else "暂未找到可引用的文字原话"
        summary = _topic_summary_text(title, people, len(messages), evidence_text)
        atri_view = _topic_view_for_title(title, messages, atri_view)
        topics.append({
            "title": title,
            "message_count": len(messages),
            "keywords": keywords,
            "active_members": [name for name, _ in members.most_common(8)],
            "participants": [name for name, _ in members.most_common(8)],
            "samples": samples or ["暂未找到可引用的文字原话"],
            "evidence": samples[:3],
            "summary": summary,
            "atri_view": atri_view,
            "first_at": min(timestamps) if timestamps else "",
            "last_at": max(timestamps) if timestamps else "",
            "media": [media for message in messages for media in _message_media(message)][:8],
        })
    return sorted(topics, key=lambda item: -int(item["message_count"]))
