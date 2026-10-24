from __future__ import annotations

from .support import ToolboxMixin


def _knowledge_material(source, text, coverage, blocks=None):
    return {"title": str(source).replace("\\", "/").rsplit("/", 1)[-1] or "资料",
            "locator": str(source), "text": text, "coverage": coverage,
            "blocks": blocks or [{"anchor": "text", "text": text}]}


class ToolboxDocumentsMixin(ToolboxMixin):
    async def _analyze_url(self, url: str) -> ToolAnalysisResult:
        from ..toolbox_parts.douyin import is_douyin_url
        if is_douyin_url(url):
            result = await self._analyze_douyin(url)
        else:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if "bilibili.com" in domain or "b23.tv" in domain:
                return await self._analyze_bilibili(url)
            result = await self._analyze_webpage(url)
        # QQ's message analyzer and desktop's durable imports enter here.
        # Use the same reader fallback as the model's open_web_page tool,
        # rather than letting imports stop at an empty HTML shell.
        if (result.read_level == 'metadata_only' or not any(
                m.get('text', '').strip() for m in result.knowledge_materials)) and bool(
                getattr(self.config, 'web_search_enabled', True)):
            from ..llm_tools.web_page_tool import open_web_page
            evidence = await open_web_page({'url': url}, self.config)
            if evidence.startswith(('已读取网页：', '已通过阅读代理读取网页：')):
                from dataclasses import replace
                result = replace(result, read_level='partial_content', findings=[*result.findings, evidence],
                    knowledge_materials=[*result.knowledge_materials,
                        _knowledge_material(url, evidence, 'reader_text_only')],
                    limitations=[*result.limitations, '补读到网页文字；未读取图片、视频画面或音轨。'])
        return result

    async def _analyze_douyin(self, url: str) -> ToolAnalysisResult:
        from ..toolbox_parts.douyin import public_item, share_target
        final_url = url
        try:
            raw, final_url, _ = await self._fetch_url(url)
            target = share_target(final_url)
            if not target:
                raise ValueError('未能从跳转地址识别抖音作品编号')
            kind, item_id = target
            item = public_item(_decode_bytes(raw), item_id)
            if not item:
                # The public mobile share page can expose JSON even when the
                # desktop page is only a JavaScript shell.
                share_url = f'https://www.iesdouyin.com/share/{kind}/{item_id}/'
                raw, _, _ = await self._fetch_url(share_url)
                item = public_item(_decode_bytes(raw), item_id)
            if not item:
                label = '图文' if kind == 'note' else '视频'
                raise ValueError(f'已识别抖音{label}作品 {item_id}，但公开页面未提供作品内容（可能需要登录、页面动态加载或平台访问限制）；未读到图片、视频或音轨。可上传原图/视频，或粘贴正文后分析')
            text = '抖音作品公开文案：' + item['desc'].strip()
            author = item.get('author') or {}
            if isinstance(author, dict) and isinstance(author.get('nickname'), str):
                text += '\n作者：' + author['nickname']
            return ToolAnalysisResult(category='日常生活乐趣', style='准确严谨', sources=[final_url],
                findings=[text], read_level='partial_content',
                limitations=['仅提取公开作品文案；未读取图片、视频画面或音轨。'],
                knowledge_materials=[dict(_knowledge_material(final_url, text, 'public_share_caption_only'),
                    raw=raw, filename='douyin-share.html')])
        except Exception as exc:
            return ToolAnalysisResult(category='日常生活乐趣', style='准确严谨', sources=[final_url],
                limitations=[f'抖音链接解析失败：{_exception_summary(exc)}'], read_level='metadata_only')

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
            knowledge_materials=[dict(_knowledge_material(final_url, body, "extracted_html_text"),
                                      raw=data, filename="page.html")],
        )

    async def _analyze_bilibili(self, url: str) -> ToolAnalysisResult:
        findings: list[str] = []
        materials = []
        limitations: list[str] = []
        sources = [url]
        final_url = url

        try:
            data, final_url, _ = await self._fetch_url(url)
            html_text = _decode_bytes(data)
            sources = [final_url]
        except Exception as exc:
            html_text = ""
            # A short link may have resolved successfully before the video page
            # rejected the request. Its BV number is still usable by the API.
            response = getattr(exc, 'response', None)
            if response is not None and _is_bilibili_url(str(response.url)):
                final_url = str(response.url)
                sources = [final_url]
            limitations.append(f"B站页面暂时读取失败：{exc}")

        bvid = _extract_bvid(final_url) or _extract_bvid(url) or _extract_bvid(html_text)
        title = _extract_html_title(html_text)
        desc = _extract_meta_description(html_text)

        if bvid:
            findings.append(f"B站视频 BV 号：{bvid}")
            api_result = await self._fetch_bilibili_api(bvid)
            findings.extend(api_result.findings)
            limitations.extend(api_result.limitations)
            materials.extend(api_result.knowledge_materials)
        if title:
            findings.append(f"视频页标题：{_clean_bilibili_title(title)}")
        if desc:
            findings.append(f"视频页简介：{desc}")
        if not bvid:
            limitations.append("没有识别到 BV 号，只能基于页面标题/简介判断。")
        limitations.append("目前不会自动下载视频画面；能读到公开标题、简介、分区、统计和公开字幕时才会分析。")
        read_level = "partial_content" if materials else "metadata_only"
        return ToolAnalysisResult(
            category="日常生活乐趣",
            style="抽象有趣",
            sources=sources,
            findings=_dedupe(findings),
            limitations=_dedupe(limitations),
            read_level=read_level,
            knowledge_materials=materials,
        )

    async def _fetch_bilibili_api(self, bvid: str) -> ToolAnalysisResult:
        findings: list[str] = []
        materials = []
        limitations: list[str] = []
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            data, _, _ = await self._fetch_url(url)
            payload = json.loads(_decode_bytes(data))
            if payload.get('code', 0) != 0:
                raise ValueError(f"接口错误 {payload['code']}：{payload.get('message') or '未返回视频信息'}")
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
                materials.extend(subtitle.knowledge_materials)
        if not materials and info.get('title'):
            text = 'B站公开视频资料（仅标题、简介等元数据；未读取视频画面、音轨或字幕）：\n' + '\n'.join(findings)
            materials.append(dict(_knowledge_material(f'https://www.bilibili.com/video/{bvid}', text,
                                                      'bilibili_public_metadata_only'),
                                  raw=data, filename='bilibili-metadata.json'))
        return ToolAnalysisResult(
            category="日常生活乐趣",
            style="抽象有趣",
            sources=[url],
            findings=findings,
            limitations=limitations,
            read_level="partial_content" if materials else "metadata_only",
            knowledge_materials=materials,
        )

    async def _fetch_bilibili_subtitle(self, bvid: str, cid: Any) -> ToolAnalysisResult:
        url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
        try:
            data, _, _ = await self._fetch_url(url)
            payload = json.loads(_decode_bytes(data))
            if payload.get('code', 0) != 0:
                raise ValueError(f"接口错误 {payload['code']}：{payload.get('message') or '未返回字幕信息'}")
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
            knowledge_materials=[dict(_knowledge_material(subtitle_url, subtitle_text, "public_subtitles_only",
                [{"anchor": f"seconds:{item.get('from', '?')}-{item.get('to', '?')}",
                  "text": str(item.get("content") or "")} for item in body]), raw=data, filename="subtitle.json")],
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
        self, data: bytes, source: str, filename: str = "", content_type: str = "",
    ) -> ToolAnalysisResult:
        try:
            result = await self._parse_file_bytes(data, source, filename, content_type)
        except Exception as exc:
            result = ToolAnalysisResult("生活学术研究", "准确严谨", [source],
                                        limitations=[f"解析失败：{exc}"], read_level="metadata_only")
        materials = list(result.knowledge_materials)
        if not materials:
            materials = [_knowledge_material(source, "\n".join(result.findings), "analysis_summary:" + result.read_level)]
        # Preserve the bytes actually read, including when the parser fails.
        materials[0] = dict(materials[0], raw=data, filename=filename or _basename_from_ref(source))
        return replace(result, knowledge_materials=materials)

    async def _parse_file_bytes(
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
        material = _knowledge_material(source, text, "decoded_text")
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
            return ToolAnalysisResult("生活学术研究", "准确严谨", [source], findings, knowledge_materials=[material])
        if ext == ".json":
            try:
                parsed = json.loads(text)
                return ToolAnalysisResult(
                    "生活学术研究",
                    "准确严谨",
                    [source],
                    [_summarize_json(parsed)],
                    knowledge_materials=[material],
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
            knowledge_materials=[material],
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
            knowledge_materials=[_knowledge_material(source, text, "docx_text_parts_only",
                [{"anchor": name, "text": part_text} for name, part_text in parts])],
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
            read_level="partial_content",
            knowledge_materials=[_knowledge_material(source, text,
                f"pdf_text_pages:1-{min(page_count, 20)}/{page_count};images_not_ocr",
                [{"anchor": f"page:{i + 1}", "text": part} for i, part in enumerate(page_texts)])],
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
        sheet_text = "\n\n".join(name + "\n" + "\n".join("\t".join(map(str, row)) for row in rows) for name, rows in non_empty)
        return ToolAnalysisResult("生活学术研究", "准确严谨", [source], findings,
            knowledge_materials=[_knowledge_material(source, sheet_text, "xlsx_cached_cells_only",
                [{"anchor": f"sheet:{name}", "text": "\n".join("\t".join(map(str, row)) for row in rows)} for name, rows in non_empty])])

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
