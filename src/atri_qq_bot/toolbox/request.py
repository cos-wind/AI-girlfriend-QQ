from __future__ import annotations

from .support import ToolboxMixin


class ToolboxRequestMixin(ToolboxMixin):
    async def analyze(
        self,
        event: dict[str, Any],
        plain_text: str,
        action_caller: OneBotActionCaller | None = None,
        *,
        allow_vision: bool = True,
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
        visual_fallback_available = False

        def track_visual_result(result: ToolAnalysisResult) -> None:
            nonlocal visual_data
            nonlocal visual_source
            nonlocal visual_kind
            nonlocal visual_ocr_confidence
            nonlocal visual_fallback_available
            if not result.visual_kind:
                return
            visual_kind = result.visual_kind
            visual_statuses.append(result.visual_status or "unavailable")
            visual_ocr_confidence = max(
                visual_ocr_confidence,
                float(result.visual_ocr_confidence or 0.0),
            )
            visual_fallback_available = visual_fallback_available or bool(
                getattr(result, "visual_fallback_available", False)
            )
            if result.visual_data:
                visual_data = result.visual_data
                visual_source = result.visual_source

        for url in request.urls[:4]:
            # 白名单关闭时仍允许普通网页/文档工具，但不读取明显的图片/视频 URL。
            if not allow_vision and (_looks_like_video_url(url) or _is_visual_ref(url)):
                continue
            if _looks_like_video_url(url):
                try:
                    result = await asyncio.wait_for(
                        self._analyze_url(url),
                        timeout=self.video_deadline_seconds,
                    )
                except asyncio.TimeoutError:
                    result = _video_url_metadata_fallback(
                        url,
                        "视频链接分析达到 60 秒时限，已降级使用链接标题。",
                    )
                except Exception as exc:
                    result = _video_url_metadata_fallback(
                        url,
                        f"视频链接分析失败，已降级使用链接标题：{_exception_summary(exc)}",
                    )
            else:
                result = await self._analyze_url(url)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        for path in request.paths[:4]:
            if not allow_vision and _is_visual_ref(path):
                continue
            result = await self._analyze_path(path)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        for file_ref in request.file_refs[:3]:
            if not allow_vision and _is_visual_ref(_material_filename_hint(file_ref)):
                continue
            result = await self._analyze_file_ref(file_ref, action_caller)
            sources.extend(result.sources)
            findings.extend(result.findings)
            limitations.extend(result.limitations)
            read_levels.append(result.read_level)
            track_visual_result(result)

        for image_ref in request.image_refs[:3]:
            if not allow_vision:
                continue
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

        video_deadline = (
            time.monotonic() + self.video_deadline_seconds
            if request.video_refs
            else None
        )
        for video_ref in request.video_refs[:2]:
            if not allow_vision:
                continue
            result = await self._analyze_video_ref_bounded(
                video_ref,
                action_caller,
                video_deadline,
            )
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
            visual_fallback_available=visual_fallback_available,
        )

    async def _analyze_video_ref_bounded(
        self,
        video_ref: _SegmentRef,
        action_caller: OneBotActionCaller | None,
        deadline: float | None,
    ) -> ToolAnalysisResult:
        """在单条消息的剩余预算内处理视频，超时后只返回标题/摘要证据。"""
        remaining = self.video_deadline_seconds
        if deadline is not None:
            remaining = max(0.05, deadline - time.monotonic())
        try:
            return await asyncio.wait_for(
                self._analyze_video_ref(video_ref, action_caller),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            return self._video_metadata_fallback(
                video_ref,
                "视频分析达到 60 秒时限，已降级使用标题/摘要。",
            )
        except Exception as exc:
            return self._video_metadata_fallback(
                video_ref,
                f"视频分析失败，已降级使用标题/摘要：{_exception_summary(exc)}",
            )

    def _video_metadata_fallback(
        self,
        video_ref: _SegmentRef,
        limitation: str,
    ) -> ToolAnalysisResult:
        findings = [f"收到视频：{video_ref.label}。"]
        title = video_ref.summary or video_ref.name or video_ref.label
        if _meaningful_video_title(title):
            findings.append(f"视频标题：{title}")
        if video_ref.url:
            findings.append(f"视频地址：{video_ref.url}")
        return ToolAnalysisResult(
            "日常生活乐趣",
            "抽象有趣",
            [video_ref.url or video_ref.label],
            findings,
            [limitation],
            read_level="metadata_only",
            visual_kind="video",
            visual_status="metadata_only",
            visual_fallback_available=any(
                item.startswith("视频标题：") for item in findings
            ),
        )

    async def analyze_visual_followup(
        self,
        previous: ToolAnalysisResult,
        question: str,
        *,
        allow_vision: bool = True,
    ) -> ToolAnalysisResult | None:
        if not allow_vision or not previous.visual_data:
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
