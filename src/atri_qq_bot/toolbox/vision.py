from __future__ import annotations

from .support import ToolboxMixin


class ToolboxVisionMixin(ToolboxMixin):
    async def analyze_image_upload(
        self,
        data: bytes,
        source: str = "api:image",
        *,
        user_question: str = "",
    ) -> ToolAnalysisResult:
        """Analyze image bytes received through an external API client.

        Keeping this as a public method gives Core API a stable seam without
        exposing request-parser internals or requiring callers to share paths.
        """

        if not data:
            raise ValueError("图片内容为空")
        if len(data) > int(getattr(self, "vision_max_bytes", 8_000_000)):
            raise ValueError("图片文件过大")
        return await self._analyze_image_bytes(
            data,
            str(source or "api:image"),
            visual_kind="image",
            vision_prompt=_visual_prompt_for_kind("image", user_question),
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
            title = video_ref.summary or video_ref.name or video_ref.label
            if _meaningful_video_title(title):
                result = replace(result, visual_fallback_available=True)
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
            visual_fallback_available=_meaningful_video_title(
                video_ref.summary or video_ref.name or video_ref.label
            ),
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
        if ocr_result.error:
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
            knowledge_materials=[{"title": "图片 OCR 与视觉分析", "locator": source, "raw": data,
                "filename": _basename_from_ref(source) or "image.bin",
                "text": "\n\n".join(p for p in (ocr_result.text, vision_text) if p),
                "coverage": "image_ocr_and_model_description;unverified",
                "blocks": [{"anchor": "ocr", "text": ocr_result.text},
                           {"anchor": "model_description", "text": vision_text}]}],
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
            if self.vision_fallback_model and self.vision_fallback_model != self.vision_model
            else ""
        )
        fallback_base_url = self._resolve_vision_fallback_base_url(fallback_model)
        retry_count = max(
            self.vision_retry_count,
            1 if fallback_model and fallback_base_url else 0,
        )
        deadline = time.monotonic() + self.vision_timeout_seconds
        for attempt in range(retry_count + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 1.0:
                break
            self._vision_attempt_timeout_seconds = max(1.0, remaining)
            try:
                active_base_url = (
                    self.vision_base_url
                    if active_model == self.vision_model
                    else fallback_base_url
                )
                async with self._vision_lock:
                    if _ollama_native_base_url(active_base_url):
                        async with inference_resource_lease(
                            f"vision:{active_model}",
                            timeout_seconds=min(
                                self.vision_resource_wait_seconds,
                                max(1.0, remaining),
                            ),
                            priority=InferencePriority.VISION,
                        ):
                            # 先独占推理租约再拉起 Ollama，避免后台记忆在线程间隙
                            # 抢先加载另一个 4B 模型。保留热 GPT-SoVITS；视觉
                            # 请求自身 keep_alive=0，会在完成后释放 Ollama 模型。
                            ollama_ready = await ensure_ollama_service(
                                timeout_seconds=min(
                                    10.0,
                                    max(1.0, remaining),
                                ),
                            )
                            if not ollama_ready:
                                raise RuntimeError(
                                    "本地 Ollama 视觉服务按需启动失败；未继续加载模型以保护系统资源"
                                )
                            release_base_url = (
                                active_base_url
                                if active_base_url != self.vision_base_url
                                else None
                            )
                            if release_base_url:
                                await self._release_chat_model_for_vision(
                                    active_model,
                                    release_base_url,
                                )
                            else:
                                await self._release_chat_model_for_vision(active_model)
                            native_kwargs = {"model": active_model}
                            if active_base_url != self.vision_base_url:
                                native_kwargs["base_url"] = active_base_url
                            model_response = await self._analyze_image_with_ollama_native(
                                encoded_images,
                                system_prompt,
                                user_prompt,
                                **native_kwargs,
                            )
                    else:
                        openai_kwargs = {"model": active_model}
                        if active_base_url != self.vision_base_url:
                            openai_kwargs["base_url"] = active_base_url
                        model_response = await self._analyze_image_with_openai_compatible(
                            encoded_images,
                            [_image_mime_type(image) for image in vision_images],
                            system_prompt,
                            user_prompt,
                            **openai_kwargs,
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
                    release_base_url = (
                        active_base_url
                        if active_base_url != self.vision_base_url
                        else None
                    )
                    if release_base_url:
                        await self._release_vision_model_after_failure(
                            active_model,
                            release_base_url,
                        )
                    else:
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
                    release_base_url = (
                        active_base_url
                        if active_base_url != self.vision_base_url
                        else None
                    )
                    if release_base_url:
                        await self._release_vision_model_after_failure(
                            active_model,
                            release_base_url,
                        )
                    else:
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
            return OcrExtraction(error="OCR 未开启，请在设置 → 图片与视频中启用文字识别。")
        return await asyncio.to_thread(extract_image_text, data)

    async def _analyze_image_with_openai_compatible(
        self,
        encoded_images: list[str],
        mime_types: list[str],
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        base_url: str | None = None,
    ) -> _VisionModelResponse:
        import httpx

        image_items = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
            }
            for encoded_image, mime_type in zip(encoded_images, mime_types)
        ]
        # 与 Ollama 原生路径一致：多帧（视频抽样帧）需要更大输出预算，
        # 避免 max_tokens 截断导致视觉输出被判无效。
        max_tokens = (
            getattr(self, "vision_video_num_predict", 800)
            if len(encoded_images) > 1
            else 480
        )
        payload = {
            "model": model or self.vision_model,
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
            "max_tokens": max_tokens,
        }
        active_model = str(model or self.vision_model).casefold()
        active_base_url = str(base_url or self.vision_base_url).casefold()
        if (
            "bigmodel.cn" in active_base_url
            and any(name in active_model for name in ("glm-4.6v", "glm-4.7"))
        ):
            # GLM-4.6V 默认可能开启动态思考。短视觉 JSON 曾出现 480 个
            # completion token 中 479 个被 reasoning 消耗、正文为空；关闭
            # Thinking 可让额度用于可见结果，并减少不必要的本地兜底。
            payload["thinking"] = {"type": "disabled"}
        headers = {"Authorization": f"Bearer {self.vision_api_key or 'ollama'}"}
        async with httpx.AsyncClient(
            timeout=min(self.vision_timeout_seconds, self._vision_attempt_timeout_seconds),
            headers=headers,
        ) as client:
            response = await client.post(
                f"{str(base_url or self.vision_base_url).rstrip('/')}/chat/completions",
                json=payload,
            )
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
        base_url: str | None = None,
    ) -> _VisionModelResponse:
        import httpx

        # 多帧（视频抽样帧 / 多帧 GIF）需要综合前后变化，输出字段更多，
        # 固定 320 token 会被写满触发 truncated_output，导致回落到封面。
        # 单张图片继续用 320，多帧用可配置的更大上限（默认 800）。
        num_predict = (
            getattr(self, "vision_video_num_predict", 800)
            if len(encoded_images) > 1
            else 320
        )
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
                "num_predict": num_predict,
                "num_ctx": 4096,
            },
        }
        async with httpx.AsyncClient(
            timeout=min(self.vision_timeout_seconds, self._vision_attempt_timeout_seconds)
        ) as client:
            response = await client.post(
                f"{_ollama_native_base_url(base_url or self.vision_base_url)}/api/chat",
                json=payload,
            )
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
        active_base_url: str | None = None,
    ) -> None:
        vision_host = _ollama_native_base_url(active_base_url or self.vision_base_url)
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
        base_url: str | None = None,
    ) -> None:
        vision_host = _ollama_native_base_url(base_url or self.vision_base_url)
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

    def _resolve_vision_fallback_base_url(self, model: str) -> str:
        """解析视觉兜底模型地址，支持云端主模型切换到本地 Ollama。

        WebUI 只保存一个视觉 Base URL 是历史兼容设计。为了不强迫用户
        额外填写第二个地址，本地 Ollama 模型名（例如 qwen3-vl:4b-instruct）
        默认使用本机原生接口；若以后配置了显式兜底地址，则优先使用它。
        """
        if not model:
            return ""
        if self.vision_fallback_base_url:
            return self.vision_fallback_base_url
        if _ollama_native_base_url(self.vision_base_url):
            return self.vision_base_url
        if ":" in model and not model.startswith(("http://", "https://")):
            return "http://127.0.0.1:11434"
        return ""

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
