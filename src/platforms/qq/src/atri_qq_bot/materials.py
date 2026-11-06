"""OneBot segments and file actions translated into core material contracts."""
from __future__ import annotations
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from dataclasses import dataclass
from typing import Any
from atri_bot.toolbox import ToolAnalyzer
from atri_bot.toolbox.request_collection import (
    MaterialRef, MaterialRequest, collect_text_material, _dedupe, _extract_urls,
    _is_bilibili_url, WINDOWS_PATH_RE,
)
from atri_bot.toolbox.formatting import _clean_html_text, _shorten


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


@dataclass(frozen=True)
class QQMaterialRef(MaterialRef):
    group_id: str = ""
    busid: Any = None


def collect_onebot_material(event: dict[str, Any], plain_text: str) -> MaterialRequest:
    request = collect_text_material(plain_text)

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


def _segment_ref(kind: str, data: dict[str, Any], event: dict[str, Any]) -> QQMaterialRef:
    name = _first_text(data, "name", "file_name", "filename", "title")
    summary = _first_text(data, "summary", "text", "desc", "prompt", "sub_type")
    url = _first_text(data, "url", "file_url", "download_url", "preview")
    file = _first_text(data, "file", "path", "file_path")
    file_id = _first_text(data, "file_id", "id", "fid", "uuid")
    size = _as_positive_int(data.get("size") or data.get("file_size"))
    return QQMaterialRef(
        kind=kind,
        name=name,
        url=url,
        file=file,
        resource_id=file_id,
        summary=summary,
        size=size,
        group_id=str(event.get("group_id") or ""),
        busid=data.get("busid") or data.get("bus_id"),
    )


def _collect_share_segment(request: MaterialRequest, data: dict[str, Any]) -> None:
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


def _onebot_material_actions(ref: QQMaterialRef) -> list[tuple[str, dict[str, Any]]]:
    file_key = ref.resource_id or ref.file
    if not file_key:
        return []

    actions: list[tuple[str, dict[str, Any]]] = []
    if ref.kind in {"image", "sticker"}:
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
    path = _extract_path_from_any(payload)
    return (urls[0] if urls else "", path) if urls or path else None


def _int_or_original(value: Any) -> int | str:
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


class QQToolAnalyzer(ToolAnalyzer):
    """QQ translates its event format; analysis itself stays in the core."""

    async def analyze(self, event, plain_text, action_caller=None, *, allow_vision=True):
        if isinstance(event, MaterialRequest):
            return await super().analyze(event, plain_text, action_caller, allow_vision=allow_vision)
        request = collect_onebot_material(event, plain_text)

        async def resolve(ref):
            for action, params in _onebot_material_actions(ref):
                try:
                    response = await action_caller(action, params)
                except Exception:
                    continue
                material = _resolve_material_from_action_response(response)
                if material:
                    yield material

        return await super().analyze(request, plain_text,
            resolve if action_caller else None, allow_vision=allow_vision)
