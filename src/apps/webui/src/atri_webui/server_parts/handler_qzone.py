from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerQZoneMixin(WebUIHandlerMixin):
    # QQ 空间是**运行账号**的登录会话（Cookie 存在本地 Bridge 里）。
    # 面板查看别的账号时，那个账号没有登录会话——所以这里必须返回"空 + 原因"，
    # 而不是把运行账号的动态/好友继续显示出来。显示别人的数据是在撒谎，
    # 比显示空更糟：用户会以为切过去了。
    QZONE_VIEWED_OTHER_REASON = (
        "QQ 空间数据来自正在运行的那个账号的登录会话（Bridge 中的 Cookie）。"
        "面板正在查看另一个账号，它没有登录会话，因此这里不显示数据。"
        "要查看该账号的空间，需要让 NapCat 登录它。"
    )

    def _viewing_other_account(self) -> bool:
        try:
            return self.webui_state.view_account() is not None
        except Exception:
            return False

    def _qzone_unavailable(self, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "ok": True,
            "viewing_other_account": True,
            "unavailable_reason": self.QZONE_VIEWED_OTHER_REASON,
        }
        payload.update(extra)
        self._send_json(payload)

    def _qzone_admin(self) -> QZoneAdmin:
        # 复用记忆面板的聚合结果，确保这里只能选择已经认识的人物 QQ。
        # 用**运行账号**的记忆：QQ 空间是运行账号的登录会话，用默认账号的名单会选错人。
        return QZoneAdmin(
            self.webui_state.running_memory_admin().summary(),
            bot_qq=self.webui_state.config.bot_qq,
            owner_qqs=self.webui_state.config.owner_qqs,
        )

    def _handle_qzone_dashboard(self) -> None:
        if self._viewing_other_account():
            return self._qzone_unavailable(users=[])
        self._send_json(self._qzone_admin().dashboard())

    def _handle_qzone_friends(self) -> None:
        if self._viewing_other_account():
            return self._qzone_unavailable(friends=[])
        try:
            self._send_json({"ok": True, "friends": self._qzone_admin().friends()})
        except (ValueError, QZoneBridgeError) as exc:
            self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))

    def _handle_qzone_bridge_status(self) -> None:
        """只读状态：Bridge 是否在跑、是否登录、是否还会自动启动。"""

        self._send_json(bridge_status())

    def _handle_qzone_bridge_action(self) -> None:
        """手动启动/停止 Bridge；不再由桌宠启动链自动拉起。"""

        payload = self._read_json()
        action = str((payload or {}).get("action") or "").strip().lower()
        try:
            if action == "start":
                result = start_bridge()
            elif action == "stop":
                result = stop_bridge()
            else:
                return self._send_error(HTTPStatus.BAD_REQUEST, "action 必须是 start 或 stop")
        except OSError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_automation_settings(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        values = dict(payload)
        for key in ("like_keywords", "comment_keywords"):
            if key in values:
                values[key] = parse_keywords(values[key])
        for key in ("enabled", "post_enabled", "post_auto_generate", "like_enabled", "comment_enabled", "comment_use_pool"):
            if key in values:
                values[key] = bool(values[key])
        # Legacy fixed/random fields remain readable for migration, but no
        # longer participate in scheduling. There is one supported model:
        # stable random slots distributed inside the configured window.
        values["post_mode"] = "window"
        for key, lower, upper in (("period_days", 1, 31), ("posts_per_period", 1, 20), ("post_start_hour", 0, 23), ("post_end_hour", 1, 24)):
            if key in values:
                try:
                    values[key] = max(lower, min(upper, int(values[key])))
                except (TypeError, ValueError):
                    return self._send_error(HTTPStatus.BAD_REQUEST, f"{key} 必须是整数")
        if "topic_rotation" in values:
            values["topic_rotation"] = parse_keywords(values["topic_rotation"])
        for key, upper in (("feed_limit", 50), ("max_likes_per_run", 50), ("max_comments_per_run", 20)):
            if key in values:
                try:
                    values[key] = max(0 if key != "feed_limit" else 1, min(upper, int(values[key])))
                except (TypeError, ValueError):
                    return self._send_error(HTTPStatus.BAD_REQUEST, f"{key} 必须是整数")
        if "visibility" in values:
            try:
                values["visibility"] = int(values["visibility"])
            except (TypeError, ValueError):
                return self._send_error(HTTPStatus.BAD_REQUEST, "可见范围无效")
            if values["visibility"] not in {0, 1, 2}:
                return self._send_error(HTTPStatus.BAD_REQUEST, "可见范围无效")
        try:
            settings = self.webui_state.qzone_automation.store.save_settings(values)
        except (ValueError, TypeError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "settings": settings})

    def _handle_qzone_automation_content(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            item = self.webui_state.qzone_automation.store.content_add(str(payload.get("content") or ""), prompt=str(payload.get("prompt") or ""), model_profile_id=str(payload.get("model_profile_id") or ""), generated_at=float(payload.get("generated_at") or 0) or None)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "item": item})

    def _handle_qzone_automation_content_update(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict) or not payload.get("id"):
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少内容 id")
        try:
            self.webui_state.qzone_automation.store.content_update(int(payload["id"]), str(payload.get("content") or ""), str(payload.get("status") or "") or None, prompt=payload.get("prompt"), model_profile_id=payload.get("model_profile_id"))
        except (ValueError, TypeError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True})

    def _handle_qzone_automation_content_delete(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict) or not payload.get("id"):
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少内容 id")
        self.webui_state.qzone_automation.store.content_delete(int(payload["id"]))
        # Deleting the visible pending item must immediately create/reveal the
        # next scheduled item; waiting for the 30-second scheduler made the UI
        # look empty until the next refresh.
        try:
            item = self.webui_state.qzone_automation.refresh_next_post()
        except Exception as exc:
            LOGGER.exception("QQ 空间删除动态后重排失败")
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json({"ok": True, "item": item})

    def _handle_qzone_automation_targets(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("targets"), list):
            return self._send_error(HTTPStatus.BAD_REQUEST, "targets 必须是数组")
        self._send_json({"ok": True, "targets": self.webui_state.qzone_automation.store.save_targets(payload["targets"])})

    def _handle_qzone_automation_run(self) -> None:
        # 这是明确的人工触发，仍受总控和模块开关约束。
        try:
            result = self.webui_state.qzone_automation.run_once()
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_automation_publish_generated(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            result = self.webui_state.qzone_automation.publish_generated_now(
                str(payload.get("prompt") or ""),
                str(payload.get("model_profile_id") or ""),
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            LOGGER.exception("QQ 空间即时生成发布失败")
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_automation_prepare_next(self) -> None:
        try:
            item = self.webui_state.qzone_automation.prepare_next_generated()
        except Exception as exc:
            LOGGER.exception("QQ 空间下一条动态预生成失败")
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json({"ok": True, "item": item})

    def _handle_qzone_automation_publish(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict) or not payload.get("id"):
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少内容 id")
        try:
            result = self.webui_state.qzone_automation.publish_now(int(payload["id"]))
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_automation_generate(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            result = run_coro(generate_qzone_text(self.webui_state.config, str(payload.get("prompt") or ""), str(payload.get("kind") or "post"), str(payload.get("profile_id") or "")))
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            LOGGER.exception("QQ 空间文案生成失败")
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_automation_comment(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            item = self.webui_state.qzone_automation.store.comment_add(str(payload.get("content") or ""), prompt=str(payload.get("prompt") or ""), model_profile_id=str(payload.get("model_profile_id") or ""), source_tid=str(payload.get("source_tid") or ""), source_user_id=str(payload.get("source_user_id") or ""), source_content=str(payload.get("source_content") or ""), generated_at=float(payload.get("generated_at") or 0) or None)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "item": item})

    def _handle_qzone_automation_comment_update(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict) or not payload.get("id"):
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少评论 id")
        try:
            self.webui_state.qzone_automation.store.comment_update(int(payload["id"]), str(payload.get("content") or ""), str(payload.get("status") or "") or None, prompt=payload.get("prompt"), model_profile_id=payload.get("model_profile_id"), source_tid=payload.get("source_tid"), source_user_id=payload.get("source_user_id"), source_content=payload.get("source_content"))
        except (ValueError, TypeError) as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True})

    def _handle_qzone_automation_comment_delete(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict) or not payload.get("id"):
            return self._send_error(HTTPStatus.BAD_REQUEST, "缺少评论 id")
        self.webui_state.qzone_automation.store.comment_delete(int(payload["id"]))
        self._send_json({"ok": True})

    def _handle_qzone_feeds(self, query: str) -> None:
        if self._viewing_other_account():
            return self._qzone_unavailable(feeds=[])
        params = parse_qs(query)
        try:
            result = self._qzone_admin().feeds(
                params.get("user_id", [""])[0],
                params.get("limit", ["10"])[0],
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except QZoneBridgeError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_all_feeds(self, query: str) -> None:
        if self._viewing_other_account():
            return self._qzone_unavailable(feeds=[])
        params = parse_qs(query)
        try:
            result = self._qzone_admin().all_feeds(params.get("limit", ["20"])[0])
        except QZoneBridgeError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_like(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            result = self._qzone_admin().like(payload)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except QZoneBridgeError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_comment(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            result = self._qzone_admin().comment(payload)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except QZoneBridgeError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result)

    def _handle_qzone_login(self) -> None:
        """从 QQ 动态面板触发一次 Bridge 可视化登录，不阻塞 8787。"""
        state = self.webui_state
        with state.qzone_login_lock:
            if state.qzone_login_running:
                return self._send_json({"ok": True, "running": True, "message": "QQ 空间登录已在进行中"})
            state.qzone_login_running = True
            state.qzone_login_last = {"ok": None, "message": "正在打开 QQ 空间登录页"}

        def worker() -> None:
            try:
                self._qzone_admin().client.action("login_qr", {})
                state.qzone_login_last = {"ok": True, "message": "QQ 空间登录成功"}
            except Exception as exc:
                state.qzone_login_last = {"ok": False, "message": str(exc)[:300]}
            finally:
                with state.qzone_login_lock:
                    state.qzone_login_running = False

        threading.Thread(target=worker, name="qzone-login", daemon=True).start()
        self._send_json({"ok": True, "running": True, "message": "正在打开 QQ 空间登录页"})

    def _handle_qzone_login_status(self) -> None:
        state = self.webui_state
        with state.qzone_login_lock:
            running = state.qzone_login_running
            last = dict(state.qzone_login_last)
        try:
            bridge = self._qzone_admin().client.status()
            nested = bridge.get("data") if isinstance(bridge.get("data"), dict) else {}
            def status_flag(value: Any) -> bool:
                if isinstance(value, str):
                    return value.strip().lower() not in {"", "0", "false", "no", "off", "未登录", "not_logged_in"}
                return bool(value)
            logged_in = any(
                status_flag(bridge.get(key)) or status_flag(nested.get(key))
                for key in ("logged_in", "is_logged_in", "login", "ok", "qq", "uin")
            )
            self._send_json({
                "ok": True,
                "reachable": True,
                "logged_in": logged_in,
                "qq": bridge.get("qq") or bridge.get("uin") or nested.get("qq") or nested.get("uin"),
                "login_running": running,
                "last": last,
            })
        except QZoneBridgeError as exc:
            self._send_json({
                "ok": True,
                "reachable": False,
                "logged_in": False,
                "login_running": running,
                "last": {**last, "message": str(exc)},
            })


