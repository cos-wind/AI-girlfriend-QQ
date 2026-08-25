from __future__ import annotations

from typing import Any

from . import core as _core


def _sync_module_globals() -> None:
    for name, value in vars(_core).items():
        if name not in {"AtriReplyEngine"} and not name.startswith("__"):
            globals()[name] = value


_sync_module_globals()

from .reply_rules import (
    _accepted_correction_reply,
    _asks_for_direct_suggestion,
    _asks_for_stance,
    _direct_answer_override,
    _emotional_fallback_reply,
    _has_concrete_suggestion,
    _has_abstract_noise,
    _has_specific_support_move,
    _has_stance,
    _is_correction,
    _is_deflecting_answer,
    _is_distress,
    _is_user_angry_at_bot,
    _needs_comfort_repair_mode,
    _needs_direct_answer,
    _normalize_reply,
    _question_count,
    _sanitize_group_mentions,
    _shares_content_word,
)

def _trim_extra_questions(text: str, keep_questions: int = 1) -> str:
    sentences = _split_sentences(text)
    kept: list[str] = []
    questions = 0
    for sentence in sentences:
        if "?" in sentence or "？" in sentence:
            questions += 1
            if questions > keep_questions:
                continue
        kept.append(sentence)
    return "".join(kept).strip() or text


def _split_sentences(text: str) -> list[str]:
    pieces = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    return [piece.strip() for piece in pieces if piece.strip()]


def _direct_suggestion_fallback(user_text: str) -> str:
    if "吃什么" in user_text or "晚饭" in user_text:
        return "我会选热一点、好消化的：西红柿炒鸡蛋，或者粥配一点肉和青菜。今晚别太折腾，吃完舒服最重要。"
    if "推荐" in user_text and any(word in user_text for word in ("吃", "饭", "夜宵", "早餐", "午饭")):
        return "我推荐、螃蟹、或者粥配青菜和肉。亚托莉的偏好很明确：先吃热的，别拿零食糊弄自己。"
    if "怎么启动" in user_text:
        return "像平时一样启动 QQ 就行。亚托莉的后台监听会自动拉起 NapCat 和聊天服务；如果 QQ 要扫码，就登录你的机器人 QQ。"
    if "怎么办" in user_text or "怎么做" in user_text:
        return (
            "可以，我先不乱指挥。按现在信息，先确认最急的限制是什么，"
            "再选代价最小的一步；你把背景补一句，我就能给更具体的做法。"
        )
    if "推荐" in user_text or "建议" in user_text:
        return (
            "可以，但这句还缺对象，我先不给万能建议。"
            "你告诉我是吃饭、学习、项目还是别的事，我再给你具体选项。"
        )
    return "可以，但我得先知道你说的是哪件事。给我一句背景，我再帮你拆得更准。"


def _stance_fallback(user_text: str) -> str:
    if any(word in user_text for word in ("对吗", "对不对", "这样做")):
        return "我先站个明确观点：如果这件事会让你长期委屈自己，我不赞成；如果只是短期麻烦但对你有好处，我支持你试。哼，我偏心主人，但不会无脑点头。"
    if any(word in user_text for word in ("要不要", "该不该", "值不值得")):
        return "我的态度是：别为了逃避焦虑才选，也别为了逞强硬扛。能让你更接近目标、代价又可控，就做；只会消耗你，就不要。"
    if "能不能" in user_text:
        return "我倾向于：能做，但要缩小范围先试。别一上来把自己推到满负荷，亚托莉不赞成那种逞强。"
    return "我给明确态度：别端着不动，先选对你最有利、代价最小的那边。哼，亚托莉偏务实，也偏心你。"



def _question_fallback(user_text: str) -> str:
    if _asks_for_direct_suggestion(user_text):
        return _direct_suggestion_fallback(user_text)

    if _asks_for_stance(user_text):
        return _stance_fallback(user_text)

    if "怎么启动" in user_text and any(
        word in user_text for word in ("机器人", "亚托莉", "napcat", "NapCat", "qq", "QQ")
    ):
        return "像平时一样启动 QQ。后台监听器会自动把亚托莉和 NapCat 拉起来，你不用再点单独的机器人窗口。"

    if user_text.strip("？? ") in {"为什么会这样", "怎么会这样", "为什么这样"}:
        return "如果你是在问刚才让你难受的事，那先别急着怪自己。亚托莉陪你一起捋捋。"

    if any(word in user_text for word in ("你爱我", "喜欢我", "想我")):
        return "这种问题还要问吗……哼，当然是在意你的。不然我为什么会认真等你每一句消息。"

    if any(word in user_text for word in ("我该怎么办", "怎么办", "怎么做")):
        return "先别急着一步解决。你告诉我现在卡住的是哪一件事，我再按现实限制帮你拆，不拿万能模板糊弄你。"

    topic = _shorten(user_text.rstrip("？?"))
    if "为什么" in user_text or "怎么会" in user_text:
        return f"关于“{topic}”，我的判断是：通常不是单一原因，更像压力、期待和现实卡住叠在一起。先别急着怪自己，抓最影响你的那一块处理。"
    if "是什么" in user_text or "什么" in user_text:
        return f"“{topic}”这类问题我先不乱编。你要是问概念，我会直接讲定义；你要是问该怎么做，我就给步骤。"
    return f"关于“{topic}”，我给结论：先做最靠近结果的一步，别一下子把自己逼满。亚托莉偏务实，能动的先动。"


def _language_guard_fallback(user_text: str, conversation_id: str = "") -> str:
    if conversation_id.startswith("group:"):
        return "我换成正常中文说：刚才那句不该乱飘。你们继续，我按当前话题短短接一句。"
    if _is_distress(user_text):
        return "先别硬撑。那句乱掉的我丢掉了，现在我只陪你把眼前这点难受缓下来。"
    if _needs_direct_answer(user_text):
        return _question_fallback(user_text)
    return f"“{_shorten(user_text)}”我重新说：先按你这句话本身来回，不让奇怪字符混进来。"


def _fit_reply_with_sources(text: str, sources: list[str], limit: int = 1200) -> str:
    source_lines = [source for source in sources[:2] if source and source not in text]
    source_block = f"\n来源：{'；'.join(source_lines)}" if source_lines else ""
    body = str(text or "").strip()
    return f"{body}{source_block}".strip()


def _looks_incomplete_reply(text: str) -> bool:
    compact = str(text or "").rstrip()
    if compact.endswith(("...", "…", "，", ",", "：", ":", "；", ";")):
        return True
    opening_pairs = (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"), ("“", "”"))
    return any(compact.count(left) > compact.count(right) for left, right in opening_pairs)


def _repair_incomplete_reply(text: str) -> str:
    """Keep a usable complete prefix when a local model stops mid-sentence."""
    compact = _normalize_reply(text).rstrip()
    if not compact:
        return ""
    if not _looks_incomplete_reply(compact):
        return compact

    # Prefer an already completed sentence over inventing a continuation.
    boundary = max(compact.rfind(mark) for mark in ("。", "！", "？", "!", "?"))
    if boundary >= max(8, int(len(compact) * 0.35)):
        return compact[: boundary + 1].rstrip()

    candidate = compact.rstrip(".……，,：:；; ")
    for dangling in ("然后", "但是", "所以", "因为", "而且", "比如", "包括", "以及"):
        if candidate.endswith(dangling):
            candidate = candidate[: -len(dangling)].rstrip("，,：:；; ")
            break
    if len(candidate) < 6:
        return ""

    for left, right in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"), ("“", "”")):
        missing = candidate.count(left) - candidate.count(right)
        if missing > 0:
            candidate += right * missing
    if not candidate.endswith(("。", "！", "？", "!", "?")):
        candidate += "。"
    return candidate


def _redact_sensitive_output(text: str, *, is_group: bool) -> str:
    value = str(text or "")
    value = re.sub(
        r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{8,}",
        "[已隐藏令牌]",
        value,
    )
    value = re.sub(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*[^\s,，;；]+",
        "[已隐藏敏感配置]",
        value,
    )
    value = re.sub(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+(?:\\[^\s]*)?", "[已隐藏本机路径]", value)
    if is_group:
        value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[已隐藏手机号]", value)
        value = re.sub(r"(?<!\d)\d{17}[0-9Xx](?!\d)", "[已隐藏身份证号]", value)
    return value


def _truncate_reply_at_boundary(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    candidates = [prefix.rfind(mark) for mark in ("。", "！", "？", "!", "?", "\n")]
    boundary = max(candidates)
    if boundary >= max(80, int(limit * 0.55)):
        return prefix[: boundary + 1].rstrip()
    return prefix.rstrip() + "…"


def _tool_receipt_urls(receipts: list[ToolExecutionReceipt]) -> set[str]:
    urls: set[str] = set()
    for receipt in receipts:
        if not receipt.ok or receipt.name not in {"search_web", "open_web_page"}:
            continue
        for match in re.findall(r"https?://[^\s<>\"'）】]+", receipt.content):
            canonical = _canonical_evidence_url(match)
            if canonical:
                urls.add(canonical)
    return urls


def _canonical_evidence_url(value: str) -> str:
    candidate = str(value or "").strip().rstrip(".,;:!?，。；：！？)]}）】")
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""
    path = parsed.path.rstrip("/") or "/"
    if (parsed.hostname or "").casefold().endswith("arxiv.org"):
        path = re.sub(r"(/abs/\d+\.\d+)v\d+$", r"\1", path)
    return urlunsplit(("https", parsed.netloc.casefold(), path, parsed.query, ""))


def _looks_like_tool_schema_error(exc: Any) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code not in {400, 404, 422}:
        return False
    detail = str(getattr(response, "text", "") or "").casefold()
    tool_markers = ("tool_choice", "tool call", '"tools"', "function_call", "function call")
    rejection_markers = (
        "unsupported",
        "not support",
        "unknown",
        "unrecognized",
        "not allowed",
        "extra",
        "schema",
    )
    return any(marker in detail for marker in tool_markers) and any(
        marker in detail for marker in rejection_markers
    )


def _provider_payload_overrides(base_url: str, model: str) -> dict[str, Any]:
    if (
        "api.deepseek.com" in str(base_url).casefold()
        and str(model).strip().casefold() in {"deepseek-v4-flash", "deepseek-v4-pro"}
    ):
        return {"thinking": {"type": "disabled"}}
    return {}


def _persona_violations(user_text: str, reply_text: str) -> list[str]:
    reply = reply_text.strip()
    violations: list[str] = []

    if any(pattern in reply for pattern in BANNED_ASSISTANT_PATTERNS):
        violations.append("出现 AI 助手/客服式表达")

    if re.search(r"@\d{5,}", reply):
        violations.append("群聊输出 QQ 号艾特")

    if _has_abstract_noise(reply):
        violations.append("输出外语梗、无意义拟声或抽象怪话")

    if len(reply) > 260:
        violations.append("回复过长，应该拆成短句")

    if "\n" in reply and len([line for line in reply.splitlines() if line.strip()]) >= 4:
        violations.append("像长段说明，不像 QQ 聊天")

    if _question_count(reply) > 1:
        violations.append("连续反问，像采访而不是聊天")

    if any(pattern in reply for pattern in GENERIC_REPLY_PATTERNS) and not _shares_content_word(
        user_text, reply
    ):
        violations.append("空泛安慰，没有接住用户具体内容")

    if _uses_lore_imagery_out_of_context(user_text, reply):
        violations.append("非剧情话题滥用深海/灯塔等原作意象")

    if _uses_stale_meme_pile(reply):
        violations.append("生硬堆砌网络烂梗")

    if _fabricates_real_world_action(reply):
        violations.append("编造现实动作、位置或见闻")

    if _needs_direct_answer(user_text) and _is_deflecting_answer(reply):
        violations.append("用户需要直接回答，但回复在绕圈或反问")

    if _asks_for_direct_suggestion(user_text) and not _has_concrete_suggestion(reply):
        violations.append("用户需要建议，但回复没有给具体选项或步骤")

    if _asks_for_stance(user_text) and not _has_stance(reply):
        violations.append("用户在问看法，但回复没有明确态度")

    if _is_distress(user_text) and not _has_specific_support_move(reply):
        violations.append("用户难受时回复太空，没有安慰动作或支持动作")

    if _needs_comfort_repair_mode(user_text) and any(
        pattern in reply for pattern in ("你上次", "之前你", "怼回", "翻旧", "好感度")
    ):
        violations.append("负面情绪或纠错时翻旧账")

    if (_is_distress(user_text) or _is_user_angry_at_bot(user_text)) and reply.startswith("哼"):
        violations.append("用户负面情绪时傲娇顶嘴")

    if has_lore_trigger(user_text) and not _handles_lore_context(user_text, reply):
        violations.append("用户提到原作/梗，但回复没有使用亚托莉视角")

    return violations


def _handles_lore_context(user_text: str, reply_text: str) -> bool:
    if "高性能" in user_text:
        return any(word in reply_text for word in ("高性能", "任务", "哼", "亚托莉"))
    if any(word in user_text for word in ("海底", "水下", "打捞", "沉没")):
        return any(word in reply_text for word in ("水下", "岸", "带回", "海", "日常"))
    if "夏生" in user_text or "斑鸠" in user_text:
        return any(word in reply_text for word in ("夏生", "先生", "相遇", "约定"))
    if any(word in user_text for word in ("45天", "四十五天", "有限时间")):
        return any(word in reply_text for word in ("时间", "今天", "认真", "约定"))
    if "心" in user_text and ("机器人" in user_text or "亚托莉" in user_text):
        return any(word in reply_text for word in ("心", "感受", "珍惜", "约定"))
    if _explicit_lore_context(user_text):
        return any(word in reply_text for word in ("亚托莉", "我", "高性能", "原作", "夏天"))
    return True


def _uses_lore_imagery_out_of_context(user_text: str, reply_text: str) -> bool:
    if has_lore_trigger(user_text) or _explicit_lore_context(user_text):
        return False
    return any(word in reply_text for word in LORE_IMAGERY_WORDS)


def _uses_stale_meme_pile(reply_text: str) -> bool:
    stale_count = sum(1 for word in STALE_MEME_WORDS if word in reply_text)
    light_meme_count = sum(
        1 for word in ("抽象", "逆天", "红温", "破防", "绷不住", "6") if word in reply_text
    )
    return stale_count >= 1 or light_meme_count >= 3


def _fabricates_real_world_action(reply_text: str) -> bool:
    return any(pattern in reply_text for pattern in REAL_WORLD_ACTION_PATTERNS)


def _needs_hard_reality_repair(reply_text: str) -> bool:
    return any(pattern in reply_text for pattern in HARD_REALITY_CLAIM_PATTERNS)


def _needs_history_grounding_review(reply_text: str) -> bool:
    compact = re.sub(r"\s+", "", str(reply_text or ""))
    return bool(
        re.search(
            r"(?:上次|之前|以前|一向|总是|每次|前科|观察过|记得清清楚楚)"
            r"|(?:这|那|本来就|明明就)(?:是|属于)(?:事实|真的)"
            r"|我(?:又)?没说错|谁让你",
            compact,
        )
    )


def _persona_repair_fallback(
    user_text: str,
    reply_text: str,
    serious_mode: bool = False,
    conversation_id: str = "",
) -> str:
    is_group = conversation_id.startswith("group:")
    if is_group:
        reply_text = _sanitize_group_mentions(reply_text)

    if serious_mode or _has_abstract_noise(reply_text):
        if _is_distress(user_text):
            return "先别硬撑。把那口气缓一下，我陪你按眼前这件事一点点拆。"
        if _needs_direct_answer(user_text):
            return _question_fallback(user_text)
        if is_group:
            return "我切回正常中文：刚才那句不该乱飘。你们这话题我按当前重点接。"
        return f"“{_shorten(user_text)}”我重新说：先讲人话，别乱飘。"

    direct_reply = _direct_answer_override(user_text, conversation_id=conversation_id)
    if direct_reply:
        if is_group:
            direct_reply = _sanitize_group_mentions(direct_reply)
        return direct_reply

    lore_reply = lore_direct_reply(user_text)
    if lore_reply:
        return lore_reply

    if _uses_lore_imagery_out_of_context(user_text, reply_text):
        if _is_distress(user_text):
            return "难受的时候先别硬撑。先喝口水，把肩膀放下来一点；亚托莉在这里陪你把最刺痛的那点拆小。"
        if _needs_direct_answer(user_text):
            return _question_fallback(user_text)
        return f"关于“{_shorten(user_text)}”，我直接说重点：别绕比喻，先看你现在真正要解决的那件事。"


    if _fabricates_real_world_action(reply_text):
        if _is_distress(user_text):
            return "先别硬撑。喝口水，肩膀放松一点；你不用马上变好，我陪你把眼前这件事拆小。"
        return _trim_extra_questions(_shorten_long_reply(reply_text), keep_questions=1)

    if _is_correction(user_text):
        return _accepted_correction_reply(user_text) or "嗯，这次我改。下一句开始先答重点，不绕圈。"

    if _is_distress(user_text):
        return _emotional_fallback_reply(user_text, is_group=is_group)

    if _asks_for_direct_suggestion(user_text):
        return _direct_suggestion_fallback(user_text)

    if _asks_for_stance(user_text):
        return _stance_fallback(user_text)

    if any(pattern in reply_text for pattern in BANNED_ASSISTANT_PATTERNS):
        if _needs_direct_answer(user_text):
            return _question_fallback(user_text)
        return f"“{_shorten(user_text)}”我直接回：我会认真思考这个问题。"

    return _trim_extra_questions(_shorten_long_reply(reply_text), keep_questions=1)


def _shorten_long_reply(text: str, limit: int = 140) -> str:
    sentences = _split_sentences(_normalize_reply(text))
    result = ""
    for sentence in sentences:
        if len(result) + len(sentence) > limit:
            break
        result += sentence
    return result.strip() or text[:limit].strip()


def _explicit_lore_context(text: str) -> bool:
    lowered = text.lower()
    return any(word in text for word in ("原作", "剧情", "设定", "梗", "名场面")) or "atri" in lowered
