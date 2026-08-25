from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerConfigMixin(WebUIHandlerMixin):
    def _handle_minecraft_config(self) -> None:
        try:
            config = save_minecraft_bridge_config(self._read_json())
        except (OSError, ValueError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "config": config})

    def _handle_minecraft_command(self) -> None:
        try:
            result = send_minecraft_command(self._read_json())
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_config_update(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            update_env(payload)
            config = run_coro(self.webui_state.reload_config())
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "config": config_payload(config)})

    def _handle_modality_access(self) -> None:
        """返回白名单配置及已归档成员/群聊，供高级面板勾选。"""
        try:
            policy = load_modality_access()
            store = self._insights_runtime().store
            users = store.known_users()
            archived_groups = store.group_ids()
        except Exception as exc:
            return self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        known: dict[str, dict[str, Any]] = {
            str(item.get("user_id")): dict(item)
            for item in users
            if str(item.get("user_id") or "").isdigit()
        }
        for user_id in getattr(self.webui_state.config, "owner_qqs", ()) or ():
            key = str(user_id)
            known.setdefault(key, {"user_id": key, "name": "主人", "messages": 0, "last_message_at": ""})
        for user_id, item in (policy.get("users") or {}).items():
            key = str(user_id)
            known.setdefault(key, {"user_id": key, "name": str(item.get("name") or ""), "messages": 0, "last_message_at": ""})
            if str(item.get("name") or "").strip():
                known[key]["name"] = str(item.get("name"))[:120]
        policy["users"] = {
            key: {**known.get(key, {}), **value}
            for key, value in (policy.get("users") or {}).items()
        }
        known_groups: dict[str, dict[str, Any]] = {
            str(item.get("group_id")): dict(item)
            for item in archived_groups
            if str(item.get("group_id") or "").isdigit()
        }
        for group_id, item in (policy.get("groups") or {}).items():
            key = str(group_id)
            known_groups.setdefault(
                key,
                {
                    "group_id": key,
                    "group_name": str(item.get("name") or ""),
                    "messages": 0,
                    "last_message_at": "",
                },
            )
            if str(item.get("name") or "").strip():
                known_groups[key]["group_name"] = str(item.get("name"))[:120]
        self._send_json(
            {
                "ok": True,
                "policy": policy,
                "users": sorted(
                    known.values(),
                    key=lambda item: (
                        -int(item.get("messages") or 0),
                        str(item.get("name") or item.get("user_id") or ""),
                    ),
                ),
                "groups": sorted(
                    known_groups.values(),
                    key=lambda item: (
                        -int(item.get("messages") or 0),
                        str(item.get("group_name") or item.get("group_id") or ""),
                    ),
                ),
            }
        )

    def _handle_users(self, query: str) -> None:
        """Return the shared user directory read model.

        QQ Bridge is an optional source.  A failed friend refresh therefore
        keeps memory/Insights/modality users visible and reports the stale
        source state instead of failing the whole directory request.
        """
        params = parse_qs(query)
        friends: list[dict[str, Any]] = []
        source_status = {
            "memory": "ready",
            "insights": "unavailable",
            "modality": "ready",
            "qzone": "not_refreshed",
        }
        if str(params.get("sync_qzone", ["0"])[0]).lower() in {"1", "true", "yes", "on"}:
            try:
                friends = self._qzone_admin().friends()
                source_status["qzone"] = "ready"
            except Exception as exc:
                source_status["qzone"] = f"offline: {str(exc)[:180]}"
        try:
            group_names = self._group_name_cache()
            memory_payload = self._decorate_memory_payload(
                self.webui_state.memory_admin.summary(), group_names
            )
            insights_users: list[dict[str, Any]] = []
            insights_groups: list[dict[str, Any]] = []
            runtime = getattr(self.webui_state.server, "insights", None)
            if runtime is not None:
                insights_users = runtime.store.known_users()
                insights_groups = runtime.store.group_summary_schedules()
                for group in insights_groups:
                    group_id = str(group.get("group_id") or "")
                    if group_id and not str(group.get("group_name") or "").strip():
                        group["group_name"] = group_names.get(group_id, "")
                source_status["insights"] = "ready"
            policy = load_modality_access()
            targets = self.webui_state.qzone_automation.store.targets()
            directory = UserDirectory(
                memory_payload=memory_payload,
                insights_users=insights_users,
                modality_policy=policy,
                qzone_targets=targets,
                qzone_friends=friends,
                insights_groups=insights_groups,
                bot_qq=self.webui_state.config.bot_qq,
                owner_qqs=self.webui_state.config.owner_qqs,
                source_status=source_status,
            )
            user_id = str(params.get("id", [""])[0]).strip()
            if user_id:
                overview = directory.group_overview(user_id) if user_id.startswith("group:") else directory.overview(user_id)
                if overview is None:
                    return self._send_error(HTTPStatus.NOT_FOUND, "用户不存在")
                return self._send_json({"ok": True, "user": overview, "source_status": source_status})
            payload = directory.list_users(
                query=str(params.get("q", [""])[0]),
                source=str(params.get("source", [""])[0]),
                context=str(params.get("context", [""])[0]),
                capability=str(params.get("capability", [""])[0]),
                limit=int(params.get("limit", ["200"])[0]),
                offset=int(params.get("offset", ["0"])[0]),
            )
            payload["groups"] = directory.list_groups(
                query=str(params.get("q", [""])[0]),
                limit=500,
            )["items"]
            payload["group_total"] = len(payload["groups"])
            return self._send_json(payload)
        except (TypeError, ValueError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))

    def _handle_modality_access_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            policy = save_modality_access(payload)
        except (OSError, ValueError, TypeError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "policy": policy})

    def _handle_proactive_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            policy = save_proactive_policy(payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "policy": policy})

    def _handle_proactive_preview(self) -> None:
        payload = self._read_json()
        event_type = str((payload or {}).get("event_type") or "check_in")
        policy = load_proactive_policy()
        allowed = set(policy.get("content_weights") or {}) | set(
            policy.get("group_content_weights") or {}
        )
        if event_type not in allowed:
            return self._send_error(HTTPStatus.BAD_REQUEST, "未知的主动消息类型")
        raw_user_id = (payload or {}).get("user_id")
        raw_target_id = (payload or {}).get("target_id") or raw_user_id
        scope = str((payload or {}).get("scope") or "private")
        if scope not in {"private", "group"}:
            return self._send_error(HTTPStatus.BAD_REQUEST, "未知的预览范围")
        try:
            target_id = int(raw_target_id) if raw_target_id else None
            result = run_coro(
                self.webui_state.server.preview_proactive(event_type, target_id, scope)
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, **result})

    def _handle_model_profile_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            profile = upsert_model_profile(payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "profile": public_model_profile(profile)})

    def _handle_model_profile_delete(self) -> None:
        payload = self._read_json()
        profile_id = str((payload or {}).get("id") or "").strip()
        try:
            delete_model_profile(profile_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True})

    def _handle_model_profile_activate(self) -> None:
        payload = self._read_json()
        profile_id = str((payload or {}).get("id") or "").strip()
        try:
            profile = activate_model_profile(profile_id)
            config = run_coro(self.webui_state.reload_config())
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json(
            {
                "ok": True,
                "profile": public_model_profile(profile),
                "config": config_payload(config),
                "status": self._status(),
            }
        )

    def _handle_test_chat(self) -> None:
        payload = self._read_json()
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return self._send_error(HTTPStatus.BAD_REQUEST, "text is required")
        try:
            result = run_coro(test_chat(self.webui_state.config, text))
        except Exception as exc:
            return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        self._send_json({"ok": True, **result})

    def _handle_voice_translate(self) -> None:
        payload = self._read_json()
        try:
            result = run_coro(
                translate_voice_text(
                    self.webui_state.config,
                    str((payload or {}).get("text") or ""),
                    str((payload or {}).get("target_language") or ""),
                )
            )
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except Exception:
                detail = ""
            return self._send_error(HTTPStatus.BAD_GATEWAY, detail or f"翻译服务返回 HTTP {exc.code}")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, **result})

    def _voice_payload(self) -> dict[str, Any]:
        try:
            health = run_coro(self.webui_state.server.voice.client.health())
        except Exception as exc:
            health = {"ok": False, "error": str(exc), "ready": False}
        try:
            music_health = _music_bridge_request("/api/health", timeout=1.5)
            music_service = {
                "ok": bool(music_health.get("ok")),
                "url": MUSIC_SERVICE_URL,
                "error": "",
                "projects": music_health.get("music_projects") or {},
            }
        except Exception as exc:
            music_service = {
                "ok": False,
                "url": MUSIC_SERVICE_URL,
                "error": str(exc),
                "projects": {},
            }
        singing = health.get("singing")
        singing_references = (
            singing.get("references", [])
            if isinstance(singing, dict)
            and isinstance(singing.get("references"), list)
            else []
        )
        return {
            "ok": True,
            "config": config_payload(self.webui_state.config),
            "service": health,
            "profiles": voice_profiles_payload(),
            "candidates": voice_candidates_payload(),
            "asr_lexicon_text": asr_lexicon_text(),
            "tts_pronunciation_text": tts_pronunciation_text(),
            "behavior": load_voice_behavior(),
            "singing_references": singing_references,
            "music_service": music_service,
        }


