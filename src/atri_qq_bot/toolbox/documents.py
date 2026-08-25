from __future__ import annotations

from .support import ToolboxMixin


class ToolboxDocumentsMixin(ToolboxMixin):
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
