from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerCoreMixin(WebUIHandlerMixin):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_html(_render_index_dynamic())
        if parsed.path == "/voice-call":
            token = parse_qs(parsed.query).get("token", [""])[0]
            session = self.webui_state.server.voice_calls.get(token)
            if session is None:
                return self._send_html(
                    "<!doctype html><meta charset='utf-8'><title>邀请无效</title>"
                    "<p style='font:16px sans-serif;padding:32px'>通话邀请已失效或已结束。</p>"
                )
            return self._send_html(render_voice_call(token, session.topic))
        if parsed.path == "/api/status":
            return self._send_json(self._status())
        if parsed.path == "/api/developer":
            return self._send_json(self._developer_payload())
        if parsed.path == "/api/logs":
            return self._send_json(self._logs_payload(parsed.query))
        if parsed.path == "/api/insights/status":
            return self._handle_insights_status()
        if parsed.path == "/api/evaluations/dashboard":
            return self._handle_evaluation_dashboard(parsed.query)
        if parsed.path == "/api/evaluations":
            return self._handle_evaluations(parsed.query)
        if parsed.path == "/api/evaluations/detail":
            return self._handle_evaluation_detail(parsed.query)
        if parsed.path == "/api/group-summaries/groups":
            return self._handle_summary_groups()
        if parsed.path == "/api/group-summaries/schedules":
            return self._handle_summary_schedules()
        if parsed.path == "/api/group-summaries/detail":
            return self._handle_summary_detail(parsed.query)
        if parsed.path == "/api/group-summaries/export":
            return self._handle_summary_export(parsed.query)
        if parsed.path == "/api/group-summaries":
            return self._handle_summaries(parsed.query)
        if parsed.path == "/api/config":
            return self._send_json(config_payload(self.webui_state.config))
        if parsed.path == "/api/modality-access":
            return self._handle_modality_access()
        if parsed.path == "/api/users":
            return self._handle_users(parsed.query)
        if parsed.path == "/api/proactive":
            return self._send_json(self.webui_state.server.proactive_status())
        if parsed.path == "/api/model-presets":
            return self._send_json({"presets": MODEL_PRESETS})
        if parsed.path == "/api/model-profiles":
            return self._send_json(model_profiles_payload(self.webui_state.config))
        if parsed.path == "/api/local-models":
            return self._send_json(local_models_payload())
        if parsed.path == "/api/minecraft":
            return self._send_json(minecraft_dashboard())
        if parsed.path == "/api/voice":
            return self._send_json(self._voice_payload())
        if parsed.path == "/api/voice/behavior":
            return self._send_json({"ok": True, "behavior": load_voice_behavior()})
        if parsed.path == "/api/voice/singing/jobs":
            return self._handle_singing_jobs()
        if parsed.path == "/api/voice/singing/job":
            return self._handle_singing_job(parsed.query)
        if parsed.path == "/api/music/projects":
            return self._handle_music_projects()
        if parsed.path == "/api/music/capabilities":
            return self._handle_music_capabilities()
        if parsed.path == "/api/music/sources":
            return self._handle_music_sources()
        if parsed.path == "/api/music/project":
            return self._handle_music_project(parsed.query)
        if parsed.path == "/api/music/project/audio":
            return self._handle_music_project_audio(parsed.query)
        if parsed.path == "/api/music/project/waveform":
            return self._handle_music_project_waveform(parsed.query)
        if parsed.path == "/api/music/project/log":
            return self._handle_music_project_log(parsed.query)
        if parsed.path == "/api/music/delivery-songs":
            return self._send_json(self._delivery_songs_payload())
        if parsed.path == "/api/music/delivery-audio":
            return self._send_delivery_song_audio(parsed.query)
        if parsed.path == "/api/voice/audio":
            return self._send_voice_audio(parsed.query)
        if parsed.path == "/api/stickers":
            return self._send_json(sticker_summary())
        if parsed.path == "/api/stickers/file":
            return self._send_sticker_file(parsed.query)
        if parsed.path == "/api/memory":
            names = self._group_name_cache()
            return self._send_json(
                self._decorate_memory_payload(self.webui_state.memory_admin.summary(), names)
            )
        if parsed.path == "/api/memory/detail":
            names = self._group_name_cache()
            return self._send_json(
                self._decorate_memory_payload(
                    self.webui_state.memory_admin.detail(parsed.query), names
                )
            )
        if parsed.path == "/api/qzone":
            return self._handle_qzone_dashboard()
        if parsed.path == "/api/qzone/feeds":
            return self._handle_qzone_feeds(parsed.query)
        if parsed.path == "/api/qzone/feeds/all":
            return self._handle_qzone_all_feeds(parsed.query)
        if parsed.path == "/api/qzone/login-status":
            return self._handle_qzone_login_status()
        if parsed.path == "/api/qzone/friends":
            return self._handle_qzone_friends()
        if parsed.path == "/api/qzone/automation":
            payload = self.webui_state.qzone_automation.dashboard()
            payload["bot_qq"] = str(self.webui_state.config.bot_qq)
            payload["owner_qqs"] = [str(value) for value in (self.webui_state.config.owner_qqs or ())]
            return self._send_json(payload)
        if parsed.path == "/api/qzone/automation/logs":
            params = parse_qs(parsed.query)
            return self._send_json({"ok": True, "logs": self.webui_state.qzone_automation.store.logs(int(params.get("limit", [100])[0] or 100), str(params.get("action", [""])[0]))})
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            return self._handle_config_update()
        if parsed.path == "/api/modality-access":
            return self._handle_modality_access_save()
        if parsed.path == "/api/proactive/save":
            return self._handle_proactive_save()
        if parsed.path == "/api/proactive/preview":
            return self._handle_proactive_preview()
        if parsed.path == "/api/model-profiles/save":
            return self._handle_model_profile_save()
        if parsed.path == "/api/model-profiles/delete":
            return self._handle_model_profile_delete()
        if parsed.path == "/api/model-profiles/activate":
            return self._handle_model_profile_activate()
        if parsed.path == "/api/test-chat":
            return self._handle_test_chat()
        if parsed.path == "/api/insights/config":
            return self._handle_insights_config()
        if parsed.path == "/api/insights/check":
            return self._handle_insights_check()
        if parsed.path == "/api/evaluations/manual":
            return self._handle_manual_evaluation()
        if parsed.path == "/api/evaluations/retry":
            return self._handle_evaluation_retry()
        if parsed.path == "/api/evaluations/retry-failed":
            return self._handle_evaluation_retry_failed()
        if parsed.path == "/api/group-summaries/generate":
            return self._handle_summary_generate()
        if parsed.path == "/api/group-summaries/schedules":
            return self._handle_summary_schedule_save()
        if parsed.path == "/api/voice/translate":
            return self._handle_voice_translate()
        if parsed.path == "/api/minecraft/config":
            return self._handle_minecraft_config()
        if parsed.path == "/api/minecraft/command":
            return self._handle_minecraft_command()
        if parsed.path == "/api/voice/save":
            return self._handle_voice_save()
        if parsed.path == "/api/voice/reference":
            return self._handle_voice_reference()
        if parsed.path == "/api/voice/preview":
            return self._handle_voice_preview()
        if parsed.path == "/api/voice/test-asr":
            return self._handle_voice_test_asr()
        if parsed.path == "/api/voice/singing/source":
            return self._handle_singing_source_upload()
        if parsed.path == "/api/voice/singing/create":
            return self._handle_singing_create()
        if parsed.path == "/api/voice/singing/cancel":
            return self._handle_singing_cancel()
        if parsed.path == "/api/music/project/create":
            return self._handle_music_project_create()
        if parsed.path == "/api/music/project/stems":
            return self._handle_music_project_stems()
        if parsed.path == "/api/music/project/stage":
            return self._handle_music_project_stage()
        if parsed.path == "/api/music/project/pipeline":
            return self._handle_music_project_operation("pipeline")
        if parsed.path == "/api/music/project/confirm":
            return self._handle_music_project_operation("confirm")
        if parsed.path == "/api/music/project/rollback":
            return self._handle_music_project_operation("rollback")
        if parsed.path == "/api/music/project/reset":
            return self._handle_music_project_operation("reset")
        if parsed.path == "/api/music/project/recover":
            return self._handle_music_project_operation("recover")
        if parsed.path == "/api/music/project/segment":
            return self._handle_music_project_operation("segment")
        if parsed.path == "/api/music/project/export":
            return self._handle_music_project_operation("export")
        if parsed.path == "/api/music/delivery-source":
            return self._handle_delivery_music_source_upload()
        if parsed.path == "/api/music/delivery-segment":
            return self._handle_delivery_music_segment()
        if parsed.path == "/api/voice-call/turn":
            return self._handle_voice_call_turn()
        if parsed.path == "/api/voice-call/close":
            return self._handle_voice_call_close()
        if parsed.path == "/api/voice-call/test-invite":
            return self._handle_voice_call_test_invite()
        if parsed.path == "/api/restart":
            return self._send_json(restart_background_services())
        if parsed.path == "/api/stickers/category":
            return self._handle_sticker_category()
        if parsed.path == "/api/stickers/upload":
            return self._handle_sticker_upload()
        if parsed.path == "/api/stickers/delete":
            return self._handle_sticker_delete()
        if parsed.path == "/api/memory/save":
            return self._handle_memory_save()
        if parsed.path == "/api/memory/relationship":
            return self._handle_memory_relationship()
        if parsed.path == "/api/memory/delete":
            return self._handle_memory_delete()
        if parsed.path == "/api/memory/backup":
            backup = self.webui_state.memory_admin.backup("manual")
            return self._send_json({"ok": True, "backup": str(backup)})
        if parsed.path == "/api/qzone/like":
            return self._handle_qzone_like()
        if parsed.path == "/api/qzone/comment":
            return self._handle_qzone_comment()
        if parsed.path == "/api/qzone/login":
            return self._handle_qzone_login()
        if parsed.path == "/api/qzone/automation/settings":
            return self._handle_qzone_automation_settings()
        if parsed.path == "/api/qzone/automation/content":
            return self._handle_qzone_automation_content()
        if parsed.path == "/api/qzone/automation/content/update":
            return self._handle_qzone_automation_content_update()
        if parsed.path == "/api/qzone/automation/content/delete":
            return self._handle_qzone_automation_content_delete()
        if parsed.path == "/api/qzone/automation/targets":
            return self._handle_qzone_automation_targets()
        if parsed.path == "/api/qzone/automation/run":
            return self._handle_qzone_automation_run()
        if parsed.path == "/api/qzone/automation/publish-generated":
            return self._handle_qzone_automation_publish_generated()
        if parsed.path == "/api/qzone/automation/prepare-next":
            return self._handle_qzone_automation_prepare_next()
        if parsed.path == "/api/qzone/automation/publish":
            return self._handle_qzone_automation_publish()
        if parsed.path == "/api/qzone/automation/generate":
            return self._handle_qzone_automation_generate()
        if parsed.path == "/api/qzone/automation/comment":
            return self._handle_qzone_automation_comment()
        if parsed.path == "/api/qzone/automation/comment/update":
            return self._handle_qzone_automation_comment_update()
        if parsed.path == "/api/qzone/automation/comment/delete":
            return self._handle_qzone_automation_comment_delete()
        self._send_error(HTTPStatus.NOT_FOUND, "not found")


