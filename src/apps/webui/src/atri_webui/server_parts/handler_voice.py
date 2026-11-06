from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerVoiceMixin(WebUIHandlerMixin):
    def _handle_voice_service_status(self) -> None:
        """只读状态：atri_voice_service 是否在跑、模型是否已预热。"""

        config = self.webui_state.config
        self._send_json(
            voice_service_status(
                enabled=bool(
                    getattr(config, "voice_asr_enabled", False)
                    or getattr(config, "voice_tts_enabled", False)
                )
            )
        )

    def _handle_voice_service_action(self) -> None:
        """手动启动 / 停止 atri_voice_service。"""

        payload = self._read_json()
        action = str((payload or {}).get("action") or "").strip().lower()
        if action == "start":
            try:
                result = start_voice_service()
            except OSError as exc:
                return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
            return self._send_json(result)
        if action == "stop":
            return self._send_json(stop_voice_service())
        return self._send_error(HTTPStatus.BAD_REQUEST, "action 必须是 start 或 stop")

    def _handle_voice_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            config_changes = payload.get("config")
            if isinstance(config_changes, dict):
                update_env(config_changes)
                config = run_coro(self.webui_state.reload_config())
            else:
                config = self.webui_state.config
            profile_payload = payload.get("profile")
            profile = (
                save_voice_profile(profile_payload)
                if isinstance(profile_payload, dict)
                else None
            )
            if "asr_lexicon_text" in payload:
                save_asr_lexicon_text(str(payload.get("asr_lexicon_text") or ""))
            if "tts_pronunciation_text" in payload:
                save_tts_pronunciation_text(
                    str(payload.get("tts_pronunciation_text") or "")
                )
            behavior_payload = payload.get("behavior")
            if isinstance(behavior_payload, dict):
                save_voice_behavior(behavior_payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {
                "ok": True,
                "config": config_payload(config),
                "profile": profile.public_dict() if profile else None,
            }
        )

    def _handle_voice_call_turn(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_VOICE_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "通话音频最大 30MB")
        audio_path: Path | None = None
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            token = multipart_text(form, "token", "").strip()
            session = self.webui_state.server.voice_calls.get(token)
            if session is None:
                raise ValueError("通话邀请已失效或已结束")
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("没有收到通话音频")
            language = multipart_text(form, "language", "auto").strip().lower()
            if language not in {"auto", "zh", "en", "ja"}:
                language = "auto"
            audio_path = save_test_audio(str(file_item.filename), file_item.data)
            started_at = time.perf_counter()
            transcript = run_coro(
                self.webui_state.server.voice.client.transcribe(audio_path, language)
            )
            reply = run_coro(
                self.webui_state.server.reply_engine.reply(
                    session.conversation_id,
                    transcript.text,
                    profile_id=session.conversation_id,
                    observed=False,
                    tool_context=VoicePromptContext(
                        transcript,
                        prefer_voice_reply=True,
                    ),
                )
            )
            voice_request = self.webui_state.server.reply_engine.consume_voice_request(
                session.conversation_id
            )
            consume_call = getattr(
                self.webui_state.server.reply_engine,
                "consume_call_request",
                None,
            )
            if callable(consume_call):
                consume_call(session.conversation_id)
            spoken_text = str(voice_request.text if voice_request else reply).strip()
            if not spoken_text:
                spoken_text = "我在听，再和我说一点吧。"
            max_chars = max(20, int(self.webui_state.config.voice_max_chars))
            spoken_text = spoken_text[:max_chars].strip()
            synthesis_request = VoiceRequest(
                text=spoken_text,
                emotion=voice_request.emotion if voice_request else "gentle",
                intensity=voice_request.intensity if voice_request else 0.55,
                language=voice_request.language if voice_request else "auto",
                reason="voice_reply",
            )
            synthesis = run_coro(
                self.webui_state.server.voice.synthesize(
                    session.conversation_id,
                    synthesis_request,
                    enforce_cooldown=False,
                )
            )
            self.webui_state.server.reply_engine.record_bot_reply(
                session.conversation_id,
                spoken_text,
                profile_id=session.conversation_id,
            )
            self.webui_state.server.voice_calls.mark_turn(token)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        finally:
            if audio_path is not None:
                with contextlib.suppress(OSError):
                    audio_path.unlink()
        self._send_json(
            {
                "ok": True,
                "transcript": transcript.text,
                "reply": spoken_text,
                "audio_url": f"/api/voice/audio?path={quote(str(synthesis.audio_path))}",
                "elapsed_ms": elapsed_ms,
            }
        )

    def _handle_voice_call_close(self) -> None:
        payload = self._read_json()
        token = str((payload or {}).get("token") or "").strip()
        if token:
            self.webui_state.server.voice_calls.close(token)
        self._send_json({"ok": True})

    def _handle_voice_call_test_invite(self) -> None:
        policy = load_voice_behavior()
        if not policy["calls_enabled"]:
            return self._send_error(HTTPStatus.BAD_REQUEST, "请先启用并保存浏览器通话")
        if not bool(self.webui_state.config.voice_tts_enabled):
            return self._send_error(HTTPStatus.BAD_REQUEST, "请先启用语音合成")
        owner_qqs = tuple(getattr(self.webui_state.config, "owner_qqs", ()) or ())
        if not owner_qqs:
            return self._send_error(HTTPStatus.BAD_REQUEST, "没有配置主人 QQ，无法建立测试会话")
        session = self.webui_state.server.voice_calls.create(
            f"private:{int(owner_qqs[0])}",
            "WebUI 通话链路测试",
            int(policy["call_expiry_minutes"]),
            int(policy["call_max_minutes"]),
        )
        call_url = (
            f"{str(policy['call_base_url']).rstrip('/')}/voice-call?token={session.token}"
        )
        self._send_json({"ok": True, "call_url": call_url, "session": session.public_dict()})

    def _handle_voice_reference(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_VOICE_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "参考音频最大 30MB")
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            profile_id = multipart_text(form, "profile_id", "atri")
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("请选择参考音频")
            if len(file_item.data) > MAX_VOICE_UPLOAD_BYTES:
                raise ValueError("参考音频最大 30MB")
            profile = save_reference_audio(
                profile_id,
                str(file_item.filename),
                file_item.data,
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "profile": profile.public_dict()})

    def _handle_voice_preview(self) -> None:
        payload = self._read_json()
        try:
            request = VoiceRequest.from_tool_arguments(
                payload if isinstance(payload, dict) else {},
                max_chars=int(self.webui_state.config.voice_max_chars),
            )
            profile_id = str((payload or {}).get("profile") or "atri")
            behavior = load_voice_behavior()
            started_at = time.perf_counter()
            result = run_coro(
                self.webui_state.server.voice.client.synthesize(
                    request,
                    profile_id,
                    **_voice_preview_synthesis_options_for_mode(
                        behavior, str((payload or {}).get("preview_mode") or "strict")
                    ),
                )
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {
                "ok": True,
                "audio_url": f"/api/voice/audio?path={quote(str(result.audio_path))}",
                "audio_path": str(result.audio_path),
                "duration_seconds": result.duration_seconds,
                "source": result.source,
                "quality": result.quality,
                "elapsed_ms": elapsed_ms,
            }
        )

    def _handle_voice_test_asr(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0 or content_length > MAX_VOICE_UPLOAD_BYTES + 200_000:
            return self._send_error(HTTPStatus.BAD_REQUEST, "测试音频最大 30MB")
        audio_path: Path | None = None
        try:
            form = parse_multipart_form(
                self.headers.get("Content-Type", ""),
                self.rfile.read(content_length),
            )
            file_item = multipart_file(form, "file")
            if file_item is None or not file_item.filename:
                raise ValueError("请选择测试音频")
            if len(file_item.data) > MAX_VOICE_UPLOAD_BYTES:
                raise ValueError("测试音频最大 30MB")
            language = multipart_text(form, "language", "auto").strip().lower()
            if language not in {"auto", "zh", "en", "ja"}:
                raise ValueError("识别语言只支持自动、中文、英文或日文")
            audio_path = save_test_audio(str(file_item.filename), file_item.data)
            started_at = time.perf_counter()
            result = run_coro(
                self.webui_state.server.voice.client.transcribe(audio_path, language)
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        finally:
            if audio_path is not None:
                with contextlib.suppress(OSError):
                    audio_path.unlink()
        self._send_json(
            {
                "ok": True,
                "text": result.text,
                "language": result.language,
                "emotion": result.emotion,
                "confidence": result.confidence,
                "elapsed_ms": elapsed_ms,
            }
        )


