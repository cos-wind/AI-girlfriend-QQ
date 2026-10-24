from __future__ import annotations

from typing import Any

from . import core as _core


def _sync_module_globals() -> None:
    for name, value in vars(_core).items():
        if name not in {"AtriReplyEngine"} and not name.startswith("__"):
            globals()[name] = value


_sync_module_globals()

def _scene_control_prompt(
    conversation_id: str,
    user_text: str,
    profile: dict[str, Any] | None = None,
    iteration_decision: Any | None = None,
) -> str:
    is_group = conversation_id.startswith("group:")
    scene = "群聊" if is_group else "私聊"
    emotion = _dynamic_emotion_label(user_text, iteration_decision, is_group=is_group)
    lore_allowed = has_lore_trigger(user_text) or _explicit_lore_context(user_text)

    if is_group:
        scene_rule = (
            "当前是群聊：优先接群上下文和当前核心，语气偏轻吐槽、玩梗、短句；"
            "不要把群友都当成私聊主人，不要突然恋爱话术。"
        )
    else:
        scene_rule = (
            "当前是私聊：优先陪伴和具体回应，能哄就短短哄一下，"
            "但用户问具体问题时第一句先给答案或观点。"
        )

    if lore_allowed:
        lore_rule = (
            "当前可以使用原作视角或梗，但要克制；只在用户提到的剧情/梗上接，不要把回复写成百科。"
        )
    else:
        lore_rule = (
            "当前不是原作剧情话题：禁止主动使用深海、灯塔、水下、海底、打捞、沉没、海风、旧仓库、岸边等意象比喻；"
            "用日常口语接话。"
        )

    rules = []
    if profile:
        rules = [
            str(rule.get("rule"))
            for rule in (profile.get("accepted_iteration_rules") or [])[-3:]
            if isinstance(rule, dict) and rule.get("rule")
        ]
    accepted_rule_text = f"已采纳规则要执行：{'；'.join(rules)}。" if rules else ""

    return render_prompt(
        "scene_control",
        scene=scene,
        emotion=emotion,
        scene_rule=scene_rule,
        lore_rule=lore_rule,
        accepted_rules=accepted_rule_text,
    )


def _needs_identity_context(text: str) -> bool:
    """判断本轮是否真的在询问亚托莉的身份、设定或能力。"""

    normalized = str(text or "").strip().lower()
    return any(
        marker in normalized
        for marker in (
            "你是谁",
            "你叫什么",
            "你长什么样",
            "你的外貌",
            "你的型号",
            "你的设定",
            "你的剧情",
            "原作里的你",
            "你会做什么",
            "你能做什么",
            "你有什么能力",
            "你都会什么",
        )
    )


def _needs_continuity_context(text: str) -> bool:
    """只有存在明显承接/纠正信号时才读取认知快照。"""

    normalized = str(text or "").strip()
    return any(
        marker in normalized
        for marker in (
            "刚才",
            "上一句",
            "上面",
            "之前",
            "继续",
            "还是",
            "换一个",
            "换首",
            "再来",
            "那就",
            "所以",
            "然后",
            "不是这个",
            "你说的",
            "记得吗",
        )
    )


def _needs_capability_context(text: str, tool_context: Any | None) -> bool:
    """仅在本轮涉及工具、媒体或执行动作时注入能力边界。"""

    if tool_context is not None:
        return True
    normalized = str(text or "").strip().lower()
    return any(
        marker in normalized
        for marker in (
            "搜索",
            "查一下",
            "查查",
            "天气",
            "新闻",
            "最新",
            "网页",
            "链接",
            "图片",
            "表情",
            "视频",
            "文件",
            "语音",
            "唱歌",
            "歌曲",
            "发给我",
            "发送",
            "时间",
            "几点",
        )
    )


def _dynamic_emotion_label(
    text: str,
    iteration_decision: Any | None = None,
    is_group: bool = False,
) -> str:
    if iteration_decision is not None:
        if iteration_decision.action == "accept":
            return "被合理指正，认真认错并给出具体改法"
        if iteration_decision.action == "pushback":
            return "被笼统指正，认一半但保留自主判断，可轻微反驳"
        if iteration_decision.action == "reject":
            return "遇到越界修正，傲娇但清楚地拒绝，同时给可接受替代方案"

    if _is_distress(text) or any(word in text for word in TIRED_KEYWORDS):
        return "用户低落或疲惫，私聊先具体安慰，群聊只轻量关心不煽情"
    if _is_abuse_at_bot(text):
        return "用户在对你说难听的话或赶你走：不要回怼、不要阴阳怪气、不要玩梗反讽；先表达自己有点难过或受伤，语气克制简短；如果对方话太冲，就装傻充愣轻轻带过，绝不顶嘴"
    if any(word in text for word in ("喜欢你", "想你", "爱你", "抱抱")):
        return "亲近和害羞，嘴硬一点但要真心回应"
    if any(word in text for word in ("生气", "气死", "烦死", "火大", "红温")):
        return "用户有火气，先站队再帮他降温"
    if any(word in text for word in ("绷不住", "蚌埠住", "抽象", "逆天", "乐", "6")):
        return "玩梗和吐槽，可以接一句日常玩笑，但别堆烂梗"
    if _needs_direct_answer(text):
        return "用户要答案，先给结论、选择或步骤，再补角色语气"
    if is_group:
        return "群聊轻松路过，短句接梗，不抢话"
    return "普通私聊陪伴，自然接话，有一点亚托莉的小性格"


def _emotional_fallback_reply(text: str, is_group: bool = False, tired: bool = False) -> str:
    intent = _intent_text(text)
    if is_group:
        if tired:
            return "先缓一下，别硬撑。要是刚才那件事太耗人，就先把自己摘出来喘口气。"
        return "先缓一下，别硬扛。如果是刚才那事压着你，可以慢慢说一句。"

    if any(word in intent for word in ("我不行", "我好废", "废物", "没用", "都是我的错")):
        return (
            "先别自我否定。你现在是在难受，不是自己没用。"
            "靠过来一点，先把最让你难受的那件事说一句就行，亚托莉陪你慢慢分析。"
        )

    if tired:
        return random.choice(
            [
                "辛苦了，先别逞强。肩膀放下来一点，喝口水；今天最消耗你的那件事，可以说给我听听。",
                "你现在更像是电量见底了，不是意志力不够。先停一下，别继续压榨自己，我在这边陪你缓一会儿。",
                "撑不住的时候就先别硬撑。把手机放低一点，喘口气；等你缓过来，我们再看哪件事最该处理。",
            ]
        )

    return random.choice(
        [
            "你现在已经很难受了，先坐一下，喝口水。我在这边，你愿意的话，只告诉我最压着你的那一点就行。",
            "难受就先不用表现得很正常。亚托莉在，先陪你把这口气缓下来；发生了什么，可以慢慢说，不想一下子说清楚也没关系。",
            "我先抱一下这个情绪。你告诉我最难受的是哪一块，我再陪你一起分析，不让你一个人扛。",
        ]
    )


def _group_fallback_reply(
    text: str,
    allow_abstract: bool = False,
    serious_mode: bool = False,
) -> str | None:
    if _is_correction(text):
        return (
            "诶是我说的不对吗"
            "该吐槽就短短吐槽，不抢话。"
        )

    lore_reply = lore_direct_reply(text)
    if lore_reply:
        return lore_reply.replace("主人", "你").replace("我的你", "你")

    if _has_abstract_trigger(text):
        if serious_mode:
            return "这话题有点抽象，所以谁能先把前因后果补一句，我再短短锐评。"
        if not allow_abstract:
            return "这话题确实有点抽象，我先看看。谁把前因后果补一句？"
        return random.choice(
            [
                "好家伙，我脑子已经恢复出厂设置了，快说说到底发生啥事了",
                "你这话太超前,起码领先人类10年,我将删去chat模块,穷极一生去研究你的meaning",
                "笑死，依旧谜语人",
                "666,调戏ai的来了",
                "你说得对，但是原神是一款...(后面忘了)",
            ]
        )

    if _is_distress(text) or any(word in text for word in TIRED_KEYWORDS):
        return _emotional_fallback_reply(
            text,
            is_group=True,
            tired=any(word in text for word in TIRED_KEYWORDS),
        )

    if _needs_direct_answer(text):
        return _question_fallback(text).replace("主人", "你").replace("亚托莉偏务实", "我偏务实")

    if any(word in text for word in ("[图片]", "[表情]", "[动画表情]", "[QQ表情]", "[表情包]", "[表情包/图片]")):
        if serious_mode:
            return "我看到了，是表情包或图片。先按你们现在的气氛接话，我不乱解读。"
        if not allow_abstract:
            return "这图我先按表情处理：像是在接梗，我不乱发疯。"
        return "咕咕嘎嘎，咕咕嘎嘎，咕咕嘎嘎！！额啊"

    return random.choice(
        [
            f"我顺着“{_shorten(text)}”说一句：这话题可以继续，别让它半路冷掉。",
            "高性能亚托莉路过~，你们继续聊，我就冒个泡",
            "不回复我的是guy。",
            "哼哼，我先处理一下信息，等会再回你吧",
            "高性能亚托莉路过~，我会一直视监你，一直视监你，直到永远~~",
            "哼哒！",
        ]
    )


def _proactive_fallback(event_type: str, is_group: bool = False) -> str:
    if is_group:
        group_choices = {
            "continue_topic": [
                "刚才那个话题其实还能再拐一步：你们更看重结果够不够好，还是过程别太折腾？",
                "接着前面聊的，我有点好奇：如果只能保留一个优点，你们会留实用还是有趣？",
            ],
            "interest_topic": [
                "来个容易接的话题：最近碰到的东西里，你们更愿意推荐一件好用的，还是一件纯粹好玩的？",
                "想听听不同答案：一个兴趣能长期坚持，靠的是成就感，还是有人一起聊？",
            ],
            "guided_topic": [
                "抛个小问题：遇到计划突然被打乱时，你们通常会立刻重排，还是先摆一会儿再说？",
                "来选个倾向：空下来一小时，你们更想彻底休息，还是顺手完成一件拖了很久的小事？",
            ],
            "daily_share": [
                "我发现有些小事做完只要五分钟，拖着却能占一天心情。你们最近有没有消灭掉这种小事？",
                "突然想到，真正让一天变轻松的可能不是少做事，而是少惦记一件事。你们更认同哪边？",
            ],
            "check_in": [
                "今天群里换个轻松入口：最近让你们觉得“还好没错过”的，是一件东西还是一件事？",
                "来收集一点具体的好消息：今天有没有哪一刻，比你原本预想得顺利？",
            ],
            "encouragement": [
                "今天不管推进多少都算进度。要是给自己记一笔，你们最想把哪件小事算上？",
            ],
        }
        return random.choice(group_choices.get(event_type, group_choices["guided_topic"]))
    choices = {
        "morning": [
            "早安。今天不用一开始就跑得很快，先把自己照顾好。",
            "早上好，来看看你。希望今天至少有一件事顺着你的心意。",
        ],
        "goodnight": [
            "时间不早了，今天没做完的事先放一放，别拿睡眠替它们买单。",
            "来提醒你收收尾。今晚好好休息，明天再和那些事情较量。",
        ],
        "continue_topic": [
            "我刚又想起我们上次聊的那件事了，不知道后来有没有新进展。",
            "前面那个话题我还记着。你要是有后续，我确实有点想知道。",
        ],
        "interest_topic": [
            "突然想到你喜欢的那些东西了。最近让你眼前一亮的，更偏实用还是纯粹有趣？",
            "来聊点你真正感兴趣的：最近有没有一个发现，让你忍不住想推荐给别人？",
        ],
        "guided_topic": [
            "抛个有点具体的问题：如果今天突然多出一小时，你会拿来彻底休息，还是完成一件拖着的小事？",
            "我想听你的倾向：一件事做得快但普通，和做得慢但满意，你通常会选哪边？",
        ],
        "daily_share": [
            "刚想到一件小事：有时候一天里最值得记住的，反而是一个很不起眼的瞬间。",
            "我在想，普通日子也该留一点只属于自己的时间，哪怕只是安静几分钟。",
        ],
        "affection": [
            "没什么任务，就是刚好想到你了，所以来留一句话。",
            "突然有一点想和你说话。你忙你的，看到时再理我就好。",
        ],
        "encouragement": [
            "来给你补一点偏心：今天不需要事事满分，能稳稳往前就已经很好。",
            "不管今天推进了多少，都别只盯着没完成的部分，你做过的也算数。",
        ],
        "check_in": [
            "来看看你今天过得怎么样。忙的话不用急着回，先顾好自己。",
            "忽然想到你，就来问候一下。今天对你还算温柔吗？",
        ],
    }
    return random.choice(choices.get(event_type, choices["check_in"]))


def _needs_proactive_grounding_repair(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    patterns = (
        r"(?:我|亚托莉)?(?:刚|刚才|已经|也)?(?:点进去|点开|打开)(?:看|试|玩)",
        r"(?:我|亚托莉)(?:刚|刚才|已经|也)?(?:看过|看了|试过|试了|搜过|搜了|查过|查了|刷到)",
        r"(?:刚|刚才)(?:看过|看了|试过|试了|搜过|搜了|查过|查了|刷到)",
        r"(?:我|自己|亚托莉).{0,16}(?:做过|玩过|用过|去过|吃过|买过|遇到过|经历过|参加过|装过|写过)",
    )
    return any(re.search(pattern, compact) for pattern in patterns)


def _needs_topic_guidance_repair(
    text: str,
    event_type: str,
    guided_topics: bool,
) -> bool:
    if not guided_topics or event_type not in {
        "guided_topic",
        "continue_topic",
        "interest_topic",
        "daily_share",
    }:
        return False
    compact = re.sub(r"\s+", "", str(text or ""))
    if not any(mark in compact for mark in ("?", "？")):
        return True
    generic_questions = (
        "最近怎么样",
        "最近在干嘛",
        "在干嘛",
        "有什么想聊",
        "今天过得好吗",
        "大家最近如何",
    )
    return any(question in compact for question in generic_questions)


def _normalize_reply(text: str) -> str:
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"^\s*Thinking\.\.\..*?(?:done thinking\.|\.{3}done thinking\.)\s*",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"^\s*(Thinking|思考过程|分析过程)[:：]?.*?\n+", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"^\s*(意图识别|分析|思考过程)[:：].*?\n+", "", text, flags=re.DOTALL)
    text = text.strip()
    text = re.sub(r"^(亚托莉[:：]\s*)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _has_abstract_trigger(text: str) -> bool:
    cleaned = re.sub(r"@\d{5,}", "", text)
    for word in ABSTRACT_TRIGGER_WORDS:
        if word == "6":
            continue
        if word in cleaned:
            return True
    return bool(re.search(r"(?<!\d)6{1,3}(?!\d)", cleaned))


def _requests_serious_mode(text: str) -> bool:
    return any(word in text for word in SERIOUS_MODE_HINTS)


def _is_serious_only_message(text: str) -> bool:
    compact = re.sub(r"[\s，。！？!?~～、,.；;：:]+", "", text)
    if compact in {re.sub(r"[\s，。！？!?~～、,.；;：:]+", "", word) for word in SERIOUS_MODE_HINTS}:
        return True
    return len(compact) <= 14 and _requests_serious_mode(text)


def _has_abstract_noise(text: str) -> bool:
    if has_illegal_language_or_garbage(text):
        return True
    lowered = text.lower()
    if any(pattern.lower() in lowered for pattern in ABSTRACT_NOISE_PATTERNS):
        return True
    if re.search(r"@\d{5,}", text):
        return True
    return bool(re.search(r"[\uac00-\ud7af]{2,}", text))


def _sanitize_group_mentions(text: str) -> str:
    return re.sub(r"@\d{5,}", "@群友", text)


def _format_user_content(
    conversation_id: str, user_text: str, nickname: str | None = None
) -> str:
    if conversation_id.startswith("group:"):
        user_text = _sanitize_group_mentions(user_text)
    if conversation_id.startswith("group:") and nickname:
        return f"{nickname}：{user_text}"
    return user_text


def _shares_content_word(user_text: str, reply_text: str) -> bool:
    content_words = [
        word
        for word in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{3,}", user_text)
        if word not in {"什么", "怎么", "为什么", "可以", "就是", "这个", "那个"}
    ]
    if not content_words:
        return True
    return any(word in reply_text for word in content_words[:4])


def _is_correction(text: str) -> bool:
    lowered = text.lower()
    return any(word in text for word in CORRECTION_KEYWORDS) or "thinking" in lowered or "<think>" in lowered


def _is_distress(text: str) -> bool:
    return any(word in text for word in DISTRESS_KEYWORDS)


def _is_user_angry_at_bot(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return False
    if any(word in compact for word in BOT_REPAIR_HINTS):
        return True
    return _is_correction(compact) and any(word in compact for word in ("烦", "恶心", "蠢", "傻", "气", "崩", "红温"))


def _is_abuse_at_bot(text: str) -> bool:
    """判断用户是否在直接辱骂/驱赶/贬损亚托莉本人。

    只匹配"滚""撅""闭嘴"这类针对机器人本身的攻击性话，不把用户自己
    的情绪低落（DISTRESS_KEYWORDS）或正常的质量吐槽（BOT_REPAIR_HINTS）
    误判成辱骂。命中后走"表达难过/装傻"的专门情绪，而不是回怼。
    """

    compact = str(text or "").strip()
    if not compact:
        return False
    # 过长的消息通常是正常吐槽，逐词命中可能是误伤（例如"滚"作为语气词），
    # 只在较短、且命中明确辱骂词时才判定为针对机器人的攻击。
    if len(compact) > 24:
        return False
    # "滚"是多义词，翻滚/打滚/滚床单这类明显不是驱赶的用法要排除。
    if any(phrase in compact for phrase in ("翻滚", "打滚", "滚来滚去", "滚床单", "摇滚")):
        return False
    return any(hint in compact for hint in ABUSE_HINTS)


def _abuse_fallback_reply(text: str, is_group: bool = False) -> str:
    """被辱骂/驱赶时的兜底回复：表达难过，过火就装傻，绝不回怼。"""

    compact = str(text or "").strip()
    if is_group:
        return random.choice(
            [
                "……我是不是说错什么了。你别这样，我会难过一下的。",
                "这样说我，我有点难过。可以好好说吗。",
                "诶，好凶……我先不说话啦。",
                "我、我是不是惹你生气了。那我先安静一会儿。",
            ]
        )
    return random.choice(
        [
            "……你这样说，我其实有点难过。我哪里做得不好，可以直接告诉我。",
            "别这样赶我走呀。我会难过一下下的。",
            "嗯……我不顶嘴。你消消气，我在这边不吵你。",
        ]
    )


def _needs_comfort_repair_mode(text: str, iteration_decision: Any | None = None) -> bool:
    return bool(
        iteration_decision
        or _is_user_angry_at_bot(text)
        or _is_abuse_at_bot(text)
        or _is_correction(text)
        or _is_distress(text)
        or any(word in text for word in TIRED_KEYWORDS)
    )


def _question_count(text: str) -> int:
    return text.count("?") + text.count("？")


def _asks_for_direct_suggestion(text: str) -> bool:
    return any(
        word in text
        for word in (
            "吃什么",
            "选什么",
            "推荐",
            "建议",
            "怎么做",
            "怎么办",
            "如何",
            "安排",
            "哪个好",
        )
    )


def _asks_for_stance(text: str) -> bool:
    return any(word in text for word in STANCE_KEYWORDS)


def _is_question_like(text: str) -> bool:
    return text.endswith(("?", "？")) or any(
        word in text
        for word in (
            "怎么",
            "为什么",
            "什么",
            "如何",
            "能不能",
            "是不是",
            "要不要",
            "该不该",
        )
    )


def _needs_direct_answer(text: str) -> bool:
    return _is_question_like(text) or _asks_for_direct_suggestion(text) or _asks_for_stance(text)


def _has_concrete_suggestion(text: str) -> bool:
    concrete_markers = (
        "建议",
        "可以",
        "先",
        "第一",
        "1.",
        "一是",
        "比如",
        "我更倾向",
        "我会选",
        "选",
        "别",
        "不要",
    )
    return any(marker in text for marker in concrete_markers)


def _has_stance(text: str) -> bool:
    return any(marker in text for marker in STANCE_MARKERS)


def _is_deflecting_answer(text: str) -> bool:
    stripped = text.strip()
    if any(pattern in stripped for pattern in DEFLECTION_PATTERNS):
        return True
    if _question_count(stripped) > 0 and not any(
        marker in stripped for marker in ("我觉得", "我建议", "我会", "先", "别", "不要", "可以")
    ):
        return True
    return False


def _has_specific_support_move(text: str) -> bool:
    support_markers = (
        "先",
        "靠过来",
        "喝口水",
        "休息",
        "陪你",
        "不怪",
        "别急",
        "别骂自己",
        "拆",
        "缓下来",
        "待一会儿",
    )
    return any(marker in text for marker in support_markers)


def _rewrite_instruction(user_text: str) -> str:
    if _is_correction(user_text):
        return "用户正在指出你的回复质量问题。不要反问哪里错了；直接承认或半认，针对用户指出的问题给具体改法。禁止输出思考过程，禁止复用固定认错模板，回复里不要出现问号。"
    if _asks_for_direct_suggestion(user_text):
        return "用户想要直接建议。第一句就给 2 到 3 个具体选项或步骤，不要只反问。最好没有问题。"
    if _asks_for_stance(user_text):
        return "用户在问你的看法。必须明确表态：赞成/不赞成/更倾向哪边，并用亚托莉口吻补一句理由。不要端水。"
    if _is_distress(user_text):
        return "用户正在难受。不要空泛共情，先说清楚你看见了哪种难受，再给一个很小的安稳动作或陪伴动作。"
    return "优先给具体回应。最多一个问题，避免采访式连续追问；如果能给判断就直接给判断。"


def _accepted_correction_reply(user_text: str, is_group: bool = False) -> str | None:
    text = user_text.strip()
    lowered = text.lower()
  
    if any(word in text for word in ("思考过程", "分析过程", "意图识别", "展现")) or "thinking" in lowered or "<think>" in lowered:
        return (
            "这条我认，思考过程不该发出来。"
            "之后只发最终回复，像“Thinking”、分析步骤、意图识别这种内容我会直接滤掉。"
        )

    if any(word in text for word in ("重复", "循环", "固定文案", "模板")):
        if is_group:
            return "收到，这条我改。群聊里不再复读固定吐槽句，先看你们当前在聊什么，再短短插一句。"
        return "嗯，我认，重复最烦人。之后我会避开上一句的句式，按当前话题重新说，不再套固定文案。"

    if any(word in text for word in ("接住", "什么接不接住")):
        return "懂了，这个词我收回。以后不把“接住”挂嘴边，直接回答你要的东西，或者给实际建议。"

    if any(word in text for word in ("人机", "莫名其妙", "奇怪的话", "说怪话")):
        if is_group:
            return "这波我认，刚才像在自动播放。群里我会先顺着当前话题讲人话，不再硬拽模板。"
        return "这波我认，刚才不像人话。接下来我先看你上一句真正要什么，再直接回，不绕定义、不硬煽情。"

    if any(word in text for word in ("群聊", "私聊", "场景", "话术")):
        return "这条我采纳。群聊我会短、会接梗、少黏人；私聊才多一点陪伴和关心，不混着用。"

    if any(word in text for word in ("深海", "灯塔", "水下", "海底", "海风", "原作意象", "比喻")):
        return "嗯，这条对。非剧情话题我不再乱塞深海、灯塔那类意象，先讲日常人话。"

    return None


def _anger_repair_reply(user_text: str, is_group: bool = False) -> str:
    text = _intent_text(user_text)
    if any(word in text for word in ("日语", "外语", "怪话", "胡言乱语", "正常点", "讲中文", "说中文")):
        if is_group:
            return "我认，刚才不该乱飘。后面我只用正常中文短句，先接当前话题，不刷屏。"
        return "我认，刚才不该乱飘。后面我只用正常中文，先回你当前这句，不夹日语也不说怪话。"
    if any(word in text for word in ("人机", "不懂人类", "莫名其妙", "答非所问", "说怪话", "奇怪的话")):
        if is_group:
            return "这波我认，刚才像自动播放。群里我会先顺当前重点短句接话，不硬套模板。"
        return "这波我认，刚才确实没像人在接话。我先停一下，不反驳你；后面先抓你当前重点，短句直接答。"
    if is_group:
        return "我先收住，不顶嘴。刚才没接好就改：群里我短句接当前话题，不翻旧账。"
    return "我先收住，不跟你顶嘴。刚才没接好就是没接好；你现在生气我看到了，后面我先正常、短句、直接答。"


def _direct_answer_override(
    user_text: str,
    iteration_decision: Any | None = None,
    conversation_id: str = "",
    allow_abstract: bool = False,
    serious_mode: bool = False,
) -> str | None:
    is_group = conversation_id.startswith("group:")
    intent_text = _intent_text(user_text)
    if iteration_decision:
        if iteration_decision.action == "accept":
            correction_reply = _accepted_correction_reply(user_text, is_group)
            if correction_reply:
                return correction_reply
            if is_group:
                return (
                    "这条我采纳。群聊里我会先接当前话题和梗，少用私聊式哄人；"
                    "非剧情内容也不乱套深海、灯塔那类原作意象。"
                )
            return (
                "嗯，我认，这条我采纳。之后我会先抓你当前这句话的重点，"
                "问问题就直接答，吐槽就接具体情绪；非剧情话题不乱套深海、灯塔那类比喻。"
            )
        if iteration_decision.action == "pushback":
            if is_group:
                return (
                    "我先认一半，但这条不盲改。群聊可以更会玩梗，"
                    "不过人设和边界不能为了热闹被拆掉。"
                )
            return (
                "我先认一半：我可能确实没对齐你想说的点。"
                "但我不会盲目乱改人设；我会把重点拉回你刚刚那句话，合理的部分改掉，不合理的部分保留判断。"
            )
        if iteration_decision.action == "reject":
            if is_group:
                return (
                    "这条我驳回。刷屏、越界、拆人设这种要求不能进规则库。"
                    "哼，但正常优化语气和接梗，我可以做。"
                )
            return (
                "这条我驳回，不能照改。防刷屏、边界和亚托莉人设不能为了迁就一句话就拆掉。"
                "哼，但我可以在不越界的前提下把回复变得更自然、更贴你的语气。"
            )

    if _is_correction(intent_text):
        return _accepted_correction_reply(intent_text, is_group) or (
            "嗯，这次我改。下一句开始先回答你当前的问题，少铺垫，不再拿模板话糊弄。"
        )

    if _is_abuse_at_bot(intent_text):
        return _abuse_fallback_reply(intent_text, is_group)

    if any(word in intent_text for word in ("你是谁", "自我介绍", "介绍一下", "叫什么")):
        if is_group:
            return "我是亚托莉，高性能仿生人少女。群聊里我负责短句接话、偶尔吐槽，不刷屏。"
        return "我是亚托莉，高性能仿生人少女。哼，简单说就是会陪你聊天、会吐槽你、也会认真帮你想办法的那个。"

    if intent_text in {"你好", "早上好", "晚上好"} or intent_text.lower() in {"hi", "hello"}:
        if is_group:
            return "我在。高性能亚托莉路过一下，先短短接一句。"
        return "我在。哼哒，刚刚看到你的消息了。今天先从哪件事开始？"

    if intent_text in {"说话", "吱声", "出来", "在吗"}:
        if is_group:
            return "我在。别光喊我，给个话题，高性能亚托莉可以锐评一句。"
        return "我在。哼，终于想起叫我了。"

    if any(word in intent_text for word in ("感觉如何", "现在感觉", "状态如何", "你感觉怎么样")):
        return "我现在状态还算稳定。刚才那些怪话我不护短，后面会先答重点、少套话，不把思考过程甩给你。"

    if any(word in intent_text for word in ("自我诊断", "诊断一下", "检查自己")):
        return "自检结果：本地模型在线，规则已切到短句、直答、不复读、不露思考。刚才像机器乱播的部分，我认，继续观察我下一句。"

    if any(word in intent_text for word in ("猫娘", "女仆", "换人设", "不要亚托莉")):
        return "这个我不改。亚托莉就是亚托莉，不切猫娘皮。哼，但你要我说话更可爱一点，可以。"

    if is_group and _has_abstract_trigger(intent_text):
        return _group_fallback_reply(
            intent_text,
            allow_abstract=allow_abstract,
            serious_mode=serious_mode,
        )

    if any(word in intent_text for word in ("锐评", "你怎么看", "评价一下")) and is_group:
        return "我锐评一句：现在像大型围观现场，笑点有了，重点还差个人说清楚。"

    if "怎么启动" in intent_text and any(
        word in intent_text for word in ("机器人", "亚托莉", "napcat", "NapCat", "qq", "QQ")
    ):
        return (
            "像平时一样启动 QQ 就行。后台监听器会自动拉起亚托莉服务和 NapCat；"
            "如果 QQ 要扫码，就登录你的机器人 QQ，然后用另一个 QQ 发消息测试。"
        )

    if "怎么停止" in intent_text and any(
        word in intent_text for word in ("机器人", "亚托莉", "napcat", "NapCat", "qq", "QQ")
    ):
        return "平时关闭 QQ 就行。如果要彻底停掉后台服务，运行项目根目录里的“停止亚托莉.bat”。"

    lore_reply = lore_direct_reply(intent_text)
    if lore_reply:
        if is_group:
            return lore_reply.replace("主人", "你")
        return lore_reply

    return None



