from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .formatting import _clean_html_text, _shorten


URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"'<>]+)")
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".csv", ".tsv", ".json"}
DOC_EXTENSIONS = {".docx", ".pdf"}
SHEET_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_FILE_EXTENSIONS = TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}


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


@dataclass(frozen=True)
class _SegmentRef:
    kind: str
    name: str = ""
    url: str = ""
    file: str = ""
    file_id: str = ""
    summary: str = ""
    size: int | None = None
    group_id: str = ""
    busid: Any = None

    @property
    def label(self) -> str:
        return self.name or self.summary or _basename_from_ref(self.url or self.file) or self.file_id or self.kind


@dataclass
class _MaterialRequest:
    urls: list[str] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    file_refs: list[_SegmentRef] = field(default_factory=list)
    image_refs: list[_SegmentRef] = field(default_factory=list)
    video_refs: list[_SegmentRef] = field(default_factory=list)
    share_hints: list[str] = field(default_factory=list)
    segment_limitations: list[str] = field(default_factory=list)
    has_image_only: bool = False

    @property
    def has_material(self) -> bool:
        return bool(
            self.urls
            or self.paths
            or self.file_refs
            or self.image_refs
            or self.video_refs
            or self.share_hints
            or self.segment_limitations
        )


def _collect_request(event: dict[str, Any], plain_text: str) -> _MaterialRequest:
    request = _MaterialRequest()
    request.urls.extend(_extract_urls(plain_text))
    request.paths.extend(_extract_paths(plain_text))

    message = event.get("message")
    if isinstance(message, list):
        for segment in message:
            if not isinstance(segment, dict):
                continue
            data = segment.get("data") or {}
            segment_type = segment.get("type")
            if segment_type == "image":
                request.has_image_only = True
                image_ref = _segment_ref("image", data, event)
                if _should_analyze_image(plain_text) or _message_has_only_material(message):
                    request.image_refs.append(image_ref)
            elif segment_type == "file":
                request.file_refs.append(_segment_ref("file", data, event))
            elif segment_type == "video":
                video_ref = _segment_ref("video", data, event)
                request.video_refs.append(video_ref)
                if video_ref.url and _is_bilibili_url(video_ref.url):
                    request.urls.append(video_ref.url)
            elif segment_type == "face":
                face_id = _first_text(data, "id", "face_id")
                request.share_hints.append(f"QQ表情：{face_id}" if face_id else "QQ表情：用户发了一个普通 QQ 表情")
            elif segment_type in {"mface", "marketface"}:
                face_ref = _segment_ref("sticker", data, event)
                if face_ref.url or face_ref.file or face_ref.summary or face_ref.name:
                    request.image_refs.append(face_ref)
                if face_ref.summary or face_ref.name:
                    request.share_hints.append(f"动画表情摘要：{face_ref.summary or face_ref.name}")
            elif segment_type in {"json", "xml", "share"}:
                _collect_share_segment(request, data)
            else:
                request.urls.extend(_extract_urls_from_any(data))

    request.urls = _dedupe(request.urls)
    request.paths = [path for path in _dedupe(request.paths) if str(path)]
    request.image_refs = _dedupe(request.image_refs)
    request.file_refs = _dedupe(request.file_refs)
    request.video_refs = _dedupe(request.video_refs)
    request.share_hints = _dedupe(request.share_hints)
    request.segment_limitations = _dedupe(request.segment_limitations)
    return request

def _segment_ref(kind: str, data: dict[str, Any], event: dict[str, Any]) -> _SegmentRef:
    name = _first_text(data, "name", "file_name", "filename", "title")
    summary = _first_text(data, "summary", "text", "desc", "prompt", "sub_type")
    url = _first_text(data, "url", "file_url", "download_url", "preview")
    file = _first_text(data, "file", "path", "file_path")
    file_id = _first_text(data, "file_id", "id", "fid", "uuid")
    size = _as_positive_int(data.get("size") or data.get("file_size"))
    return _SegmentRef(
        kind=kind,
        name=name,
        url=url,
        file=file,
        file_id=file_id,
        summary=summary,
        size=size,
        group_id=str(event.get("group_id") or ""),
        busid=data.get("busid") or data.get("bus_id"),
    )

def _material_filename_hint(ref: _SegmentRef) -> str:
    for candidate in (ref.name, ref.file, ref.url, ref.summary, ref.file_id):
        basename = _basename_from_ref(candidate)
        if Path(basename).suffix.lower() in SUPPORTED_FILE_EXTENSIONS | VIDEO_EXTENSIONS:
            return basename
    return ref.label

def _message_has_only_material(message: list[Any]) -> bool:
    meaningful_types = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        segment_type = segment.get("type")
        data = segment.get("data") or {}
        if segment_type == "text" and not str(data.get("text") or "").strip():
            continue
        meaningful_types.append(segment_type)
    return bool(meaningful_types) and all(
        segment_type in {"image", "file", "video", "json", "xml", "share", "mface", "marketface"}
        for segment_type in meaningful_types
    )

def _collect_share_segment(request: _MaterialRequest, data: dict[str, Any]) -> None:
    raw = data.get("data") if "data" in data else data
    parsed = _parse_maybe_json(raw)
    values: list[Any] = [data, raw]
    if parsed is not raw:
        values.append(parsed)

    urls: list[str] = []
    hints: list[str] = []
    for value in values:
        urls.extend(_extract_urls_from_any(value))
        hints.extend(_extract_share_hints(value))

    request.urls.extend(urls)
    request.share_hints.extend(hints)
    if hints and not urls:
        request.segment_limitations.append("这条 QQ 分享卡片没有提供可访问链接，只能基于卡片标题/摘要回应。")

def _parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = html.unescape(value).strip()
    if not text:
        return value
    for candidate in (text, unquote(text)):
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return value

def _extract_urls_from_any(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        parsed = _parse_maybe_json(value)
        if parsed is not value:
            urls.extend(_extract_urls_from_any(parsed))
        urls.extend(_extract_urls(value))
    elif isinstance(value, dict):
        for item in value.values():
            urls.extend(_extract_urls_from_any(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_extract_urls_from_any(item))
    return _dedupe(urls)

def _extract_share_hints(value: Any) -> list[str]:
    hints: list[str] = []
    if isinstance(value, str):
        parsed = _parse_maybe_json(value)
        if parsed is not value:
            hints.extend(_extract_share_hints(parsed))
        title = _extract_xmlish_tag(value, "title")
        desc = _extract_xmlish_tag(value, "summary") or _extract_xmlish_tag(value, "desc")
        if title:
            hints.append(f"分享标题：{_shorten(title, 160)}")
        if desc:
            hints.append(f"分享摘要：{_shorten(desc, 220)}")
    elif isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"title", "desc", "description", "summary", "prompt", "tag", "source"}:
                text = _clean_html_text(str(item))
                if text and not text.startswith(("http://", "https://")):
                    label = "分享标题" if key_text == "title" else "分享摘要"
                    hints.append(f"{label}：{_shorten(text, 220)}")
            elif isinstance(item, (dict, list, str)):
                hints.extend(_extract_share_hints(item))
    elif isinstance(value, list):
        for item in value:
            hints.extend(_extract_share_hints(item))
    return _dedupe(hints)

def _extract_xmlish_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text or "", flags=re.IGNORECASE | re.DOTALL)
    return _clean_html_text(match.group(1)) if match else ""

def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""

def _as_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

def _extension_for_material(name_or_url: str, content_type: str = "") -> str:
    suffix = Path(_basename_from_ref(name_or_url)).suffix.lower()
    if suffix in SUPPORTED_FILE_EXTENSIONS | VIDEO_EXTENSIONS:
        return suffix

    normalized_type = (content_type or "").split(";")[0].strip().lower()
    return {
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
    }.get(normalized_type, "")

def _basename_from_ref(ref: str) -> str:
    ref = str(ref or "").strip()
    if not ref:
        return ""
    parsed = urlparse(ref)
    if parsed.scheme in {"http", "https"}:
        return unquote(Path(parsed.path).name)
    return unquote(Path(ref).name)

def _is_bilibili_url(url: str) -> bool:
    parsed = urlparse(url or "")
    domain = parsed.netloc.lower()
    return "bilibili.com" in domain or "b23.tv" in domain

def _onebot_material_actions(ref: _SegmentRef) -> list[tuple[str, dict[str, Any]]]:
    file_key = ref.file_id or ref.file
    if not file_key:
        return []

    actions: list[tuple[str, dict[str, Any]]] = []
    if ref.kind == "image":
        actions.append(("get_image", {"file": file_key}))
        actions.append(("get_file", {"file": file_key}))
    elif ref.kind in {"file", "video"}:
        actions.append(("get_file", {"file_id": file_key}))
        actions.append(("get_file", {"file": file_key}))
        actions.append(("get_private_file_url", {"file_id": file_key}))
        if ref.group_id:
            params: dict[str, Any] = {"group_id": _int_or_original(ref.group_id), "file_id": file_key}
            if ref.busid is not None:
                params["busid"] = ref.busid
            actions.append(("get_group_file_url", params))
            group_params: dict[str, Any] = {"group": _int_or_original(ref.group_id), "file_id": file_key}
            if ref.busid is not None:
                group_params["busid"] = ref.busid
            actions.append(("get_group_file_url", group_params))
    return actions

def _resolve_material_from_action_response(response: dict[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(response, dict):
        return None
    payload: Any = response.get("data") if "data" in response else response
    urls = _extract_urls_from_any(payload)
    if urls:
        return urls[0], ""
    path = _extract_path_from_any(payload)
    if path:
        return "", path
    return None

def _extract_path_from_any(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        parsed = urlparse(text)
        if parsed.scheme == "file":
            return unquote(parsed.path.lstrip("/")) if re.match(r"^/[A-Za-z]:/", parsed.path) else unquote(parsed.path)
        if WINDOWS_PATH_RE.fullmatch(text) or Path(text).is_absolute():
            return text
        return ""
    if isinstance(value, dict):
        for key in ("path", "file", "file_path", "download_path", "absolute_path"):
            item = value.get(key)
            if isinstance(item, str):
                path = _extract_path_from_any(item)
                if path:
                    return path
        for item in value.values():
            path = _extract_path_from_any(item)
            if path:
                return path
    elif isinstance(value, list):
        for item in value:
            path = _extract_path_from_any(item)
            if path:
                return path
    return ""

def _int_or_original(value: Any) -> int | str:
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)

def _extract_urls(text: str) -> list[str]:
    return [match.rstrip("，。！？!?") for match in URL_RE.findall(text or "")]

def _extract_paths(text: str) -> list[Path]:
    paths = []
    for match in WINDOWS_PATH_RE.findall(text or ""):
        cleaned = match.strip().rstrip("，。！？!?")
        suffix = Path(cleaned).suffix.lower()
        if suffix in TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            paths.append(Path(cleaned))
    return paths

def _should_analyze_image(text: str) -> bool:
    return any(
        word in text
        for word in (
            "分析图片",
            "分析这张",
            "评价图片",
            "评价这张",
            "看图",
            "看看图",
            "看看这张",
            "这张图",
            "这张照片",
            "这张截图",
            "图片内容",
            "图里",
            "截图",
            "帮我看",
            "好看吗",
            "怎么样",
            "咋样",
            "如何",
            "评价一下",
            "总结图片",
        )
    )

def _classify_category(text: str, request: _MaterialRequest) -> str:
    if request.image_refs or request.has_image_only:
        return "日常生活乐趣"
    if any(("bilibili.com" in urlparse(url).netloc.lower() or "b23.tv" in urlparse(url).netloc.lower()) for url in request.urls):
        if not any(word in text for word in ("论文", "研究", "数据", "报告", "权威", "引用", "指标", "统计")):
            return "日常生活乐趣"
    research_words = (
        "学术",
        "论文",
        "研究",
        "数据",
        "表格",
        "报告",
        "严谨",
        "准确",
        "权威",
        "实时",
        "资料",
        "引用",
        "来源",
        "指标",
        "统计",
        "总结",
    )
    if any(word in text for word in research_words):
        return "生活学术研究"
    if any(path.suffix.lower() in TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS for path in request.paths):
        return "生活学术研究"
    return "日常生活乐趣"
