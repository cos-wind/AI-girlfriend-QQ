from __future__ import annotations

from . import *  # noqa: F403 — compatibility globals are populated by the package.
from . import (
    _toolbox_formatting,
    _toolbox_media_probe,
    _toolbox_office_docs,
    _toolbox_request_collection,
)

_SegmentRef = _toolbox_request_collection._SegmentRef
_MaterialRequest = _toolbox_request_collection._MaterialRequest
_collect_request = _toolbox_request_collection._collect_request
_segment_ref = _toolbox_request_collection._segment_ref
_material_filename_hint = _toolbox_request_collection._material_filename_hint
_message_has_only_material = _toolbox_request_collection._message_has_only_material
_collect_share_segment = _toolbox_request_collection._collect_share_segment
_parse_maybe_json = _toolbox_request_collection._parse_maybe_json
_extract_urls_from_any = _toolbox_request_collection._extract_urls_from_any
_extract_share_hints = _toolbox_request_collection._extract_share_hints
_extract_xmlish_tag = _toolbox_request_collection._extract_xmlish_tag
_first_text = _toolbox_request_collection._first_text
_as_positive_int = _toolbox_request_collection._as_positive_int
_extension_for_material = _toolbox_request_collection._extension_for_material
_basename_from_ref = _toolbox_request_collection._basename_from_ref
_is_bilibili_url = _toolbox_request_collection._is_bilibili_url
_onebot_material_actions = _toolbox_request_collection._onebot_material_actions
_resolve_material_from_action_response = _toolbox_request_collection._resolve_material_from_action_response
_extract_path_from_any = _toolbox_request_collection._extract_path_from_any
_int_or_original = _toolbox_request_collection._int_or_original
_extract_urls = _toolbox_request_collection._extract_urls
_extract_paths = _toolbox_request_collection._extract_paths
_classify_category = _toolbox_request_collection._classify_category



def _prepare_images_for_vision(
    data: bytes,
    static_max_side: int = 1536,
    animated_max_side: int = 768,
) -> list[bytes]:
    try:
        from PIL import Image, ImageOps
    except Exception:
        return [data]

    try:
        with Image.open(io.BytesIO(data)) as image:
            frame_count = int(getattr(image, "n_frames", 1) or 1)
            if frame_count > 1:
                sample_indices = sorted(
                    {
                        0,
                        frame_count // 2,
                        frame_count - 1,
                    }
                )
                prepared_frames: list[bytes] = []
                for frame_index in sample_indices[:3]:
                    image.seek(frame_index)
                    frame = ImageOps.exif_transpose(image.copy()).convert("RGBA")
                    frame.thumbnail((animated_max_side, animated_max_side))
                    background = Image.new("RGB", frame.size, (255, 255, 255))
                    background.paste(frame, mask=frame.getchannel("A"))
                    output = io.BytesIO()
                    background.save(output, format="PNG", optimize=True)
                    prepared_frames.append(output.getvalue())
                return [frame for frame in prepared_frames if frame] or [data]

            prepared = ImageOps.exif_transpose(image.copy())
            prepared.thumbnail((static_max_side, static_max_side))
            if prepared.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", prepared.size, (255, 255, 255))
                alpha = prepared.getchannel("A")
                background.paste(prepared.convert("RGBA"), mask=alpha)
                prepared = background
            elif prepared.mode != "RGB":
                prepared = prepared.convert("RGB")
            output = io.BytesIO()
            prepared.save(output, format="PNG", optimize=True)
            optimized = output.getvalue()
            return [optimized] if optimized else [data]
    except Exception:
        return [data]


def _prepare_image_for_vision(data: bytes, max_side: int = 1536) -> bytes:
    return _prepare_images_for_vision(
        data,
        static_max_side=max_side,
        animated_max_side=min(max_side, 768),
    )[0]


def _video_frame_position_labels(frame_count: int) -> list[str]:
    count = max(1, int(frame_count or 1))
    if count == 1:
        return ["中间位置"]
    labels: list[str] = []
    for index in range(count):
        if index == 0:
            labels.append("开头")
        elif index == count - 1:
            labels.append("结尾")
        else:
            labels.append(f"约 {round(index * 100 / (count - 1))}% 处")
    return labels


def _ollama_native_base_url(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    if parsed.port == 11434:
        return f"{parsed.scheme}://{parsed.netloc}"
    if path == "/v1" and "ollama" in parsed.netloc.lower():
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _exception_summary(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", "")
        try:
            text = response.text
        except Exception:
            text = ""
        text = _shorten(str(text or "").strip(), 220)
        if status and text:
            return f"HTTP {status} {text}"
        if status:
            return f"HTTP {status}"
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _is_retryable_vision_resource_error(exc: Exception) -> bool:
    summary = _exception_summary(exc).casefold()
    return any(
        marker in summary
        for marker in (
            "memory layout cannot be allocated",
            "requires more system memory",
            "ggml_assert",
            "mem_buffer",
            "out of memory",
            "model runner has unexpectedly stopped",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "timed out",
            "timeout",
            "connection reset",
            "connecterror",
            "gpu 推理资源正被其他任务占用",
            "inference resource",
        )
    )


def _merge_read_levels(levels: list[str]) -> str:
    cleaned = [str(level or "").strip() for level in levels if str(level or "").strip()]
    if not cleaned:
        return "metadata_only"
    if any(level == "full_content" for level in cleaned):
        return "full_content"
    if any(level == "partial_content" for level in cleaned):
        return "partial_content"
    return "metadata_only"


def _merge_visual_statuses(statuses: list[str]) -> str:
    cleaned = [str(status or "").strip() for status in statuses if str(status or "").strip()]
    if not cleaned:
        return ""
    if all(status == "verified" for status in cleaned):
        return "verified"
    if len(cleaned) == 1:
        return cleaned[0]
    if all(status in {"verified", "ocr_only"} for status in cleaned):
        return "partial"
    if any(status == "unavailable" for status in cleaned):
        return "unavailable"
    return "metadata_only"


def _classify_visual_material(
    data: bytes | None,
    source: str,
    image_ref: _SegmentRef | None = None,
) -> str:
    if image_ref and image_ref.kind == "sticker":
        return "sticker"

    text = " ".join(
        part
        for part in (
            source,
            image_ref.name if image_ref else "",
            image_ref.summary if image_ref else "",
            image_ref.file if image_ref else "",
            image_ref.url if image_ref else "",
        )
        if part
    ).lower()

    if any(token in text for token in ("动画表情", "qq表情", "表情包")):
        return "sticker"
    parts = {part.lower() for part in re.split(r"[^A-Za-z0-9_\u4e00-\u9fff]+", text) if part}
    if "chat_history" in parts and parts & _STICKER_EMOTION_PARTS:
        return "sticker"
    if {"mface", "marketface", "sticker", "emoji", "emoticon", "face", "qqface"} & parts:
        return "sticker"
    if "stickers" in parts and "chat_history" not in parts:
        return "sticker"
    if any(token in text for token in ("截图", "screenshot", "screen", "photo", "image", "scan")):
        return "image"
    if any(token in text for token in ("游戏", "ui", "界面", "文档", "表格", "网页", "聊天记录")):
        return "image"

    info = _image_info(data or b"") if data else None
    if info:
        kind, width, height = info
        if kind == "GIF":
            return "sticker"
        if width and height:
            if width >= 720 or height >= 720:
                return "image"
    return "auto"


def _fallback_visual_kind(
    data: bytes | None,
    source: str,
    image_ref: _SegmentRef | None = None,
) -> str:
    result = _classify_visual_material(data, source, image_ref)
    return "image" if result == "auto" else result


def _visual_meta_line(visual_kind: str, data: bytes, info: tuple[str, int, int] | None) -> str:
    label = "表情包信息" if visual_kind == "sticker" else "图片信息"
    if info:
        kind, width, height = info
        return f"{label}：{kind} 格式，尺寸约 {width}x{height}。"
    return f"{label}：约 {len(data)} 字节，暂未识别出尺寸。"


def _visual_prompt_for_kind(visual_kind: str, user_question: str = "") -> str:
    question = re.sub(
        r"\[(?:表情包/图片|动画表情|图片):.*?\]\]?",
        " ",
        str(user_question or ""),
    )
    question = re.sub(r"@(?:群友|全体成员)", " ", question)
    question = re.sub(r"\s+", " ", question).strip()
    question = _shorten(question, 300) if question else "用户没有附加文字，请完整理解图片。"
    kind_focus = {
        "sticker": (
            "这通常是表情包/梗图/动画表情。重点判断它在聊天中传达的情绪、态度和社交意图，"
            "不能只罗列颜色、发型和衣着。"
        ),
        "image": (
            "这通常是普通图片、截图或照片。重点识别主体、人物身份、可见文字、界面信息和用户真正关心的内容。"
        ),
    }.get(
        visual_kind,
        "先判断它是表情包、梗图、动画表情、普通图片、截图还是照片，再按对应重点分析。",
    )
    return (
        "只分析本次请求附带的当前图片，不得引用或猜测上一张图片。\n"
        f"当前用户问题：{question}\n"
        f"{kind_focus}\n"
        "先直接回答用户的当前问题，再补充必要依据。OCR 时逐字读取主要可见文字；"
        "没有明显文字就写“无明显文字”，看不清的字不要编。"
        "对于知名动漫、游戏、虚拟歌手或影视人物，特征充分时给出姓名和出处；"
        "不确定时不要硬猜。只要给出了具体人物名或作品名，"
        "“需要联网核验”必须写“是”，检索关键词必须包含候选名、作品名和至少一个当前画面特征；"
        "联网结果不能支持时，最终身份应保持未确认。"
        "必须理解图片在当前聊天里想表达什么，不能停留在图像特征罗列。\n"
        "只输出简体中文 JSON，不输出思考过程或 Markdown。字段含义："
        "direct_answer（直接回答）不可留空；visible_text（图中文字）是逐字可见文字；"
        "subjects（人物/主体）是可见主体；identity（身份/出处）不确定时写“未确认”；"
        "emotion（表情/情绪）是情绪；social_intent（表达含义/社交意图）是聊天语境下含义；"
        "evidence（依据）只能列可见依据；"
        "confidence 只能为 high、medium、low；needs_web_verification 是布尔值；"
        "search_keywords 是字符串数组，需要核验时给出 3-8 个关键词，否则为空数组。"
    )


def _visual_search_query(analysis_text: str) -> str:
    text = str(analysis_text or "")
    needs_search = bool(
        re.search(r"需要联网核验\s*[:：]\s*是", text)
        or re.search(r"置信度\s*[:：]\s*低", text)
    )
    if not needs_search:
        return ""
    match = re.search(
        r"检索关键词\s*[:：]\s*([^；;\r\n]+)",
        text,
    )
    if not match:
        return ""
    query = re.sub(r"\s+", " ", match.group(1)).strip(" ，,。")
    return _shorten(query, 160)


def _search_result_supports_query(search_result: str, query: str) -> bool:
    query_terms = [
        term.strip("\"'“”《》()（）,，。")
        for term in re.split(r"\s+", str(query or "").strip())
        if term.strip("\"'“”《》()（）,，。")
    ]
    if len(query_terms) < 2:
        return False
    result_text = str(search_result or "")
    first_result = re.search(r"(?:^|\n)\s*\d+\.\s*标题\s*[:：]", result_text)
    if first_result:
        result_text = result_text[first_result.start() :]
    else:
        result_text = "\n".join(
            line
            for line in result_text.splitlines()
            if not line.strip().startswith(("搜索关键词：", "搜索时间：", "聚合来源："))
        )
    haystack = result_text.casefold()
    matched_terms = {
        term.casefold()
        for term in query_terms
        if len(term) >= 2 and term.casefold() in haystack
    }
    return (
        query_terms[0].casefold() in matched_terms
        and len(matched_terms) >= 2
    )


def _normalize_visual_model_output(raw_text: str) -> str:
    raw = str(raw_text or "").strip()
    if not raw:
        return ""
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
    if not candidate.startswith("{"):
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if match:
            candidate = match.group(0)
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _sanitize_vision_text(raw)
    if not isinstance(payload, dict):
        return ""

    def string_value(key: str, fallback: str = "") -> str:
        value = payload.get(key, fallback)
        if isinstance(value, list):
            value = "、".join(str(item).strip() for item in value if str(item).strip())
        return re.sub(r"\s+", " ", str(value or fallback)).strip()

    direct_answer = string_value("direct_answer")
    visible_text = string_value("visible_text", "无明显文字") or "无明显文字"
    subjects = string_value("subjects", "未确认") or "未确认"
    identity = string_value("identity", "未确认") or "未确认"
    emotion = string_value("emotion", "无法确认") or "无法确认"
    social_intent = string_value("social_intent", "无法确认") or "无法确认"
    evidence = string_value("evidence", "证据不足") or "证据不足"
    confidence = {
        "high": "高",
        "medium": "中",
        "low": "低",
        "高": "高",
        "中": "中",
        "低": "低",
    }.get(string_value("confidence").casefold(), "低")
    needs_web = payload.get("needs_web_verification") is True
    keywords = payload.get("search_keywords")
    if isinstance(keywords, list):
        keyword_text = " ".join(
            re.sub(r"\s+", " ", str(item)).strip()
            for item in keywords
            if str(item).strip()
        )
    else:
        keyword_text = re.sub(r"\s+", " ", str(keywords or "")).strip()
    normalized = (
        f"直接回答：{direct_answer or '当前画面证据不足，无法可靠判断'}；"
        f"图中文字：{visible_text}；"
        f"人物/主体：{subjects}；"
        f"身份/出处：{identity}；"
        f"表情/情绪：{emotion}；"
        f"表达含义/社交意图：{social_intent}；"
        f"依据：{evidence}；"
        f"置信度：{confidence}；"
        f"需要联网核验：{'是' if needs_web else '否'}；"
        f"检索关键词：{keyword_text}"
    )
    return _sanitize_vision_text(normalized)


def _replace_visual_visible_text(analysis_text: str, ocr_text: str) -> str:
    text = str(analysis_text or "")
    evidence = re.sub(r"\s+", " ", str(ocr_text or "")).strip()
    if not text or not evidence:
        return text
    pattern = r"(图中文字\s*[:：])[^；;\r\n]*"
    if re.search(pattern, text):
        return re.sub(
            pattern,
            lambda match: f"{match.group(1)}{evidence}",
            text,
            count=1,
        )
    return f"{text}；图中文字：{evidence}"


def _visual_response_failure_reason(
    raw_text: str,
    cleaned_text: str,
    metrics: dict[str, Any] | None = None,
) -> str:
    if not str(raw_text or "").strip() or not str(cleaned_text or "").strip():
        return "empty_output"
    cleaned = str(cleaned_text)
    if len(re.sub(r"\s+", "", cleaned)) < 16:
        return "too_short"
    done_reason = str((metrics or {}).get("done_reason") or "").strip().lower()
    if done_reason in {"length", "max_tokens"} and not _is_complete_visual_analysis(cleaned):
        return "truncated_output"
    if str(raw_text).lstrip().startswith("{") and not _is_complete_visual_analysis(cleaned):
        return "invalid_structured_output"
    return ""


def _is_complete_visual_analysis(text: str) -> bool:
    normalized = str(text or "")
    required_fields = (
        "直接回答：",
        "图中文字：",
        "人物/主体：",
        "身份/出处：",
        "表情/情绪：",
        "表达含义/社交意图：",
        "依据：",
        "置信度：",
        "需要联网核验：",
    )
    return all(field in normalized for field in required_fields)


def _ensure_visual_identity_requires_verification(analysis_text: str) -> str:
    text = str(analysis_text or "")
    match = re.search(r"身份/出处\s*[:：]\s*([^；;\r\n]+)", text)
    if not match:
        return text
    identity = match.group(1).strip()
    if not identity or any(
        marker in identity
        for marker in (
            "未确认",
            "无法确认",
            "不能确认",
            "无明确",
            "无特定",
            "未知",
            "普通人物",
            "网络表情包",
        )
    ):
        return text

    if re.search(r"需要联网核验\s*[:：]\s*否", text):
        text = re.sub(
            r"(需要联网核验\s*[:：]\s*)否",
            r"\1是",
            text,
            count=1,
        )
    elif not re.search(r"需要联网核验\s*[:：]", text):
        text = f"{text}；需要联网核验：是"

    keyword_match = re.search(
        r"检索关键词\s*[:：]\s*([^；;\r\n]*)",
        text,
    )
    if keyword_match and keyword_match.group(1).strip():
        return text
    fallback_keywords = re.sub(r"[（）()].*?[）)]", " ", identity)
    fallback_keywords = re.sub(
        r"(疑似|可能是|来自|中的角色|角色|形象)",
        " ",
        fallback_keywords,
    )
    fallback_keywords = re.sub(r"\s+", " ", fallback_keywords).strip()
    if keyword_match:
        return (
            text[: keyword_match.start(1)]
            + _shorten(fallback_keywords, 120)
            + text[keyword_match.end(1) :]
        )
    return f"{text}；检索关键词：{_shorten(fallback_keywords, 120)}"


def _demote_unverified_visual_identity(analysis_text: str) -> str:
    demoted = re.sub(
        r"(身份/出处\s*[:：])[^；;\r\n]*",
        r"\1未确认（视觉模型候选未获得联网证据，不作为事实）",
        str(analysis_text or ""),
        count=1,
    )
    demoted = re.sub(
        r"(依据\s*[:：])[^；;\r\n]*",
        r"\1人物身份未获可靠核验；情绪判断仅依据本轮可见表情和姿态",
        demoted,
        count=1,
    )
    return re.sub(
        r"(检索关键词\s*[:：])[^；;\r\n]*",
        r"\1无可靠匹配",
        demoted,
        count=1,
    )


def _duration_ms(value: Any) -> int | None:
    try:
        nanoseconds = int(value)
    except (TypeError, ValueError):
        return None
    return round(nanoseconds / 1_000_000)


def _visual_kind_from_analysis(text: str) -> str:
    normalized = str(text or "").lower()
    if any(token in normalized for token in ("表情包", "梗图", "动画表情", "meme", "sticker")):
        return "sticker"
    if any(token in normalized for token in ("普通图片", "截图", "照片", "游戏界面", "ui", "文档截图")):
        return "image"
    return ""


def _sanitize_vision_text(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", " ", str(text or ""), flags=re.IGNORECASE | re.DOTALL)
    lines: list[str] = []
    for raw_line in re.split(r"[\r\n]+", text):
        line = raw_line.strip()
        if not line:
            continue
        if re.search(r"\b(analysis|reasoning|thought|tool|system|assistant|user)\b", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"[A-Za-z0-9_:/\\|+=\-*#@$%^&{}[\]().,;!?~`'\" ]{12,}", line):
            continue
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", line))
        visible_chars = len(re.sub(r"\s+", "", line))
        if visible_chars >= 8 and chinese_chars == 0:
            continue
        lines.append(line)
    cleaned = "；".join(lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ；。")
    cleaned = _collapse_repeated_terms(cleaned)
    return _shorten(cleaned, 1000)


_STICKER_EMOTION_PARTS = {
    "affection",
    "angry",
    "comfort",
    "confused",
    "food",
    "goodnight",
    "happy",
    "pout",
    "proud",
    "shy",
    "speechless",
    "teasing",
    "tired",
}


def _collapse_repeated_terms(text: str) -> str:
    text = re.sub(
        r"(?P<term>[\u4e00-\u9fffA-Za-z0-9]{1,12})(?:、(?P=term)){3,}",
        lambda match: f"{match.group('term')}、{match.group('term')}",
        text,
    )
    text = re.sub(
        r"(?P<term>[\u4e00-\u9fffA-Za-z0-9]{1,12})(?:，(?P=term)){3,}",
        lambda match: f"{match.group('term')}，{match.group('term')}",
        text,
    )
    text = re.sub(
        r"(?P<term>[\u4e00-\u9fffA-Za-z0-9]{1,12})(?: (?P=term)){4,}",
        lambda match: f"{match.group('term')} {match.group('term')}",
        text,
    )
    return text


def _looks_like_text_bytes(data: bytes) -> bool:
    sample = data[:1024]
    if not sample or b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            sample.decode("gb18030")
            return True
        except UnicodeDecodeError:
            return False




_decode_bytes = _toolbox_formatting._decode_bytes
_extract_html_title = _toolbox_formatting._extract_html_title
_extract_meta_description = _toolbox_formatting._extract_meta_description
_extract_readable_text = _toolbox_formatting._extract_readable_text
_clean_html_text = _toolbox_formatting._clean_html_text
_extract_bvid = _toolbox_formatting._extract_bvid
_clean_bilibili_title = _toolbox_formatting._clean_bilibili_title
_looks_authoritative = _toolbox_formatting._looks_authoritative
_shorten = _toolbox_formatting._shorten
_summarize_json = _toolbox_formatting._summarize_json
_summarize_table_rows = _toolbox_formatting._summarize_table_rows
_numeric_column_summaries = _toolbox_formatting._numeric_column_summaries
_to_float = _toolbox_formatting._to_float
_format_number = _toolbox_formatting._format_number



_docx_text_part_names = _toolbox_office_docs._docx_text_part_names
_docx_xml_to_text = _toolbox_office_docs._docx_xml_to_text
_read_xlsx_sheet_refs = _toolbox_office_docs._read_xlsx_sheet_refs
_read_xlsx_shared_strings = _toolbox_office_docs._read_xlsx_shared_strings
_first_xlsx_sheet_name = _toolbox_office_docs._first_xlsx_sheet_name
_read_xlsx_sheet_rows = _toolbox_office_docs._read_xlsx_sheet_rows



_image_mime_type = _toolbox_media_probe._image_mime_type
_extract_video_frames = _toolbox_media_probe._extract_video_frames
_probe_video_duration_seconds = _toolbox_media_probe._probe_video_duration_seconds
_extract_even_video_frames = _toolbox_media_probe._extract_even_video_frames
_image_info = _toolbox_media_probe._image_info
_jpeg_info = _toolbox_media_probe._jpeg_info



_GENERIC_VIDEO_TITLES = {
    "视频",
    "视频文件",
    "手机发来的视频",
    "未命名视频",
    "video",
    "clip",
}


def _meaningful_video_title(value: str) -> bool:
    title = Path(str(value or "").strip()).stem.strip()
    if not title:
        return False
    return title.casefold() not in {item.casefold() for item in _GENERIC_VIDEO_TITLES}


def _looks_like_video_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if _is_bilibili_url(url):
        return True
    return Path(unquote(parsed.path)).suffix.lower() in VIDEO_EXTENSIONS


def _is_visual_ref(value: Any) -> bool:
    """仅按明确的文件后缀判断视觉材料，避免误拦普通网页链接。"""
    suffix = Path(unquote(str(value or "").split("?", 1)[0])).suffix.lower()
    return suffix in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def _video_url_metadata_fallback(url: str, limitation: str) -> ToolAnalysisResult:
    title = Path(unquote(urlparse(url).path)).stem.strip()
    findings = [f"视频地址：{url}"]
    if _meaningful_video_title(title):
        findings.insert(0, f"视频标题：{title}")
    return ToolAnalysisResult(
        "日常生活乐趣",
        "抽象有趣",
        [url],
        findings,
        [limitation],
        read_level="metadata_only",
        visual_kind="video",
        visual_status="metadata_only",
        visual_fallback_available=bool(_meaningful_video_title(title)),
    )


def _dedupe(items: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        key = str(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
