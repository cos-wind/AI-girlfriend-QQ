from __future__ import annotations

from .support import ToolboxMixin


class ToolboxVideoMixin(ToolboxMixin):
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
                visual_fallback_available=_meaningful_video_title(
                    filename or _basename_from_ref(source)
                ),
            )

        try:
            # 抽帧是最容易卡住的阶段，单独限时并把剩余时间留给 OCR/视觉。
            frames, frame_limitation = await asyncio.wait_for(
                asyncio.to_thread(
                    _extract_video_frames,
                    data,
                    Path(filename or _basename_from_ref(source)).suffix.lower() or ".mp4",
                    self.video_max_frames,
                ),
                timeout=min(24.0, self.video_deadline_seconds - 1.0),
            )
        except asyncio.TimeoutError:
            frames, frame_limitation = [], "视频抽帧超过阶段时限，已转入 OCR/标题降级。"
        if frame_limitation:
            limitations.append(frame_limitation)
        if frames:
            findings.append(f"视频画面：已抽取 {len(frames)} 张关键帧用于理解画面。")
            if self.ocr_enabled:
                for index, frame in enumerate(frames, start=1):
                    try:
                        ocr_result = await asyncio.wait_for(
                            self._extract_image_ocr(frame),
                            timeout=min(
                                5.0,
                                max(0.2, self.video_deadline_seconds - 25.0),
                            ),
                        )
                    except asyncio.TimeoutError:
                        ocr_result = OcrExtraction(error="视频帧 OCR 超时")
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
                try:
                    vision_text, limitation = await asyncio.wait_for(
                        self._analyze_image_with_vision(
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
                        ),
                        timeout=min(
                            35.0,
                            max(0.2, self.video_deadline_seconds - 24.0),
                        ),
                    )
                except asyncio.TimeoutError:
                    vision_text, limitation = "", "视频视觉理解超过阶段时限，已转入 OCR/标题降级。"
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
                if vision_text or frame_ocr_texts
                else "metadata_only"
            ),
            visual_kind="video",
            visual_status=(
                "verified"
                if vision_text
                else "ocr_only"
                if frame_ocr_texts
                else "metadata_only"
            ),
            visual_fallback_available=bool(
                frame_ocr_texts
                or _meaningful_video_title(filename or _basename_from_ref(source))
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
