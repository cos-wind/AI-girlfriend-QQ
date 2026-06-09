from __future__ import annotations

import asyncio
import base64
import csv
import html
import io
import json
import re
import struct
import subprocess
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree


URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"'<>]+)")
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".csv", ".tsv", ".json"}
DOC_EXTENSIONS = {".docx", ".pdf"}
SHEET_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_FILE_EXTENSIONS = TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}
MAX_TEXT_CHARS = 2800

OneBotActionCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class ToolAnalysisResult:
    category: str
    style: str
    sources: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    read_level: str = "full_content"

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
        if any(
            item.startswith(("图片内容分析", "表情包情绪分析", "图片信息", "表情包信息"))
            for item in self.findings
        ):
            visual_rule = (
                "\n本轮有当前图片/表情包分析时，优先围绕当前画面或表情情绪回复；"
                "不要引用上一份文档、表格、网页、旧图片或旧话题来抢答。"
                "\n不要说自己看不见图；如果可用信息有限，就基于当前可见信息自然短评。"
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
        self.enabled = bool(getattr(config, "toolbox_enabled", True))
        self.timeout = float(getattr(config, "toolbox_timeout_seconds", 8.0))
        self.max_bytes = int(getattr(config, "toolbox_max_bytes", 2_000_000))
        self.max_document_bytes = int(getattr(config, "toolbox_max_document_bytes", 20_000_000))
        self.max_media_bytes = int(getattr(config, "toolbox_max_media_bytes", 80_000_000))
        self.vision_enabled = bool(getattr(config, "toolbox_vision_enabled", False))
        self.vision_model = str(
            getattr(config, "toolbox_vision_model", "") or getattr(config, "openai_model", "")
        ).strip()
        self.vision_base_url = str(
            getattr(config, "toolbox_vision_base_url", "") or getattr(config, "openai_base_url", "")
        ).rstrip("/")
        self.vision_api_key = getattr(config, "toolbox_vision_api_key", None) or getattr(config, "openai_api_key", None)
        self.vision_max_bytes = int(getattr(config, "toolbox_vision_max_bytes", 8_000_000))
        self.video_frame_analysis_enabled = bool(
            getattr(config, "toolbox_video_frame_analysis_enabled", True)
        )
        self.video_max_frames = max(1, min(8, int(getattr(config, "toolbox_video_max_frames", 4))))

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

        for url in request.urls[:4]:
            result = await self._analyze_url(url)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)

        for path in request.paths[:4]:
            result = await self._analyze_path(path)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)

        for file_ref in request.file_refs[:3]:
            result = await self._analyze_file_ref(file_ref, action_caller)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)

        for image_ref in request.image_refs[:3]:
            result = await self._analyze_image_ref(image_ref, action_caller)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)

        for video_ref in request.video_refs[:2]:
            result = await self._analyze_video_ref(video_ref, action_caller)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)

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
    ) -> ToolAnalysisResult:
        visual_kind = _classify_visual_material(None, image_ref.label, image_ref)
        material = await self._resolve_ref_material(image_ref, action_caller)
        if material:
            data, source, _ = material
            return await self._analyze_image_bytes(data, source, visual_kind=visual_kind, image_ref=image_ref)

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
            )

        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [image_ref.label],
            [f"收到图片：{image_ref.label}。"],
            ["没有拿到图片下载地址，只能知道用户发了图片，不能判断具体画面。"],
            read_level="metadata_only",
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
        )

    async def _resolve_ref_material(
        self,
        ref: _SegmentRef,
        action_caller: OneBotActionCaller | None,
    ) -> tuple[bytes, str, str] | None:
        filename_hint = _material_filename_hint(ref)
        for candidate in (ref.url, ref.file):
            if not candidate:
                continue
            if candidate.startswith(("http://", "https://")):
                try:
                    return await self._fetch_url(candidate, filename_hint)
                except Exception:
                    continue
            path = Path(candidate)
            if path.exists() and path.is_file():
                return path.read_bytes(), str(path), ""

        if action_caller is None:
            return None

        for action, params in _onebot_material_actions(ref):
            try:
                response = await action_caller(action, params)
            except Exception:
                continue
            resolved = _resolve_material_from_action_response(response)
            if not resolved:
                continue
            url, path = resolved
            if url:
                try:
                    return await self._fetch_url(url, filename_hint)
                except Exception:
                    continue
            if path:
                file_path = Path(path)
                if file_path.exists() and file_path.is_file():
                    return file_path.read_bytes(), str(file_path), ""
        return None

    async def _analyze_image_bytes(
        self,
        data: bytes,
        source: str,
        visual_kind: str = "auto",
        image_ref: _SegmentRef | None = None,
    ) -> ToolAnalysisResult:
        info = _image_info(data)
        kind_hint = visual_kind if visual_kind in {"image", "sticker"} else _classify_visual_material(data, source, image_ref)
        vision_prompt = _visual_prompt_for_kind(kind_hint)
        vision_text, vision_limitation = await self._analyze_image_with_vision(data, source, vision_prompt)
        vision_text = _sanitize_vision_text(vision_text)
        resolved_kind = kind_hint
        if resolved_kind == "auto":
            resolved_kind = _visual_kind_from_analysis(vision_text) or _fallback_visual_kind(data, source, image_ref)

        findings = [_visual_meta_line(resolved_kind, data, info)]
        limitations = []
        if vision_text:
            label = "表情包情绪分析" if resolved_kind == "sticker" else "图片内容分析"
            findings.append(f"{label}：{vision_text}")
        elif vision_limitation:
            limitations.append(vision_limitation)
        else:
            limitations.append("当前只读取到图片元信息；未配置视觉模型时，不会臆测图片里具体画面。")
        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [source],
            findings,
            limitations,
            read_level="full_content" if vision_text else "partial_content",
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
    ) -> tuple[str, str]:
        if not self.vision_enabled:
            return "", "当前只读取到图片元信息；未配置视觉模型时，不会臆测图片里具体画面。"
        if not self.vision_model or not self.vision_base_url:
            return "", "视觉模型配置不完整，暂时只能基于图片元信息判断。"
        vision_data = _prepare_image_for_vision(data)
        if len(vision_data) > self.vision_max_bytes:
            return "", f"图片超过视觉分析上限 {self.vision_max_bytes} 字节，暂时只读取元信息。"

        encoded_image = base64.b64encode(vision_data).decode("ascii")
        system_prompt = (
            "你是图片理解模块，只输出可见事实、情绪判断和可用于聊天的简短结论。"
            "必须使用简体中文；不要输出思考过程、推理过程、工具过程、角色扮演台词、外语或无意义字符串。"
            "看不清的文字或细节要直接说看不清，不要编造。"
        )
        user_prompt = prompt or "请分析这张用户发来的图片或表情包，给出自然、可用于日常聊天的评价。"
        try:
            if _ollama_native_base_url(self.vision_base_url):
                content = await self._analyze_image_with_ollama_native(
                    encoded_image,
                    system_prompt,
                    user_prompt,
                )
            else:
                content = await self._analyze_image_with_openai_compatible(
                    encoded_image,
                    _image_mime_type(vision_data),
                    system_prompt,
                    user_prompt,
                )
        except Exception as exc:
            print(f"[toolbox] vision analysis failed for {source}: {_exception_summary(exc)}")
            return "", "这次没有稳定读到图片具体内容，只能基于图片类型和尺寸判断；不要臆测画面细节。"
        cleaned = _sanitize_vision_text(content)
        return cleaned, "" if cleaned else "视觉模型没有返回可用图片分析。"

    async def _analyze_image_with_openai_compatible(
        self,
        encoded_image: str,
        mime_type: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        import httpx

        data_url = f"data:{mime_type};base64,{encoded_image}"
        payload = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": 180,
        }
        headers = {"Authorization": f"Bearer {self.vision_api_key or 'ollama'}"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.post(f"{self.vision_base_url}/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        return (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()

    async def _analyze_image_with_ollama_native(
        self,
        encoded_image: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        import httpx

        payload = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt, "images": [encoded_image]},
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 180,
                "num_ctx": 2048,
            },
        }
        async with httpx.AsyncClient(timeout=max(self.timeout, 75.0)) as client:
            response = await client.post(f"{_ollama_native_base_url(self.vision_base_url)}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        return ((body.get("message") or {}).get("content") or body.get("response") or "").strip()

    async def _analyze_video_bytes(self, data: bytes, source: str, filename: str = "") -> ToolAnalysisResult:
        findings = [f"视频文件：{filename or _basename_from_ref(source) or '未命名视频'}，约 {len(data)} 字节。"]
        limitations: list[str] = []

        if not self.video_frame_analysis_enabled:
            return ToolAnalysisResult(
                "日常生活乐趣",
                "抽象有趣",
                [source],
                findings,
                ["视频抽帧分析未启用，只能基于标题和文件信息回应。"],
                read_level="partial_content",
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
            if self.vision_enabled:
                frame_summaries = []
                for index, frame in enumerate(frames[: self.video_max_frames], start=1):
                    text, limitation = await self._analyze_image_with_vision(
                        frame,
                        f"{source}#frame{index}",
                        f"这是用户视频的第 {index} 张抽样关键帧。请只基于画面描述视频内容、氛围和可评价点。",
                    )
                    if text:
                        frame_summaries.append(f"第 {index} 帧：{text}")
                    elif limitation and limitation not in limitations:
                        limitations.append(limitation)
                if frame_summaries:
                    findings.append("关键帧视觉分析：" + "；".join(frame_summaries))
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
            read_level="full_content" if any(item.startswith("关键帧视觉分析") for item in findings) else "partial_content",
        )

    async def _fetch_url(self, url: str, filename_hint: str = "") -> tuple[bytes, str, str]:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }
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


def _prepare_image_for_vision(data: bytes, max_side: int = 336) -> bytes:
    try:
        from PIL import Image, ImageOps
    except Exception:
        return data

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((max_side, max_side))
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, (255, 255, 255))
                alpha = image.getchannel("A")
                background.paste(image.convert("RGBA"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
            compressed = output.getvalue()
            return compressed if compressed else data
    except Exception:
        return data


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


def _merge_read_levels(levels: list[str]) -> str:
    cleaned = [str(level or "").strip() for level in levels if str(level or "").strip()]
    if not cleaned:
        return "metadata_only"
    if any(level == "full_content" for level in cleaned):
        return "full_content"
    if any(level == "partial_content" for level in cleaned):
        return "partial_content"
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


def _visual_prompt_for_kind(visual_kind: str) -> str:
    if visual_kind == "sticker":
        return (
            "请判断这张用户发来的表情包/梗图/动画表情的情绪和社交意图。"
            "只输出中文结论，禁止输出思考过程、工具过程、英文、日文或无意义字符串。"
            "格式用一段短中文，必须包含：类型、情绪、画面、适合怎么接话。"
            "情绪从开心、无语、嘲讽、委屈、震惊、害羞、安慰、生气、疑惑、得意、破防、其他里选最贴近的。"
            "如果图里有文字，尽量读出关键文字；不确定就说看不清，不要编。"
        )
    if visual_kind == "image":
        return (
            "请分析这张用户发来的普通图片、截图或照片。"
            "只输出中文结论，禁止输出思考过程、工具过程、英文、日文或无意义字符串。"
            "格式用一段短中文，必须包含：类型、主体/场景、关键文字或UI、审美/信息价值、适合怎么回复。"
            "如果是游戏界面、聊天截图、网页或文档截图，要优先说明可见文字和界面重点；看不清就说看不清，不要编。"
        )
    return (
        "请先判断这张图属于表情包/梗图/动画表情，还是普通图片/截图/照片。"
        "只输出中文结论，禁止输出思考过程、工具过程、英文、日文或无意义字符串。"
        "格式用一段短中文，必须包含：类型、主体/场景、情绪或关键内容、适合怎么回复。"
        "如果是表情包，重点分析情绪和社交意图；如果是普通图片，重点分析内容、文字/UI和审美。"
    )


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
    return _shorten(cleaned, 500)


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


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_html_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_html_text(match.group(1)) if match else ""


def _extract_meta_description(text: str) -> str:
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _clean_html_text(match.group(1))
    return ""


def _extract_readable_text(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_html_text(text)


def _clean_html_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_bvid(text: str) -> str:
    match = re.search(r"BV[0-9A-Za-z]{8,14}", text or "")
    return match.group(0) if match else ""


def _clean_bilibili_title(title: str) -> str:
    return re.sub(r"_哔哩哔哩_bilibili\s*$", "", title).strip()


def _looks_authoritative(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return domain.endswith((".gov", ".edu", ".edu.cn", ".gov.cn")) or any(
        token in domain for token in ("who.int", "stats.gov", "pbc.gov", "mof.gov", "worldbank.org")
    )


def _shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _summarize_json(value: Any) -> str:
    if isinstance(value, dict):
        keys = list(value.keys())
        return f"JSON 对象：顶层字段 {len(keys)} 个，主要字段：{'、'.join(map(str, keys[:12]))}"
    if isinstance(value, list):
        sample = value[:3]
        return f"JSON 数组：共 {len(value)} 项，前几项摘要：{_shorten(json.dumps(sample, ensure_ascii=False), 600)}"
    return f"JSON 值：{_shorten(json.dumps(value, ensure_ascii=False), 600)}"


def _summarize_table_rows(rows: list[list[str]], label: str, include_samples: bool = True) -> list[str]:
    header = [str(cell).strip() for cell in (rows[0] if rows else [])]
    sample = rows[1:4]
    col_count = max((len(row) for row in rows), default=0)
    findings = [
        f"{label}：约 {max(0, len(rows) - 1)} 行数据，{col_count} 列。",
        f"{label}字段：{'、'.join(cell for cell in header[:10] if cell) or '未识别'}",
    ]
    numeric = _numeric_column_summaries(rows)
    if numeric:
        findings.append(f"{label}数值概览：" + "；".join(numeric[:5]))
    if include_samples and sample:
        findings.append(f"{label}样例：" + "；".join(" | ".join(map(str, row[:6])) for row in sample))
    return findings


def _numeric_column_summaries(rows: list[list[str]]) -> list[str]:
    if len(rows) < 2:
        return []
    header = [str(cell).strip() or f"第{index + 1}列" for index, cell in enumerate(rows[0])]
    summaries: list[str] = []
    for index, name in enumerate(header[:20]):
        values = []
        missing = 0
        for row in rows[1:]:
            raw = str(row[index]).strip() if index < len(row) else ""
            if not raw:
                missing += 1
                continue
            number = _to_float(raw)
            if number is None:
                continue
            values.append(number)
        if not values:
            continue
        avg = sum(values) / len(values)
        summaries.append(
            f"{name} count={len(values)} min={_format_number(min(values))} "
            f"max={_format_number(max(values))} avg={_format_number(avg)} missing={missing}"
        )
    return summaries


def _to_float(value: str) -> float | None:
    text = value.replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _docx_text_part_names(archive: zipfile.ZipFile) -> list[str]:
    names = []
    wanted_prefixes = (
        "word/document.xml",
        "word/header",
        "word/footer",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    )
    for name in archive.namelist():
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        if name == "word/document.xml" or any(name.startswith(prefix) for prefix in wanted_prefixes[1:]):
            names.append(name)
    return sorted(names, key=lambda item: (item != "word/document.xml", item))


def _docx_xml_to_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    paragraphs: list[str] = []
    for paragraph in root.iter():
        if not paragraph.tag.endswith("}p"):
            continue
        pieces = [
            node.text or ""
            for node in paragraph.iter()
            if node.tag.endswith("}t") or node.tag.endswith("}instrText")
        ]
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    if paragraphs:
        return "\n".join(paragraphs)
    pieces = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    return " ".join(piece.strip() for piece in pieces if piece.strip())


def _read_xlsx_sheet_refs(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    fallback = [
        (Path(name).stem, name)
        for name in archive.namelist()
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
    ]
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return fallback

    rel_targets: dict[str, str] = {}
    for rel in rels.iter():
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if not rel_id or not target:
            continue
        target = target.replace("\\", "/")
        if target.startswith("/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = "xl/" + target.lstrip("/")
        rel_targets[rel_id] = path

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.iter():
        if not sheet.tag.endswith("}sheet"):
            continue
        name = sheet.attrib.get("name") or f"sheet{len(sheets) + 1}"
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        path = rel_targets.get(rel_id or "")
        if path and path in archive.namelist():
            sheets.append((name, path))
    return sheets or fallback


def _read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.iter():
        if item.tag.endswith("}si"):
            strings.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
    return strings


def _first_xlsx_sheet_name(archive: zipfile.ZipFile) -> str:
    for name in archive.namelist():
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
            return name
    raise KeyError("没有找到工作表")


def _read_xlsx_sheet_rows(
    archive: zipfile.ZipFile,
    sheet_name: str,
    shared: list[str],
) -> list[list[str]]:
    root = ElementTree.fromstring(archive.read(sheet_name))
    rows: list[list[str]] = []
    for row in root.iter():
        if not row.tag.endswith("}row"):
            continue
        values: list[str] = []
        for cell in row:
            if not cell.tag.endswith("}c"):
                continue
            cell_type = cell.attrib.get("t")
            raw = ""
            for child in cell:
                if child.tag.endswith("}v") and child.text is not None:
                    raw = child.text
                    break
                if child.tag.endswith("}is"):
                    raw = "".join(node.text or "" for node in child.iter() if node.tag.endswith("}t"))
                    break
            if cell_type == "s" and raw.isdigit():
                index = int(raw)
                raw = shared[index] if index < len(shared) else raw
            values.append(raw)
        if any(value != "" for value in values):
            rows.append(values)
    return rows


def _image_mime_type(data: bytes) -> str:
    info = _image_info(data)
    if not info:
        return "image/png"
    kind = info[0].lower()
    if kind == "jpeg":
        return "image/jpeg"
    return f"image/{kind}"


def _extract_video_frames(data: bytes, ext: str, max_frames: int) -> tuple[list[bytes], str]:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        return [], f"视频抽帧组件不可用：{exc}"

    suffix = ext if ext in VIDEO_EXTENSIONS else ".mp4"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / f"input{suffix}"
        input_path.write_bytes(data)
        duration = _probe_video_duration_seconds(ffmpeg, input_path)
        frames = _extract_even_video_frames(ffmpeg, input_path, tmp_dir, max_frames, duration)
        if not frames:
            pattern = str(tmp_dir / "frame_%02d.jpg")
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-vf",
                "fps=1,scale=640:-2",
                "-frames:v",
                str(max_frames),
                "-q:v",
                "4",
                pattern,
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
            except Exception as exc:
                return [], f"视频抽帧失败：{exc}"
            if completed.returncode != 0:
                error = completed.stderr.decode("utf-8", errors="ignore").strip()
                return [], f"视频抽帧失败：{_shorten(error, 220) or 'ffmpeg 未返回成功状态'}"
            frames = [path.read_bytes() for path in sorted(tmp_dir.glob("frame_*.jpg"))[:max_frames]]
        return frames, "" if frames else "视频文件已读取，但没有抽取到关键帧。"


def _probe_video_duration_seconds(ffmpeg: str, input_path: Path) -> float | None:
    command = [ffmpeg, "-i", str(input_path)]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            check=False,
        )
    except Exception:
        return None
    text = completed.stderr.decode("utf-8", errors="ignore")
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return duration if duration > 0 else None


def _extract_even_video_frames(
    ffmpeg: str,
    input_path: Path,
    tmp_dir: Path,
    max_frames: int,
    duration: float | None,
) -> list[bytes]:
    if not duration:
        return []
    timestamps = [
        max(0.0, min(duration - 0.05, duration * (index + 1) / (max_frames + 1)))
        for index in range(max_frames)
    ]
    frames: list[bytes] = []
    for index, timestamp in enumerate(timestamps, start=1):
        output_path = tmp_dir / f"even_frame_{index:02d}.jpg"
        command = [
            ffmpeg,
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(input_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            "-q:v",
            "4",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=12,
                check=False,
            )
        except Exception:
            continue
        if completed.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            frames.append(output_path.read_bytes())
    return frames[:max_frames]


def _image_info(data: bytes) -> tuple[str, int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return ("PNG", width, height)
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return ("GIF", width, height)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_info(data)
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ("WEBP", 0, 0)
    return None


def _jpeg_info(data: bytes) -> tuple[str, int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack(">H", data[index : index + 2])[0]
        if marker in set(range(0xC0, 0xCF)) - {0xC4, 0xC8, 0xCC} and index + 7 < len(data):
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            return ("JPEG", width, height)
        index += max(2, length)
    return None


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
