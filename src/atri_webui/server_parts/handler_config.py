from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals
from .handler_account import effective_bot_qq_for, view_memory_admin_for


class HandlerConfigMixin(WebUIHandlerMixin):
    def _handle_config_update(self) -> None:
        # 只读检视模式下拒绝改配置：写的是全局 .env，属于运行账号的配置。
        if self._refuse_when_read_only("修改配置"):
            return
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
        state = self.webui_state
        viewing_other = state.view_account() is not None
        friends: list[dict[str, Any]] = []
        source_status = {
            "memory": "ready",
            "insights": "unavailable",
            "modality": "ready",
            "qzone": "not_refreshed",
        }
        # QQ 空间是**运行账号**的登录会话（Cookie 在 Bridge 里）。查看别的账号时
        # 没有那个账号的空间会话，所以这里明确不拉、并说明原因，而不是把运行账号的
        # 好友混进被查看账号的用户列表。
        if viewing_other:
            source_status["qzone"] = "not_available_for_viewed_account"
        elif str(params.get("sync_qzone", ["0"])[0]).lower() in {"1", "true", "yes", "on"}:
            try:
                friends = self._qzone_admin().friends()
                source_status["qzone"] = "ready"
            except Exception as exc:
                source_status["qzone"] = f"offline: {str(exc)[:180]}"
        try:
            group_names = self._group_name_cache()
            # 四个来源全部跟随「查看账号」：记忆、评测、权限策略、空间互动对象。
            # 之前只接了记忆，于是切到新账号后用户中心还是原账号的人——那是 bug。
            memory_payload = self._decorate_memory_payload(
                view_memory_admin_for(self).summary(), group_names
            )
            insights_users: list[dict[str, Any]] = []
            insights_groups: list[dict[str, Any]] = []
            insights_store = state.view_insights_store()
            if insights_store is not None:
                insights_users = insights_store.known_users()
                insights_groups = insights_store.group_summary_schedules()
                for group in insights_groups:
                    group_id = str(group.get("group_id") or "")
                    if group_id and not str(group.get("group_name") or "").strip():
                        group["group_name"] = group_names.get(group_id, "")
                source_status["insights"] = "ready"
            elif viewing_other:
                # 被查看的账号还没有评测库，这不是错误，是"还没有数据"。
                source_status["insights"] = "empty_for_viewed_account"
            policy = state.view_modality_policy()
            targets = state.view_qzone_targets()
            view_config = state.view_config()
            directory = UserDirectory(
                memory_payload=memory_payload,
                insights_users=insights_users,
                modality_policy=policy,
                qzone_targets=targets,
                qzone_friends=friends,
                insights_groups=insights_groups,
                # 代表"机器人自己"的号必须跟随生效账号，否则换号后目录里还把旧号当机器人。
                bot_qq=effective_bot_qq_for(self),
                owner_qqs=view_config.owner_qqs,
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

    def _handle_reply_strategy_preview(self) -> None:
        """按好感度/活跃度预览会命中哪一档、上限多少。"""

        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            value = float(payload.get("value") or 0.0)
        except (TypeError, ValueError):
            return self._send_error(HTTPStatus.BAD_REQUEST, "value 必须是数字")
        try:
            result = preview_limits(
                kind=str(payload.get("kind") or "user"),
                value=value,
            )
        except OSError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json({"ok": True, **result})

    def _handle_reply_strategy(self) -> None:
        """回复策略 + 频率计数 + 可选对象（好感/活跃度），供高级页「回复策略」卡片使用。"""

        try:
            policy = load_reply_strategy()
            counters = counter_snapshot()
        except OSError as exc:
            return self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        self._send_json(
            {
                "ok": True,
                "policy": policy,
                "counters": counters,
                "objects": self._reply_strategy_objects(policy),
            }
        )

    def _handle_reply_strategy_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            policy = save_reply_strategy(payload)
        except (OSError, ValueError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "policy": policy})

    def _handle_reply_strategy_object(self) -> None:
        """用户中心按卡片保存单个用户/群聊的聊天权限与频率覆盖。"""

        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            result = update_object_rule(
                str(payload.get("kind") or "user"),
                str(payload.get("id") or ""),
                payload.get("rule") or {},
                name=str(payload.get("name") or ""),
                remove=bool(payload.get("remove")),
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json({"ok": True, **result})

    def _handle_reply_strategy_reset(self) -> None:
        try:
            reset_reply_counters()
        except OSError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json({"ok": True, "reset": True})

    def _reply_strategy_objects(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        """把记忆面板里的用户/群与它们的规则合并成一张表。

        对象来自记忆面板（带好感度 / 群活跃度），策略里手动添加但记忆里还没有的
        对象也会被合并进来，避免"刚加的对象在表格里看不见"。
        """

        owner_ids = {str(item) for item in (self.webui_state.config.owner_qqs or ())}
        collected: dict[tuple[str, str], dict[str, Any]] = {}
        try:
            items = view_memory_admin_for(self).summary().get("items") or []
        except Exception:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            conversation_id = str(item.get("id") or "")
            if kind == "person":
                identifier = str(target.get("user_id") or "").strip()
                if not identifier.isdigit() and conversation_id.startswith("private:"):
                    identifier = conversation_id.split(":", 1)[1].strip()
                if not identifier.isdigit():
                    continue
                collected[("user", identifier)] = {
                    "id": identifier,
                    "kind": "user",
                    "name": str(item.get("display_name") or f"QQ {identifier}"),
                    "affection": item.get("affection"),
                    "activity": None,
                    "owner": identifier in owner_ids,
                }
            elif kind == "group":
                identifier = str(target.get("group_id") or "").strip()
                if not identifier.isdigit() and conversation_id.startswith("group:"):
                    identifier = conversation_id.split(":", 1)[1].split(":", 1)[0].strip()
                if not identifier.isdigit():
                    continue
                collected[("group", identifier)] = {
                    "id": identifier,
                    "kind": "group",
                    "name": str(item.get("display_name") or f"群 {identifier}"),
                    "affection": None,
                    "activity": item.get("activity"),
                    "owner": False,
                }

        for kind, rules in (
            ("user", policy.get("users") or {}),
            ("group", policy.get("groups") or {}),
        ):
            for raw_id, rule in (rules or {}).items():
                identifier = str(raw_id)
                if not identifier.isdigit():
                    continue
                default_name = f"QQ {identifier}" if kind == "user" else f"群 {identifier}"
                entry = collected.setdefault(
                    (kind, identifier),
                    {
                        "id": identifier,
                        "kind": kind,
                        "name": default_name,
                        "affection": None,
                        "activity": None,
                        "owner": identifier in owner_ids,
                    },
                )
                rule_name = str((rule or {}).get("name") or "").strip()
                if rule_name:
                    entry["name"] = rule_name[:120]

        objects: list[dict[str, Any]] = []
        for (kind, identifier), entry in collected.items():
            rules = policy.get("users") if kind == "user" else policy.get("groups")
            rule = (rules or {}).get(identifier)
            entry["rule"] = dict(rule or {"mode": "auto"})
            objects.append(entry)
        objects.sort(
            key=lambda item: (
                0 if item.get("owner") else 1,
                -(float(item.get("affection") or item.get("activity") or 0.0)),
                str(item.get("id")),
            )
        )
        return objects

    def _handle_proactive_save(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            # 两张档位表（私聊好感档 / 群聊活跃度档）都是「回复策略」与「主动互动」
            # 共用的，住在 reply_strategy.json；主动互动页面保存时一起写回唯一来源。
            tiers = persist_tiers_from_payload(payload)
            policy = save_proactive_policy(payload)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        policy.update(tiers)
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
        """语音服务与档案的可读状态。

        歌曲合成工作流已迁出，因此这里不再探测 AI_music 桥接；工作台的探活走
        `/api/music/entry-status`。
        """

        try:
            health = run_coro(self.webui_state.server.voice.client.health())
        except Exception as exc:
            health = {"ok": False, "error": str(exc), "ready": False}
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
        }


