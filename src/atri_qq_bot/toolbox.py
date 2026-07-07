from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import re
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
_should_analyze_image = _toolbox_request_collection._should_analyze_image
_classify_category = _toolbox_request_collection._classify_category



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
