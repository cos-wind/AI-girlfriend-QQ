from __future__ import annotations

from atri_shared.reply_trace import span, traced
from atri_shared.runtime.memory import ASR_WORKER_COMMIT_BYTES, available_commit_bytes

from dataclasses import replace
import asyncio
import time
from pathlib import Path
from urllib.parse import urlparse
from contextvars import ContextVar

from atri_bot.toolbox.analysis_result import ToolAnalysisResult
from atri_bot.toolbox.formatting import _shorten
from atri_bot.toolbox.helpers import _exception_summary, _meaningful_video_title, _prepare_image_for_vision
from atri_bot.toolbox.request_collection import (
    ANALYZABLE_TEXT_EXTENSIONS as TEXT_EXTENSIONS,
    _basename_from_ref,
    _dedupe,
    _extension_for_material,
    _is_bilibili_url,
)


# Per-task budget: concurrent QQ requests must never change each other's deadline.
VIDEO_LINK_DEADLINE = ContextVar('video_link_deadline', default=None)

# The ASR worker alone commits ~6.5 GB (measured); the vision model needs
# roughly as much again. Only overlap when the system can commit both, or the
# OS runs out of virtual memory and the worker crashes inside torch.
AUDIO_OVERLAP_COMMIT_BYTES = ASR_WORKER_COMMIT_BYTES + 7 * 1024**3


class ToolboxVideoMixin:
    @staticmethod
    def _audio_may_overlap_vision() -> bool:
        available = available_commit_bytes()
        return available is None or available >= AUDIO_OVERLAP_COMMIT_BYTES


    @traced('video_download')
    async def _download_public_video(self, url: str) -> bytes:
        """Bound streamed downloads before buffering; error/login pages are not videos."""
        import httpx
        from urllib.parse import urlparse

        if urlparse(url).scheme != 'https':
            raise ValueError('公开视频下载地址必须使用 HTTPS')
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36'}
        host = (urlparse(url).hostname or '').lower()
        if host == 'bilivideo.com' or host.endswith('.bilivideo.com'):
            headers['Referer'] = 'https://www.bilibili.com/'
        elif host == 'douyinvod.com' or host.endswith('.douyinvod.com'):
            headers['Referer'] = 'https://www.douyin.com/'
        chunks = bytearray()
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(20, connect=8), headers=headers) as client:
            async with client.stream('GET', url) as response:
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').lower()
                if any(t in content_type for t in ('text/', 'json', 'xml')):
                    raise ValueError('视频地址返回了网页或错误信息，未取得视频文件')
                if int(response.headers.get('content-length') or 0) > self.max_media_bytes:
                    raise ValueError(f'视频超过读取上限 {self.max_media_bytes} 字节')
                async for chunk in response.aiter_bytes():
                    if len(chunks) + len(chunk) > self.max_media_bytes:
                        raise ValueError(f'视频超过读取上限 {self.max_media_bytes} 字节')
                    chunks.extend(chunk)
        data = bytes(chunks)
        if not (data[4:8] == b'ftyp' or data.startswith((b'FLV', b'\x1aE\xdf\xa3', b'RIFF'))):
            raise ValueError('下载内容不是可识别的视频文件')
        return data

    async def _analyze_public_video(self, media_urls: list[str], source: str):
        """Both QQ links and durable desktop imports use the file analysis pipeline."""
        from atri_bot.toolbox.analysis_result import ToolAnalysisResult
        deadline = time.monotonic() + max(0.05, self.video_deadline_seconds - min(20, self.video_deadline_seconds * 0.1))
        link_deadline = VIDEO_LINK_DEADLINE.get()
        if link_deadline is not None:
            deadline = min(deadline, link_deadline - max(0.05, min(2, self.video_deadline_seconds * 0.1)))
        errors = []
        for media_url in list(dict.fromkeys(media_urls))[:2]:
            try:
                data = await self._download_public_video(media_url)
            except Exception as exc:
                errors.append(_exception_summary(exc))
                continue
            # CPU ASR and GPU frame understanding can run together. The speech
            # service still serializes ASR workers and leases the GPU if needed.
            # 16 GB machines cannot hold the 6.5 GB ASR worker and the vision
            # model at once (Windows runs out of commit charge and the worker
            # dies inside torch), so the stages are serialized when there is no
            # room for both. See docs/engineering/modules/voice-service.md.
            audio_enabled = bool(getattr(self.config, 'voice_asr_enabled', False))
            audio_task = (asyncio.create_task(self._transcribe_video_audio(data))
                          if audio_enabled and self._audio_may_overlap_vision() else None)
            try:
                result = await self._analyze_video_bytes(data, source, 'public-video.mp4')
            except BaseException:
                if audio_task is not None:
                    audio_task.cancel()
                    await asyncio.gather(audio_task, return_exceptions=True)
                raise
            if audio_enabled:
                if audio_task is None:
                    # Deferred until the frame/vision stage released its model.
                    audio_task = asyncio.create_task(self._transcribe_video_audio(data))
                try:
                    if audio_task.done():
                        # Frame inference may consume the remaining budget after
                        # CPU ASR has already succeeded. Keep that evidence.
                        transcript = audio_task.result()
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0.05:
                            raise asyncio.TimeoutError
                        transcript = await asyncio.wait_for(audio_task, timeout=remaining)
                    transcript = transcript.strip()
                    if not transcript:
                        raise ValueError('未识别到可用语音')
                    audio = {'title': '视频音轨转写', 'locator': source, 'text': transcript,
                             'coverage': 'audio_transcript_only;asr_unverified',
                             'blocks': [{'anchor': 'audio_transcript;timestamps_unknown;asr_unverified', 'text': transcript}]}
                    result = replace(result, read_level='partial_content',
                        findings=[*result.findings, '视频音轨转写（自动识别，可能有错字）：' + _shorten(transcript, 5000)],
                        knowledge_materials=[*result.knowledge_materials, audio])
                except Exception as exc:
                    result = replace(result, limitations=[*result.limitations,
                        '音轨转写未完成：' + (_exception_summary(exc) if not isinstance(exc, asyncio.TimeoutError) else '超过本次视频分析时限')])
                finally:
                    if not audio_task.done():
                        audio_task.cancel()
                    await asyncio.gather(audio_task, return_exceptions=True)
            else:
                result = replace(result, limitations=[*result.limitations, '语音识别未启用，本次未读取音轨。'])
            return result
        return ToolAnalysisResult('日常生活乐趣', '准确严谨', sources=[source],
            read_level='metadata_only', limitations=['公开视频内容读取失败：' + ('；'.join(errors) or '平台未提供可访问的视频地址')])

    @traced('video_audio')
    async def _transcribe_video_audio(self, data: bytes) -> str:
        import tempfile
        import wave
        from pathlib import Path
        from uuid import uuid4
        from atri_shared.voice.client import SpeechServiceClient
        from atri_voice_service.audio_processing import prepare_speech_audio
        from atri_shared.runtime.paths import PROJECT_ROOT

        def prepare():
            # Own the input directory in the worker thread too: cancellation of
            # to_thread must not remove the video while FFmpeg is still reading.
            with tempfile.TemporaryDirectory(prefix='atri-video-audio-') as folder:
                source = Path(folder) / 'video.mp4'
                source.write_bytes(data)
                prepared = prepare_speech_audio(source, cache, max_duration_seconds=1800)
                if (prepared.duration_seconds or 0) <= 240:
                    return [(prepared, None)]
                # Keep each service request below its 300-second ASR limit.
                # Each chunk owns its WAV, including when an HTTP timeout leaves
                # the isolated worker still reading it.
                from atri_voice_service.audio_processing import PreparedAudio
                chunks = []
                try:
                    with wave.open(str(prepared.path), 'rb') as audio:
                        offset = 0
                        while data_chunk := audio.readframes(240 * audio.getframerate()):
                            path = cache / f'asr-normalized-{uuid4().hex}.wav'
                            with wave.open(str(path), 'wb') as output:
                                output.setparams(audio.getparams())
                                output.writeframes(data_chunk)
                            duration = len(data_chunk) / (audio.getframerate() * audio.getsampwidth())
                            chunks.append((PreparedAudio(path, temporary=True, duration_seconds=duration), offset))
                            offset += duration
                    return chunks
                finally:
                    prepared.cleanup()

        # A timed-out HTTP request does not cancel the isolated ASR worker.
        # Keep its input alive until a successful response; stale cache
        # files are pruned on a later import, never while a worker may read.
        cache = PROJECT_ROOT / 'data' / 'voice' / 'cache' / 'video-inputs'
        cache.mkdir(parents=True, exist_ok=True)
        for old in cache.glob('asr-normalized-*.wav'):
            if old.stat().st_mtime < time.time() - 86400:
                old.unlink(missing_ok=True)
        prepared_chunks = await asyncio.to_thread(prepare)
        client = SpeechServiceClient(getattr(self.config, 'voice_service_url', 'http://127.0.0.1:8790'),
            timeout_seconds=min(180, self.video_deadline_seconds))
        transcripts = []
        deadline = VIDEO_LINK_DEADLINE.get() or (time.monotonic() + self.video_deadline_seconds)
        for index, (prepared, offset) in enumerate(prepared_chunks):
            try:
                result = await asyncio.wait_for(client.transcribe(prepared.path),
                    timeout=max(.01, deadline - time.monotonic() - 3))
                prepared.cleanup()
                if not result.text.strip():
                    raise ValueError('该音轨片段未识别到可用语音')
                prefix = '' if offset is None else f'[{int(offset)}–{int(offset + prepared.duration_seconds)}秒] '
                transcripts.append(prefix + result.text.strip())
            except Exception as exc:
                # Unsubmitted chunks are safe to remove. The current input may
                # still be used by the speech service after a network timeout.
                for pending, _ in prepared_chunks[index + 1:]:
                    pending.cleanup()
                if not transcripts:
                    raise
                transcripts.append(f'【部分音轨：从 {int(offset or 0)} 秒起未完成转写：{_exception_summary(exc)}】')
                break
        return '\n'.join(transcripts)

    @traced('video')
    async def _analyze_video_bytes(self, data: bytes, source: str, filename: str = "") -> ToolAnalysisResult:
        """Translate shared video evidence into the chat/archive contract only."""
        from atri_shared import video as video_analysis

        title = filename or _basename_from_ref(source)
        findings = [f"视频文件：{title or '未命名视频'}，约 {len(data)} 字节。"]
        if not self.video_frame_analysis_enabled:
            return ToolAnalysisResult(
                "日常生活乐趣", "抽象有趣", [source], findings,
                ["视频抽帧分析未启用，只能基于标题和文件信息回应。"],
                read_level="metadata_only", visual_kind="video", visual_status="metadata_only",
                visual_fallback_available=_meaningful_video_title(title),
                knowledge_materials=[{"title": title or "视频原件", "locator": source,
                    "raw": data, "filename": filename or "video.bin", "text": "",
                    "coverage": "video_original_only;frame_analysis_disabled"}],
            )

        async def ocr(frame):
            value = await self._extract_image_ocr(frame)
            return video_analysis.FrameText(value.text, value.error)

        async def vision(frames, texts):
            positions = [f"约 {f.timestamp_seconds:.2f} 秒" if f.timestamp_seconds is not None
                         else "位置未知（顺序抽帧）" for f in frames]
            prompt = (
                f"这是同一个视频按时间顺序抽取的 {len(frames)} 帧，位置依次为："
                f"{'、'.join(positions)}。请综合前后变化判断主体、动作、场景、情绪、"
                "可见文字和视频大意；不能把各帧当成互不相关的图片，也不能声称分析了声音。"
                "只依据这些抽样帧，未覆盖的片段保持不确定。"
                "direct_answer 用150字以内概括内容和前后变化，其余描述字段各不超过40字。"
                "visible_text 只摘录理解视频必需的少量文字，不重复抄写长代码或段落；完整OCR已单独存档。"
                "无法从画面可靠确定的人物或作品出处写未确认，不猜名字。"
            )
            if texts:
                prompt += "\n独立 OCR 文字证据：\n" + "\n".join(
                    f"帧 {t.frame_index}：{_shorten(t.text, 500)}" for t in texts
                ) + "\nvisible_text 必须优先采用这些文字，不得凭空补字。"
            text, error = await self._analyze_image_with_vision(
                data, f"{source}#sampled-frames", prompt,
                prepared_images=[_prepare_image_for_vision(f.data, max_side=960) for f in frames],
                sequence_description="这些图片是同一视频按时间顺序排列的抽样帧。只能概括抽样帧覆盖到的内容。",
            )
            return video_analysis.FrameText(text, error)

        deadline = time.monotonic() + self.video_deadline_seconds
        link_deadline = VIDEO_LINK_DEADLINE.get()
        if link_deadline is not None:
            deadline = min(deadline, link_deadline - max(.05, min(2, self.video_deadline_seconds * .1)))
        report = await video_analysis.VideoAnalyzer(
            options=video_analysis.VideoOptions(max_frames=self.video_max_frames,
                max_bytes=self.max_media_bytes, vision_seconds=self.vision_timeout_seconds),
            ocr=ocr if self.ocr_enabled else None,
            vision=vision if self.vision_enabled else None,
        ).analyze(data, Path(title).suffix.lower() or ".mp4", deadline=deadline)
        limitations = [issue.message for issue in report.issues]
        if report.extraction.frames:
            findings.append(f"视频画面：已抽取 {len(report.extraction.frames)} 张关键帧用于理解画面。")
            limitations.append("画面理解仅覆盖按时间抽样的关键帧，不能代表逐帧看完视频。")
        if report.texts:
            findings.append("独立 OCR 文字：" + "；".join(
                f"帧 {t.frame_index}：{_shorten(t.text, 500)}" for t in report.texts))
        if report.vision_text:
            findings.append("关键帧视觉分析：" + report.vision_text)
        blocks = [{"anchor": f"sampled_frame:{t.frame_index};" + (
            f"timestamp_seconds:{t.timestamp_seconds:.3f}" if t.timestamp_seconds is not None else "timestamp_unknown"),
            "text": t.text} for t in report.texts]
        if report.vision_text:
            blocks.append({"anchor": "sampled_frames_model_description", "text": report.vision_text})
        return ToolAnalysisResult(
            "日常生活乐趣", "抽象有趣", [source], findings, _dedupe(limitations),
            read_level="partial_content" if report.vision_text or report.texts else "metadata_only",
            visual_kind="video", visual_status=report.visual_status,
            visual_fallback_available=bool(report.texts or _meaningful_video_title(title)),
            knowledge_materials=[{"title": title or "视频抽样分析", "locator": source,
                "raw": data, "filename": filename or "video.bin",
                "text": "\n\n".join(b["text"] for b in blocks), "blocks": blocks,
                "coverage": ("sampled_frames_only;no_audio;sample_positions_recorded;model_description_unverified"
                             if report.extraction.frames else "video_original_only;no_audio;no_sampled_frames"),
                "sample_positions_seconds": [f.timestamp_seconds for f in report.extraction.frames],
                "video_issues": [{"stage": i.stage, "code": i.code, "message": i.message} for i in report.issues]}],
        )

    @traced('material_download')
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
        if (urlparse(url).hostname or '').lower() == 'www.iesdouyin.com':
            # Desktop UA redirects to an empty JS challenge; the public share
            # document is served to mobile browsers.
            headers['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1'
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
