from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import hashlib
import io
import json
import re
import time
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .toolbox_parts import formatting as _toolbox_formatting
from .toolbox_parts import media_probe as _toolbox_media_probe
from .toolbox_parts import office_docs as _toolbox_office_docs
from .toolbox_parts import request_collection as _toolbox_request_collection
from .toolbox_parts.ocr import OcrExtraction, extract_image_text
from .prompting import load_prompt
from .runtime.inference_lock import inference_resource_lease
from .runtime.paths import PROJECT_ROOT


URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"'<>]+)")
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".csv", ".tsv", ".json"}
DOC_EXTENSIONS = {".docx", ".pdf"}
SHEET_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_FILE_EXTENSIONS = TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}
MAX_TEXT_CHARS = 2800

VISUAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "direct_answer": {"type": "string"},
        "visible_text": {"type": "string"},
        "subjects": {"type": "string"},
        "identity": {"type": "string"},
        "emotion": {"type": "string"},
        "social_intent": {"type": "string"},
        "evidence": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "needs_web_verification": {"type": "boolean"},
        "search_keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "direct_answer",
        "visible_text",
        "subjects",
        "identity",
        "emotion",
        "social_intent",
        "evidence",
        "confidence",
        "needs_web_verification",
        "search_keywords",
    ],
    "additionalProperties": False,
}

OneBotActionCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class _VisionModelResponse:
    content: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolAnalysisResult:
    category: str
    style: str
    sources: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    read_level: str = "full_content"
    visual_data: bytes | None = field(default=None, repr=False, compare=False)
    visual_source: str = ""
    visual_kind: str = ""
    visual_status: str = ""
    visual_ocr_confidence: float = 0.0

    def requires_visual_fail_safe(self) -> bool:
        return bool(
            self.visual_kind
            and self.visual_status in {"partial", "ocr_only", "metadata_only", "unavailable"}
        )

    def visual_failure_reply(self) -> str:
        material = "这个视频" if self.visual_kind == "video" else "这张图"
        text_location = "视频抽样帧" if self.visual_kind == "video" else "图片"
        ocr_text = ""
        summary = ""
        for finding in self.findings:
            if finding.startswith("独立 OCR 文字："):
                ocr_text = finding.split("：", 1)[1].strip()
            elif "动画表情摘要：" in finding:
                summary = finding.split("动画表情摘要：", 1)[1].strip().rstrip("。")
        if ocr_text:
            return (
                f"我目前只可靠读到{text_location}里的文字：“{_shorten(ocr_text, 220)}”。"
                f"{material}的画面没有稳定识别，所以人物、动作和含义我不乱猜。"
            )
        if summary:
            return (
                f"我目前只拿到 QQ 提供的表情摘要：“{_shorten(summary, 160)}”。"
                "原图没有稳定识别，具体画面我不乱猜。"
            )
        return (
            f"{material}这次没有稳定识别出来，我不乱猜画面。"
            "你可以重新发送原图，或者稍后再试一次。"
        )

    def needs_grounding_repair(self, reply_text: str) -> bool:
        text = re.sub(r"\s+", "", str(reply_text or ""))
        if not text or self.read_level == "full_content":
            return False
        if self.requires_visual_fail_safe():
            allowed_ocr = "".join(
                finding.split("：", 1)[1]
                for finding in self.findings
                if finding.startswith("独立 OCR 文字：") and "：" in finding
            )
            visual_claims = (
                "画面里",
                "图里是",
                "图片里是",
                "人物是",
                "角色是",
                "看起来在",
                "表情是",
                "动作是",
            )
            if any(claim in text for claim in visual_claims):
                return True
            if "图中文字" in text and not allowed_ocr:
                return True
        if self.read_level == "partial_content":
            return any(
                claim in text
                for claim in ("看完整个", "看完视频", "读完全文", "完整内容里")
            )
        unread_content_claims = (
            "点开看了",
            "点进去看",
            "看完视频",
            "视频里说",
            "视频里讲",
            "画面里",
            "镜头里",
            "听完了",
            "听起来",
            "旋律",
            "音色",
            "字幕里",
            "全文里",
            "文档里写",
            "图片里",
            "图里",
            "盯着图",
            "瞄了眼",
            "看着图片",
            "看着表情",
            "看不太清",
            "看不清",
            "像素低",
            "太糊",
        )
        return any(claim in text for claim in unread_content_claims)

    def prompt_context(self) -> str:
        source_text = "；".join(self.sources[:6]) or "用户消息"
        finding_text = "\n".join(f"- {item}" for item in self.findings[:8]) or "- 暂无可用正文"
        limitation_text = "\n".join(f"- {item}" for item in self.limitations[:5]) or "- 无明显限制"
        visibility_rule = ""
        if self.read_level == "metadata_only":
            visibility_rule = (
                "\n可见性限制：本轮材料只读到标题、分享卡片、文件名、QQ 摘要或少量元数据；"
                "这不等于看完视频、看清图片、读完整文档或核验全部内容。"
                "回复时必须自然说明“我只能基于标题/卡片/摘要判断”，"
                "禁止说“我看完了视频”“视频里说”“我看到画面”“文档写了很多细节”等未读取事实。"
            )
        elif self.read_level == "partial_content":
            visibility_rule = (
                "\n可见性限制：本轮只读取到部分正文、公开简介、公开字幕或局部内容；"
                "可以基于可见部分分析，但必须避免断言完整视频/全文的未读细节。"
            )
        visual_rule = ""
        if self.visual_kind or any(
            item.startswith(("图片内容分析", "表情包情绪分析", "图片信息", "表情包信息"))
            for item in self.findings
        ):
            if self.requires_visual_fail_safe():
                visual_rule = (
                    "\n视觉证据状态：本轮没有取得可靠的完整画面理解。"
                    "只能复述明确列出的独立 OCR 或 QQ 摘要；禁止描述人物、动作、场景、"
                    "表情、颜色、身份或图片含义，禁止用聊天记忆补全。"
                    "应明确说本次识别不稳定，不得为了自然聊天而猜图。"
                )
            else:
                visual_rule = (
                    "\n以下视觉结果是本轮当前图片唯一可用的画面证据，优先级高于用户画像、兴趣、"
                    "旧图片、旧助手回复和此前聊天猜测。"
                    "回复时优先围绕当前画面或表情情绪回复。"
                    "人物身份、画中文字和画面细节只能来自本轮视觉结果或本轮联网核验，"
                    "不得用聊天记忆补全或改写。"
                    "\n用户问人物、文字、含义或情绪时必须直接回答，不要反问用户想让你识别还是描述。"
                    "视觉结果要求联网核验时直接使用搜索工具，不要先索要搜索许可。"
                )
        return (
            "你已获得用户发来的外部材料读取结果。不要说“我调用了工具”，不要输出技术流程；"
            "只把这些信息自然用于回答。"
            f"\n分类：{self.category}。"
            f"\n回复风格：{self.style}。"
            "\n风格要求：日常生活乐趣=轻松、有趣、可以短短吐槽；生活学术研究=准确、严谨、先给结论和依据。"
            "\n如果用户只是分享、让你看看或评价，就先给自然短评；如果用户要求深度分析、总结、数据分析或报告，就按结论、依据、风险/建议组织。"
            "\n禁止把没有读取到的内容编造成事实；不确定就说明只能基于当前可见信息判断。"
            f"{visibility_rule}"
            f"{visual_rule}"
            f"\n来源：{source_text}"
            f"\n可用信息：\n{finding_text}"
            f"\n限制：\n{limitation_text}"
        )

    def fallback_reply(self) -> str:
        if self.requires_visual_fail_safe():
            return self.visual_failure_reply()
        if self.category == "生活学术研究":
            intro = "我先按能读到的信息严谨说："
        else:
            intro = "我先按能看到的内容吐槽一句："
        body = "；".join(self.findings[:3]) or "这份材料目前只有很少的可见信息。"
        if self.limitations:
            return f"{intro}{body} 不确定的地方我不乱编：{self.limitations[0]}"
        return f"{intro}{body}"


class ToolAnalyzer:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.enabled = bool(getattr(config, "toolbox_enabled", True))
        self.timeout = float(getattr(config, "toolbox_timeout_seconds", 8.0))
        self.max_bytes = int(getattr(config, "toolbox_max_bytes", 2_000_000))
        self.max_document_bytes = int(getattr(config, "toolbox_max_document_bytes", 20_000_000))
        self.max_media_bytes = int(getattr(config, "toolbox_max_media_bytes", 80_000_000))
        self.vision_enabled = bool(getattr(config, "toolbox_vision_enabled", False))
        self.vision_model = str(
            getattr(config, "toolbox_vision_model", "") or getattr(config, "openai_model", "")
        ).strip()
        self.vision_fallback_model = str(
            getattr(config, "toolbox_vision_fallback_model", "") or ""
        ).strip()
        self.vision_base_url = str(
            getattr(config, "toolbox_vision_base_url", "") or getattr(config, "openai_base_url", "")
        ).rstrip("/")
        self.vision_api_key = getattr(config, "toolbox_vision_api_key", None) or getattr(config, "openai_api_key", None)
        self.vision_max_bytes = int(getattr(config, "toolbox_vision_max_bytes", 8_000_000))
        self.vision_retry_count = max(
            0,
            min(3, int(getattr(config, "toolbox_vision_retry_count", 1))),
        )
        self.vision_resource_wait_seconds = max(
            5.0,
            min(
                300.0,
                float(
                    getattr(
                        config,
                        "toolbox_vision_resource_wait_seconds",
                        120.0,
                    )
                ),
            ),
        )
        self.vision_unload_other_ollama_models = bool(
            getattr(
                config,
                "toolbox_vision_unload_other_ollama_models",
                False,
            )
        )
        self.ocr_enabled = bool(getattr(config, "toolbox_ocr_enabled", False))
        self.chat_model = str(getattr(config, "openai_model", "") or "").strip()
        self.chat_base_url = str(
            getattr(config, "openai_base_url", "") or ""
        ).rstrip("/")
        self.video_frame_analysis_enabled = bool(
            getattr(config, "toolbox_video_frame_analysis_enabled", True)
        )
        self.video_max_frames = max(1, min(8, int(getattr(config, "toolbox_video_max_frames", 4))))
        self._vision_event_log = PROJECT_ROOT / "logs" / "vision-events.jsonl"
        self._vision_lock = asyncio.Lock()

    async def analyze(
        self,
        event: dict[str, Any],
        plain_text: str,
        action_caller: OneBotActionCaller | None = None,
    ) -> ToolAnalysisResult | None:
        if not self.enabled:
            return None

        request = _collect_request(event, plain_text)
        if not request.has_material:
            return None

        findings: list[str] = []
        limitations: list[str] = []
        sources: list[str] = []
        read_levels: list[str] = []
        visual_data: bytes | None = None
        visual_source = ""
        visual_kind = ""
        visual_statuses: list[str] = []
        visual_ocr_confidence = 0.0

        def track_visual_result(result: ToolAnalysisResult) -> None:
            nonlocal visual_data
            nonlocal visual_source
            nonlocal visual_kind
            nonlocal visual_ocr_confidence
            if not result.visual_kind:
                return
            visual_kind = result.visual_kind
            visual_statuses.append(result.visual_status or "unavailable")
            visual_ocr_confidence = max(
                visual_ocr_confidence,
                float(result.visual_ocr_confidence or 0.0),
            )
            if result.visual_data:
                visual_data = result.visual_data
                visual_source = result.visual_source

        for url in request.urls[:4]:
            result = await self._analyze_url(url)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        for path in request.paths[:4]:
            result = await self._analyze_path(path)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        for file_ref in request.file_refs[:3]:
            result = await self._analyze_file_ref(file_ref, action_caller)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        for image_ref in request.image_refs[:3]:
            result = await self._analyze_image_ref(
                image_ref,
                action_caller,
                user_question=plain_text,
            )
            sources.extend(result.sources)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            visual_findings = list(result.findings)
            verification_findings: list[str] = []
            verification_succeeded = False
            visual_search_query = _visual_search_query("\n".join(visual_findings))
            if visual_search_query:
                try:
                    from .llm_tools.web_search_tool import search_web

                    search_result = await search_web(
                        {
                            "query": visual_search_query,
                            "max_results": 3,
                        },
                        self.config,
                    )
                    if search_result.startswith("搜索失败："):
                        limitations.append(
                            f"视觉身份联网核验未成功：{_shorten(search_result, 300)}"
                        )
                    elif _search_result_supports_query(
                        search_result,
                        visual_search_query,
                    ):
                        verification_findings.append(
                            "视觉身份联网核验："
                            f"{_shorten(search_result, 2400)}"
                        )
                        verification_succeeded = True
                        sources.append(f"网页核验：{visual_search_query}")
                    else:
                        limitations.append(
                            "联网搜索没有返回与视觉关键词直接匹配的结果，"
                            "不能把无关网页当作人物身份依据。"
                        )
                except Exception as exc:
                    limitations.append(
                        f"视觉身份联网核验未成功：{_exception_summary(exc)}"
                    )
                if not verification_succeeded:
                    visual_findings = [
                        _demote_unverified_visual_identity(finding)
                        for finding in visual_findings
                    ]
            findings.extend(visual_findings)
            findings.extend(verification_findings)
            track_visual_result(result)

        for video_ref in request.video_refs[:2]:
            result = await self._analyze_video_ref(video_ref, action_caller)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        findings.extend(request.share_hints[:6])
        limitations.extend(request.segment_limitations[:4])
        if request.share_hints or request.segment_limitations:
            read_levels.append("metadata_only")

        if not findings and not limitations:
            return None

        category = _classify_category(plain_text, request)
        style = "准确严谨" if category == "生活学术研究" else "抽象有趣"
        return ToolAnalysisResult(
            category=category,
            style=style,
            sources=_dedupe(sources),
            findings=_dedupe(findings),
            limitations=_dedupe(limitations),
            read_level=_merge_read_levels(read_levels),
            visual_data=visual_data,
            visual_source=visual_source,
            visual_kind=visual_kind,
            visual_status=_merge_visual_statuses(visual_statuses),
            visual_ocr_confidence=visual_ocr_confidence,
        )

    async def analyze_visual_followup(
        self,
        previous: ToolAnalysisResult,
        question: str,
    ) -> ToolAnalysisResult | None:
        if not previous.visual_data:
            return None
        prompt = _visual_prompt_for_kind(
            previous.visual_kind or "auto",
            question,
        )
        return await self._analyze_image_bytes(
            previous.visual_data,
            previous.visual_source or "上一张图片",
            visual_kind=previous.visual_kind or "auto",
            vision_prompt=prompt,
        )

    async def _analyze_url(self, url: str) -> ToolAnalysisResult:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if "bilibili.com" in domain or "b23.tv" in domain:
            return await self._analyze_bilibili(url)
        return await self._analyze_webpage(url)

    async def _analyze_webpage(self, url: str) -> ToolAnalysisResult:
        try:
            data, final_url, content_type = await self._fetch_url(url)
        except Exception as exc:
            return ToolAnalysisResult(
                category="生活学术研究",
                style="准确严谨",
                sources=[url],
                limitations=[f"网页暂时读取失败：{exc}"],
                read_level="metadata_only",
            )

        if content_type.startswith("image/"):
            return await self._analyze_image_bytes(data, final_url)
        ext = _extension_for_material(final_url, content_type)
        if ext in DOC_EXTENSIONS | SHEET_EXTENSIONS | VIDEO_EXTENSIONS | TEXT_EXTENSIONS:
            return await self._analyze_file_bytes(data, final_url, _basename_from_ref(final_url), content_type)

        text = _decode_bytes(data)
        title = _extract_html_title(text)
        desc = _extract_meta_description(text)
        body = _extract_readable_text(text)
        findings = []
        if title:
            findings.append(f"网页标题：{title}")
        if desc:
            findings.append(f"网页简介：{desc}")
        if body:
            findings.append(f"网页正文摘要：{_shorten(body, 900)}")
        if _looks_authoritative(final_url):
            findings.append("来源域名看起来偏官方/机构/学术，可优先作为依据，但仍需核对具体页面内容。")
        return ToolAnalysisResult(
            category="生活学术研究",
            style="准确严谨",
            sources=[final_url],
            findings=findings,
            limitations=[] if findings else ["网页可访问，但正文很少或被脚本动态加载。"],
            read_level="full_content" if body else "partial_content",
        )

    async def _analyze_bilibili(self, url: str) -> ToolAnalysisResult:
        findings: list[str] = []
        limitations: list[str] = []
        sources = [url]

        try:
            data, final_url, _ = await self._fetch_url(url)
            html_text = _decode_bytes(data)
            sources = [final_url]
        except Exception as exc:
            html_text = ""
            limitations.append(f"B站页面暂时读取失败：{exc}")

        bvid = _extract_bvid(url) or _extract_bvid(html_text)
        title = _extract_html_title(html_text)
        desc = _extract_meta_description(html_text)

        if bvid:
            findings.append(f"B站视频 BV 号：{bvid}")
            api_result = await self._fetch_bilibili_api(bvid)
            findings.extend(api_result.findings)
            limitations.extend(api_result.limitations)
        if title:
            findings.append(f"视频页标题：{_clean_bilibili_title(title)}")
        if desc:
            findings.append(f"视频页简介：{desc}")
        if not bvid:
            limitations.append("没有识别到 BV 号，只能基于页面标题/简介判断。")
        limitations.append("目前不会自动下载视频画面；能读到公开标题、简介、分区、统计和公开字幕时才会分析。")
        read_level = "partial_content" if any("公开字幕摘要" in item for item in findings) else "metadata_only"
        return ToolAnalysisResult(
            category="日常生活乐趣",
            style="抽象有趣",
            sources=sources,
            findings=_dedupe(findings),
            limitations=_dedupe(limitations),
            read_level=read_level,
        )

    async def _fetch_bilibili_api(self, bvid: str) -> ToolAnalysisResult:
        findings: list[str] = []
        limitations: list[str] = []
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            data, _, _ = await self._fetch_url(url)
            payload = json.loads(_decode_bytes(data))
            info = payload.get("data") or {}
        except Exception as exc:
            return ToolAnalysisResult(
                category="日常生活乐趣",
                style="抽象有趣",
                sources=[url],
                limitations=[f"B站公开 API 暂时读取失败：{exc}"],
                read_level="metadata_only",
            )

        if info.get("title"):
            findings.append(f"公开标题：{info.get('title')}")
        owner = info.get("owner") or {}
        if owner.get("name"):
            findings.append(f"UP 主：{owner.get('name')}")
        if info.get("tname"):
            findings.append(f"分区：{info.get('tname')}")
        if info.get("desc"):
            findings.append(f"简介摘要：{_shorten(str(info.get('desc')), 500)}")
        stat = info.get("stat") or {}
        stat_bits = []
        for key, label in (("view", "播放"), ("danmaku", "弹幕"), ("like", "点赞"), ("coin", "投币"), ("favorite", "收藏")):
            value = stat.get(key)
            if isinstance(value, int):
                stat_bits.append(f"{label}{value}")
        if stat_bits:
            findings.append("公开数据：" + "，".join(stat_bits))
        pages = info.get("pages") or []
        if pages:
            findings.append(f"分 P 数：{len(pages)}；首 P：{pages[0].get('part') or '未命名'}")
            cid = pages[0].get("cid")
            if cid:
                subtitle = await self._fetch_bilibili_subtitle(bvid, cid)
                findings.extend(subtitle.findings)
                limitations.extend(subtitle.limitations)
        return ToolAnalysisResult(
            category="日常生活乐趣",
            style="抽象有趣",
            sources=[url],
            findings=findings,
            limitations=limitations,
            read_level="partial_content" if any("公开字幕摘要" in item for item in findings) else "metadata_only",
        )

    async def _fetch_bilibili_subtitle(self, bvid: str, cid: Any) -> ToolAnalysisResult:
        url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
        try:
            data, _, _ = await self._fetch_url(url)
            payload = json.loads(_decode_bytes(data))
            subtitles = (((payload.get("data") or {}).get("subtitle") or {}).get("subtitles") or [])
        except Exception as exc:
            return ToolAnalysisResult(
                category="日常生活乐趣",
                style="抽象有趣",
                limitations=[f"字幕列表暂时读取失败：{exc}"],
                read_level="metadata_only",
            )
        if not subtitles:
            return ToolAnalysisResult(
                category="日常生活乐趣",
                style="抽象有趣",
                limitations=["这个视频没有读到公开字幕。"],
                read_level="metadata_only",
            )
        subtitle_url = subtitles[0].get("subtitle_url") or ""
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url
        if not subtitle_url:
            return ToolAnalysisResult(
                category="日常生活乐趣",
                style="抽象有趣",
                limitations=["字幕列表存在，但没有可读取字幕地址。"],
                read_level="metadata_only",
            )
        try:
            data, _, _ = await self._fetch_url(subtitle_url)
            payload = json.loads(_decode_bytes(data))
            body = payload.get("body") or []
            subtitle_text = " ".join(str(item.get("content") or "") for item in body)
        except Exception as exc:
            return ToolAnalysisResult(
                category="日常生活乐趣",
                style="抽象有趣",
                limitations=[f"公开字幕暂时读取失败：{exc}"],
                read_level="metadata_only",
            )
        if not subtitle_text.strip():
            return ToolAnalysisResult(
                category="日常生活乐趣",
                style="抽象有趣",
                limitations=["公开字幕为空。"],
                read_level="metadata_only",
            )
        return ToolAnalysisResult(
            category="日常生活乐趣",
            style="抽象有趣",
            findings=[f"公开字幕摘要：{_shorten(subtitle_text, 900)}"],
            read_level="partial_content",
        )

    async def _analyze_path(self, path: Path) -> ToolAnalysisResult:
        if not path.exists():
            return ToolAnalysisResult(
                category="生活学术研究",
                style="准确严谨",
                sources=[str(path)],
                limitations=["本地文件路径不存在，无法读取。"],
                read_level="metadata_only",
            )
        ext = path.suffix.lower()
        limit = self._byte_limit_for_ext(ext)
        if path.stat().st_size > limit:
            return ToolAnalysisResult(
                category="生活学术研究",
                style="准确严谨",
                sources=[str(path)],
                limitations=[f"文件超过读取上限 {limit} 字节，暂不读取。"],
                read_level="metadata_only",
            )
        return await self._analyze_file_bytes(path.read_bytes(), str(path), path.name)

    async def _analyze_file_bytes(
        self,
        data: bytes,
        source: str,
        filename: str = "",
        content_type: str = "",
    ) -> ToolAnalysisResult:
        ext = _extension_for_material(filename, content_type) or _extension_for_material(source, content_type)
        limit = self._byte_limit_for_ext(ext)
        if len(data) > limit:
            return ToolAnalysisResult(
                category="生活学术研究",
                style="准确严谨",
                sources=[source],
                limitations=[f"文件超过读取上限 {limit} 字节，暂不读取。"],
                read_level="metadata_only",
            )

        if ext in IMAGE_EXTENSIONS:
            return await self._analyze_image_bytes(data, source)
        if ext in VIDEO_EXTENSIONS:
            return await self._analyze_video_bytes(data, source, filename or _basename_from_ref(source))
        if ext in TEXT_EXTENSIONS:
            return self._analyze_text_bytes(data, source, ext)
        if ext in DOC_EXTENSIONS:
            if ext == ".pdf":
                return self._analyze_pdf_bytes(data, source)
            return self._analyze_docx_bytes(data, source)
        if ext in SHEET_EXTENSIONS:
            return self._analyze_xlsx_bytes(data, source)
        if not ext and _looks_like_text_bytes(data):
            return self._analyze_text_bytes(data, source, ".txt")
        return ToolAnalysisResult(
            category="生活学术研究",
            style="准确严谨",
            sources=[source],
            findings=[f"收到文件：{filename or _basename_from_ref(source) or source}。"] if filename else [],
            limitations=[f"暂不支持读取 {ext or '无扩展名'} 文件；可以先发文本、CSV、DOCX、PDF、XLSX、常见图片或视频。"],
            read_level="metadata_only",
        )

    def _analyze_text_file(self, path: Path) -> ToolAnalysisResult:
        return self._analyze_text_bytes(path.read_bytes(), str(path), path.suffix.lower())

    def _analyze_text_bytes(self, data: bytes, source: str, ext: str) -> ToolAnalysisResult:
        text = _decode_bytes(data)
        if ext in {".csv", ".tsv"}:
            delimiter = "\t" if ext == ".tsv" else ","
            rows = [
                [cell.strip() for cell in row]
                for row in csv.reader(io.StringIO(text), delimiter=delimiter)
                if any(str(cell).strip() for cell in row)
            ]
            if not rows:
                return ToolAnalysisResult(
                    "生活学术研究",
                    "准确严谨",
                    [source],
                    limitations=["表格文件没有读到有效行。"],
                )
            findings = _summarize_table_rows(rows, "表格文件")
            return ToolAnalysisResult("生活学术研究", "准确严谨", [source], findings)
        if ext == ".json":
            try:
                parsed = json.loads(text)
                return ToolAnalysisResult(
                    "生活学术研究",
                    "准确严谨",
                    [source],
                    [_summarize_json(parsed)],
                )
            except json.JSONDecodeError:
                pass
        if not text.strip():
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                limitations=["文档是空文本或没有读到可用正文。"],
            )
        return ToolAnalysisResult(
            "生活学术研究",
            "准确严谨",
            [source],
            [f"文档摘要：{_shorten(text, 1200)}"],
        )

    def _analyze_docx(self, path: Path) -> ToolAnalysisResult:
        return self._analyze_docx_bytes(path.read_bytes(), str(path))

    def _analyze_docx_bytes(self, data: bytes, source: str) -> ToolAnalysisResult:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                parts: list[tuple[str, str]] = []
                for name in _docx_text_part_names(archive):
                    try:
                        text = _docx_xml_to_text(archive.read(name))
                    except Exception:
                        continue
                    if text:
                        parts.append((name, text))
            text = "\n".join(part_text for _, part_text in parts)
        except Exception as exc:
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                limitations=[f"DOCX 读取失败：{exc}"],
            )
        if not text.strip():
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                limitations=["DOCX 文件没有读到正文；可能是图片扫描版、加密文档，或正文在暂不支持的嵌入对象里。"],
            )
        findings = [
            f"DOCX 文档：读取到 {len(parts)} 个文本部件，约 {len(text)} 字。",
            f"DOCX 摘要：{_shorten(text, 1200)}",
        ]
        return ToolAnalysisResult(
            "生活学术研究",
            "准确严谨",
            [source],
            findings,
        )

    def _analyze_pdf_bytes(self, data: bytes, source: str) -> ToolAnalysisResult:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            page_texts = []
            for page in reader.pages[:20]:
                page_texts.append(page.extract_text() or "")
            text = "\n".join(piece.strip() for piece in page_texts if piece.strip())
            page_count = len(reader.pages)
        except Exception as exc:
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                limitations=[f"PDF 读取失败：{exc}"],
            )
        if not text.strip():
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                findings=[f"PDF 文档：共 {page_count} 页。"],
                limitations=["PDF 没有提取到可复制文字；可能是扫描图片版，需要 OCR 才能完整识别。"],
            )
        return ToolAnalysisResult(
            "生活学术研究",
            "准确严谨",
            [source],
            [
                f"PDF 文档：共 {page_count} 页，已读取前 {min(page_count, 20)} 页可复制文字。",
                f"PDF 摘要：{_shorten(text, 1400)}",
            ],
        )

    def _analyze_xlsx(self, path: Path) -> ToolAnalysisResult:
        return self._analyze_xlsx_bytes(path.read_bytes(), str(path))

    def _analyze_xlsx_bytes(self, data: bytes, source: str) -> ToolAnalysisResult:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                shared = _read_xlsx_shared_strings(archive)
                sheets = _read_xlsx_sheet_refs(archive)
                sheet_rows = [
                    (display_name, _read_xlsx_sheet_rows(archive, sheet_path, shared))
                    for display_name, sheet_path in sheets
                ]
        except Exception as exc:
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                limitations=[f"XLSX 读取失败：{exc}"],
            )
        non_empty = [(name, rows) for name, rows in sheet_rows if rows]
        if not non_empty:
            return ToolAnalysisResult(
                "生活学术研究",
                "准确严谨",
                [source],
                limitations=["XLSX 文件没有读到有效单元格。"],
            )
        total_data_rows = sum(max(0, len(rows) - 1) for _, rows in non_empty)
        findings = [f"Excel 表格：读取到 {len(non_empty)} 个工作表，总计约 {total_data_rows} 行数据。"]
        for name, rows in non_empty[:3]:
            findings.extend(_summarize_table_rows(rows, f"工作表 {name}", include_samples=len(findings) < 5))
        return ToolAnalysisResult("生活学术研究", "准确严谨", [source], findings)

    async def _analyze_file_ref(
        self,
        file_ref: _SegmentRef,
        action_caller: OneBotActionCaller | None,
    ) -> ToolAnalysisResult:
        material = await self._resolve_ref_material(file_ref, action_caller)
        if material:
            data, source, content_type = material
            return await self._analyze_file_bytes(data, source, file_ref.label, content_type)

        return ToolAnalysisResult(
            "生活学术研究",
            "准确严谨",
            [file_ref.label],
            [f"收到文件：{file_ref.label}。"],
            ["NapCat 没有提供可读取的下载地址或本地文件路径，只能基于文件名判断。"],
            read_level="metadata_only",
        )

    async def _analyze_image_ref(
        self,
        image_ref: _SegmentRef,
        action_caller: OneBotActionCaller | None,
        user_question: str = "",
    ) -> ToolAnalysisResult:
        visual_kind = _classify_visual_material(None, image_ref.label, image_ref)
        material = await self._resolve_ref_material(image_ref, action_caller)
        if material:
            data, source, _ = material
            return await self._analyze_image_bytes(
                data,
                source,
                visual_kind=visual_kind,
                image_ref=image_ref,
                vision_prompt=_visual_prompt_for_kind(visual_kind, user_question),
            )

        if visual_kind == "sticker":
            findings = [f"收到表情包：{image_ref.label}。"]
            if image_ref.summary or image_ref.name:
                findings.append(f"表情包情绪分析：动画表情摘要：{image_ref.summary or image_ref.name}。")
            return ToolAnalysisResult(
                "日常生活乐趣",
                "抽象有趣",
                [image_ref.label],
                findings,
                ["没有拿到表情包原图，只能基于 QQ 摘要判断情绪和社交意图，不要编造具体画面。"],
                read_level="metadata_only",
                visual_source=image_ref.label,
                visual_kind="sticker",
                visual_status="metadata_only",
            )

        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [image_ref.label],
            [f"收到图片：{image_ref.label}。"],
            ["没有拿到图片下载地址，只能知道用户发了图片，不能判断具体画面。"],
            read_level="metadata_only",
            visual_source=image_ref.label,
            visual_kind="image",
            visual_status="unavailable",
        )

    async def _analyze_video_ref(
        self,
        video_ref: _SegmentRef,
        action_caller: OneBotActionCaller | None,
    ) -> ToolAnalysisResult:
        ref_url = video_ref.url or (video_ref.file if video_ref.file.startswith(("http://", "https://")) else "")
        if ref_url and _is_bilibili_url(ref_url):
            return await self._analyze_bilibili(ref_url)

        findings = [f"收到视频：{video_ref.label}。"]
        if video_ref.summary:
            findings.append(f"视频摘要/标题：{video_ref.summary}")
        if ref_url:
            findings.append(f"视频地址：{ref_url}")

        material = await self._resolve_ref_material(video_ref, action_caller)
        if material:
            data, source, _ = material
            result = await self._analyze_video_bytes(data, source, video_ref.label)
            result.findings[:0] = findings
            return result

        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [ref_url or video_ref.label],
            findings,
            ["没有拿到视频可读取文件，暂不自动下载和解析画面；如果是 B 站分享，会优先读取公开标题、简介、数据和字幕。"],
            read_level="metadata_only",
            visual_kind="video",
            visual_status="metadata_only",
        )

    async def _resolve_ref_material(
        self,
        ref: _SegmentRef,
        action_caller: OneBotActionCaller | None,
    ) -> tuple[bytes, str, str] | None:
        filename_hint = _material_filename_hint(ref)
        failures: list[str] = []
        for candidate in (ref.url, ref.file):
            if not candidate:
                continue
            if candidate.startswith(("http://", "https://")):
                try:
                    return await self._fetch_url(candidate, filename_hint)
                except Exception as exc:
                    failures.append(f"direct_url:{type(exc).__name__}")
                    continue
            path = Path(candidate)
            if path.exists() and path.is_file():
                return path.read_bytes(), str(path), ""

        if action_caller is None:
            return None

        for action, params in _onebot_material_actions(ref):
            try:
                response = await action_caller(action, params)
            except Exception as exc:
                failures.append(f"{action}:{type(exc).__name__}")
                continue
            resolved = _resolve_material_from_action_response(response)
            if not resolved:
                failures.append(f"{action}:no_resource")
                continue
            url, path = resolved
            if url:
                try:
                    return await self._fetch_url(url, filename_hint)
                except Exception as exc:
                    failures.append(f"{action}_url:{type(exc).__name__}")
            if path:
                file_path = Path(path)
                if file_path.exists() and file_path.is_file():
                    return file_path.read_bytes(), str(file_path), ""
                failures.append(f"{action}_path:not_found")
        if failures:
            print(
                f"[toolbox] material read failed kind={ref.kind} "
                f"label={ref.label[:80]!r} reason={','.join(failures[-6:])}"
            )
        return None

    async def _analyze_image_bytes(
        self,
        data: bytes,
        source: str,
        visual_kind: str = "auto",
        image_ref: _SegmentRef | None = None,
        vision_prompt: str | None = None,
    ) -> ToolAnalysisResult:
        info = _image_info(data)
        kind_hint = visual_kind if visual_kind in {"image", "sticker"} else _classify_visual_material(data, source, image_ref)
        prompt = vision_prompt or _visual_prompt_for_kind(kind_hint)
        ocr_result = await self._extract_image_ocr(data)
        if ocr_result.text:
            prompt += (
                "\n\n独立 OCR 结果（文字证据）：\n"
                f"{_shorten(ocr_result.text, 1200)}\n"
                f"OCR 平均置信度：{ocr_result.average_confidence:.3f}。"
                "图中文字必须以这份独立 OCR 结果为优先证据；"
                "可纠正明显断行，但不得改写、补字或凭空增加文字。"
            )
        vision_text, vision_limitation = await self._analyze_image_with_vision(data, source, prompt)
        vision_text = _sanitize_vision_text(vision_text)
        if vision_text and ocr_result.text:
            vision_text = _replace_visual_visible_text(
                vision_text,
                _shorten(ocr_result.text, 1200),
            )
        resolved_kind = kind_hint
        if resolved_kind == "auto":
            resolved_kind = _visual_kind_from_analysis(vision_text) or _fallback_visual_kind(data, source, image_ref)

        findings = [_visual_meta_line(resolved_kind, data, info)]
        limitations = []
        if ocr_result.text:
            findings.append(
                f"独立 OCR 文字：{_shorten(ocr_result.text, 1600)}"
            )
            findings.append(
                "OCR 证据质量："
                f"平均置信度 {ocr_result.average_confidence:.3f}，"
                f"共 {getattr(ocr_result, 'line_count', 0) or len(ocr_result.text.splitlines())} 行。"
            )
        if vision_text:
            label = "表情包情绪分析" if resolved_kind == "sticker" else "图片内容分析"
            findings.append(f"{label}：{vision_text}")
        elif vision_limitation:
            limitations.append(vision_limitation)
        else:
            limitations.append("当前只读取到图片元信息；未配置视觉模型时，不会臆测图片里具体画面。")
        if ocr_result.error and not vision_text:
            limitations.append(
                f"独立 OCR 暂不可用：{_shorten(ocr_result.error, 240)}"
            )
        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [source],
            findings,
            limitations,
            read_level=(
                "full_content"
                if vision_text
                else "partial_content"
                if ocr_result.text
                else "metadata_only"
            ),
            visual_data=data,
            visual_source=source,
            visual_kind=resolved_kind,
            visual_status=(
                "verified"
                if vision_text
                else "ocr_only"
                if ocr_result.text
                else "unavailable"
            ),
            visual_ocr_confidence=ocr_result.average_confidence,
        )

    def _byte_limit_for_ext(self, ext: str) -> int:
        if ext in DOC_EXTENSIONS | SHEET_EXTENSIONS | TEXT_EXTENSIONS:
            return self.max_document_bytes
        if ext in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            return self.max_media_bytes
        return self.max_bytes

    async def _analyze_image_with_vision(
        self,
        data: bytes,
        source: str,
        prompt: str | None = None,
        *,
        prepared_images: list[bytes] | None = None,
        sequence_description: str = "",
    ) -> tuple[str, str]:
        if not self.vision_enabled:
            return "", "当前只读取到图片元信息；未配置视觉模型时，不会臆测图片里具体画面。"
        if not self.vision_model or not self.vision_base_url:
            return "", "视觉模型配置不完整，暂时只能基于图片元信息判断。"
        vision_images = prepared_images or _prepare_images_for_vision(data)
        if sum(len(image) for image in vision_images) > self.vision_max_bytes:
            return "", f"图片超过视觉分析上限 {self.vision_max_bytes} 字节，暂时只读取元信息。"

        encoded_images = [
            base64.b64encode(image).decode("ascii")
            for image in vision_images
        ]
        system_prompt = load_prompt("visual_analysis")
        system_prompt = load_prompt("visual_analysis")
        user_prompt = prompt or "请分析这张用户发来的图片或表情包，给出自然、可用于日常聊天的评价。"
        if len(encoded_images) > 1:
            user_prompt += "\n" + (
                sequence_description
                or (
                    "本次输入是同一个动画表情按时间顺序抽取的多帧，"
                    "请综合动作变化理解完整含义，不要把各帧当成不同图片或不同人物。"
                )
            )
        started_at = time.perf_counter()
        response_metrics: dict[str, Any] = {}
        raw_content = ""
        cleaned = ""
        active_model = self.vision_model
        fallback_model = (
            self.vision_fallback_model
            if (
                _ollama_native_base_url(self.vision_base_url)
                and self.vision_fallback_model
                and self.vision_fallback_model != self.vision_model
            )
            else ""
        )
        retry_count = max(
            self.vision_retry_count,
            1 if fallback_model else 0,
        )
        for attempt in range(retry_count + 1):
            try:
                async with self._vision_lock:
                    if _ollama_native_base_url(self.vision_base_url):
                        async with inference_resource_lease(
                            f"vision:{active_model}",
                            timeout_seconds=self.vision_resource_wait_seconds,
                        ):
                            await self._release_chat_model_for_vision(active_model)
                            model_response = await self._analyze_image_with_ollama_native(
                                encoded_images,
                                system_prompt,
                                user_prompt,
                                model=active_model,
                            )
                    else:
                        model_response = await self._analyze_image_with_openai_compatible(
                            encoded_images,
                            [_image_mime_type(image) for image in vision_images],
                            system_prompt,
                            user_prompt,
                        )
                raw_content = model_response.content
                response_metrics = {
                    **model_response.metrics,
                    "attempt": attempt + 1,
                    "model": active_model,
                }
                cleaned = _normalize_visual_model_output(raw_content)
                cleaned = _ensure_visual_identity_requires_verification(cleaned)
                invalid_reason = _visual_response_failure_reason(
                    raw_content,
                    cleaned,
                    response_metrics,
                )
                if not invalid_reason:
                    break
                can_retry_output = attempt < retry_count
                if can_retry_output:
                    next_model = (
                        fallback_model
                        if active_model == self.vision_model and fallback_model
                        else active_model
                    )
                    self._log_vision_event(
                        source=source,
                        original_data=data,
                        prepared_images=vision_images,
                        prompt=user_prompt,
                        status="retry",
                        elapsed_seconds=time.perf_counter() - started_at,
                        raw_output=raw_content,
                        cleaned_output=cleaned,
                        metrics={
                            **response_metrics,
                            "retry_reason": invalid_reason,
                            "next_model": next_model,
                        },
                        error=f"视觉输出无效：{invalid_reason}",
                        model=active_model,
                    )
                    await self._release_vision_model_after_failure(active_model)
                    active_model = next_model
                    continue
                self._log_vision_event(
                    source=source,
                    original_data=data,
                    prepared_images=vision_images,
                    prompt=user_prompt,
                    status="empty" if not cleaned else "invalid",
                    elapsed_seconds=time.perf_counter() - started_at,
                    raw_output=raw_content,
                    cleaned_output=cleaned,
                    metrics={**response_metrics, "failure_reason": invalid_reason},
                    error=f"视觉输出无效：{invalid_reason}",
                    model=active_model,
                )
                return "", (
                    "这次没有稳定读到图片具体内容，只能基于独立 OCR、"
                    "图片类型和尺寸判断；不要臆测画面细节。"
                )
            except Exception as exc:
                can_retry = (
                    attempt < retry_count
                    and _is_retryable_vision_resource_error(exc)
                )
                if can_retry:
                    next_model = (
                        fallback_model
                        if active_model == self.vision_model and fallback_model
                        else active_model
                    )
                    self._log_vision_event(
                        source=source,
                        original_data=data,
                        prepared_images=vision_images,
                        prompt=user_prompt,
                        status="retry",
                        elapsed_seconds=time.perf_counter() - started_at,
                        metrics={
                            "attempt": attempt + 1,
                            "next_model": next_model,
                        },
                        error=_exception_summary(exc),
                        model=active_model,
                    )
                    await self._release_vision_model_after_failure(active_model)
                    switched_model = next_model != active_model
                    active_model = next_model
                    if not switched_model:
                        await asyncio.sleep(min(8.0, 2.0 * (attempt + 1)))
                    continue
                print(f"[toolbox] vision analysis failed for {source}: {_exception_summary(exc)}")
                self._log_vision_event(
                    source=source,
                    original_data=data,
                    prepared_images=vision_images,
                    prompt=user_prompt,
                    status="error",
                    elapsed_seconds=time.perf_counter() - started_at,
                    metrics={"attempt": attempt + 1},
                    error=_exception_summary(exc),
                    model=active_model,
                )
                return "", (
                    "这次没有稳定读到图片具体内容，只能基于独立 OCR、"
                    "图片类型和尺寸判断；不要臆测画面细节。"
                )
        self._log_vision_event(
            source=source,
            original_data=data,
            prepared_images=vision_images,
            prompt=user_prompt,
            status="ok" if cleaned else "empty",
            elapsed_seconds=time.perf_counter() - started_at,
            raw_output=raw_content,
            cleaned_output=cleaned,
            metrics=response_metrics,
            model=active_model,
        )
        return cleaned, "" if cleaned else "视觉模型没有返回可用图片分析。"

    async def _extract_image_ocr(self, data: bytes) -> OcrExtraction:
        if not self.ocr_enabled:
            return OcrExtraction()
        return await asyncio.to_thread(extract_image_text, data)

    async def _analyze_image_with_openai_compatible(
        self,
        encoded_images: list[str],
        mime_types: list[str],
        system_prompt: str,
        user_prompt: str,
    ) -> _VisionModelResponse:
        import httpx

        image_items = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
            }
            for encoded_image, mime_type in zip(encoded_images, mime_types)
        ]
        payload = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        *image_items,
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": 480,
        }
        headers = {"Authorization": f"Bearer {self.vision_api_key or 'ollama'}"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.post(f"{self.vision_base_url}/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        content = (
            ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()
        return _VisionModelResponse(
            content,
            {
                "provider": "openai-compatible",
                "usage": body.get("usage") if isinstance(body.get("usage"), dict) else {},
            },
        )

    async def _analyze_image_with_ollama_native(
        self,
        encoded_images: list[str],
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> _VisionModelResponse:
        import httpx

        payload = {
            "model": model or self.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt, "images": encoded_images},
            ],
            "stream": False,
            "keep_alive": 0,
            "think": False,
            "format": VISUAL_RESPONSE_SCHEMA,
            "options": {
                "temperature": 0.1,
                "num_predict": 640,
                "num_ctx": 8192,
            },
        }
        async with httpx.AsyncClient(timeout=max(self.timeout, 120.0)) as client:
            response = await client.post(f"{_ollama_native_base_url(self.vision_base_url)}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        message = body.get("message") or {}
        return _VisionModelResponse(
            (message.get("content") or body.get("response") or "").strip(),
            {
                "provider": "ollama",
                "done_reason": body.get("done_reason"),
                "thinking_chars": len(str(message.get("thinking") or body.get("thinking") or "")),
                "load_ms": _duration_ms(body.get("load_duration")),
                "prompt_eval_ms": _duration_ms(body.get("prompt_eval_duration")),
                "eval_ms": _duration_ms(body.get("eval_duration")),
                "total_ms": _duration_ms(body.get("total_duration")),
                "prompt_eval_count": body.get("prompt_eval_count"),
                "eval_count": body.get("eval_count"),
            },
        )

    async def _release_chat_model_for_vision(
        self,
        active_vision_model: str | None = None,
    ) -> None:
        vision_host = _ollama_native_base_url(self.vision_base_url)
        chat_host = _ollama_native_base_url(self.chat_base_url)
        if not vision_host:
            return
        protected_model = active_vision_model or self.vision_model

        import httpx

        models_to_release: set[str] = set()
        if (
            vision_host == chat_host
            and self.chat_model
            and self.chat_model != protected_model
        ):
            models_to_release.add(self.chat_model)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if self.vision_unload_other_ollama_models:
                    response = await client.get(f"{vision_host}/api/ps")
                    response.raise_for_status()
                    body = response.json()
                    for item in body.get("models") or []:
                        if not isinstance(item, dict):
                            continue
                        model = str(
                            item.get("name")
                            or item.get("model")
                            or ""
                        ).strip()
                        if model and model != protected_model:
                            models_to_release.add(model)

                for model in sorted(models_to_release):
                    response = await client.post(
                        f"{vision_host}/api/generate",
                        json={
                            "model": model,
                            "keep_alive": 0,
                        },
                    )
                    response.raise_for_status()
        except Exception as exc:
            print(
                "[toolbox] Could not release the chat model before vision: "
                f"{_exception_summary(exc)}"
            )

    async def _release_vision_model_after_failure(
        self,
        model: str | None = None,
    ) -> None:
        vision_host = _ollama_native_base_url(self.vision_base_url)
        failed_model = model or self.vision_model
        if not vision_host or not failed_model:
            return

        import httpx

        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{vision_host}/api/generate",
                    json={
                        "model": failed_model,
                        "keep_alive": 0,
                    },
                )

    def _log_vision_event(
        self,
        *,
        source: str,
        original_data: bytes,
        prepared_images: list[bytes],
        prompt: str,
        status: str,
        elapsed_seconds: float,
        raw_output: str = "",
        cleaned_output: str = "",
        metrics: dict[str, Any] | None = None,
        error: str = "",
        model: str = "",
    ) -> None:
        with contextlib.suppress(Exception):
            info = _image_info(original_data)
            payload = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "image_id": hashlib.sha256(original_data).hexdigest()[:16],
                "source": _basename_from_ref(source) or "image",
                "model": model or self.vision_model,
                "status": status,
                "elapsed_ms": round(max(0.0, elapsed_seconds) * 1000),
                "original_bytes": len(original_data),
                "original_format": info[0] if info else "",
                "original_width": info[1] if info else None,
                "original_height": info[2] if info else None,
                "prepared_frames": len(prepared_images),
                "prepared_bytes": sum(len(image) for image in prepared_images),
                "prompt": _shorten(prompt, 1200),
                "raw_output": _shorten(raw_output, 4000),
                "cleaned_output": _shorten(cleaned_output, 3000),
                "metrics": metrics or {},
                "error": _shorten(error, 500),
            }
            self._vision_event_log.parent.mkdir(parents=True, exist_ok=True)
            with self._vision_event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    async def _analyze_video_bytes(self, data: bytes, source: str, filename: str = "") -> ToolAnalysisResult:
        findings = [f"视频文件：{filename or _basename_from_ref(source) or '未命名视频'}，约 {len(data)} 字节。"]
        limitations: list[str] = []
        frame_ocr_texts: list[str] = []
        vision_text = ""

        if not self.video_frame_analysis_enabled:
            return ToolAnalysisResult(
                "日常生活乐趣",
                "抽象有趣",
                [source],
                findings,
                ["视频抽帧分析未启用，只能基于标题和文件信息回应。"],
                read_level="partial_content",
                visual_kind="video",
                visual_status="metadata_only",
            )

        frames, frame_limitation = await asyncio.to_thread(
            _extract_video_frames,
            data,
            Path(filename or _basename_from_ref(source)).suffix.lower() or ".mp4",
            self.video_max_frames,
        )
        if frame_limitation:
            limitations.append(frame_limitation)
        if frames:
            findings.append(f"视频画面：已抽取 {len(frames)} 张关键帧用于理解画面。")
            if self.ocr_enabled:
                for index, frame in enumerate(frames, start=1):
                    ocr_result = await self._extract_image_ocr(frame)
                    if ocr_result.text:
                        frame_ocr_texts.append(
                            f"帧 {index}：{_shorten(ocr_result.text, 500)}"
                        )
                if frame_ocr_texts:
                    findings.append(
                        "独立 OCR 文字：" + "；".join(frame_ocr_texts)
                    )
            if self.vision_enabled:
                frame_positions = _video_frame_position_labels(len(frames))
                frame_prompt = (
                    f"这是同一个视频按时间顺序抽取的 {len(frames)} 帧，位置依次为："
                    f"{'、'.join(frame_positions)}。请综合前后变化判断主体、动作、场景、情绪、"
                    "可见文字和视频大意；不能把各帧当成互不相关的图片，也不能声称分析了声音。"
                    "只依据这些抽样帧，未覆盖的片段保持不确定。"
                )
                if frame_ocr_texts:
                    frame_prompt += (
                        "\n独立 OCR 文字证据：\n"
                        + "\n".join(frame_ocr_texts)
                        + "\nvisible_text 必须优先采用这些文字，不得凭空补字。"
                    )
                vision_text, limitation = await self._analyze_image_with_vision(
                    data,
                    f"{source}#sampled-frames",
                    frame_prompt,
                    prepared_images=[
                        _prepare_image_for_vision(frame, max_side=960)
                        for frame in frames[: self.video_max_frames]
                    ],
                    sequence_description=(
                        "这些图片是同一视频按时间顺序排列的抽样帧。"
                        "请利用前后变化理解动作和事件，只能概括抽样帧覆盖到的内容。"
                    ),
                )
                if vision_text:
                    findings.append("关键帧视觉分析：" + vision_text)
                elif limitation and limitation not in limitations:
                    limitations.append(limitation)
            else:
                limitations.append("已拿到视频并抽取关键帧，但未配置视觉模型，暂时不能判断关键帧具体画面。")
        elif not limitations:
            limitations.append("视频文件已读取，但没有成功抽取可分析画面。")

        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [source],
            findings,
            _dedupe(limitations),
            read_level=(
                "partial_content"
                if vision_text or frame_ocr_texts or frames
                else "metadata_only"
            ),
            visual_kind="video",
            visual_status=(
                "verified"
                if vision_text
                else "ocr_only"
                if frame_ocr_texts
                else "unavailable"
            ),
        )

    async def _fetch_url(self, url: str, filename_hint: str = "") -> tuple[bytes, str, str]:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        }
        if _is_bilibili_url(url):
            headers["Referer"] = "https://www.bilibili.com/"
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0].lower()
            ext = _extension_for_material(str(response.url), content_type) or _extension_for_material(
                filename_hint, content_type
            )
            limit = self._byte_limit_for_ext(ext)
            data = response.content
            if len(data) > limit:
                if content_type.startswith(("text/", "application/json")) and ext not in TEXT_EXTENSIONS:
                    data = data[:limit]
                else:
                    raise ValueError(f"文件超过读取上限 {limit} 字节")
            return data, str(response.url), content_type

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
    if "_chat_history" in parts and parts & _STICKER_EMOTION_PARTS:
        return "sticker"
    if {"mface", "marketface", "sticker", "emoji", "emoticon", "face", "qqface"} & parts:
        return "sticker"
    if "stickers" in parts and "_chat_history" not in parts:
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
