from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerInsightsMixin(WebUIHandlerMixin):
    def _insights_runtime(self) -> Any:
        runtime = getattr(self.webui_state.server, "insights", None)
        if runtime is None:
            raise RuntimeError("评测与群聊总结旁路未启动，请查看项目日志")
        return runtime

    def _group_name_cache(self) -> dict[str, str]:
        """读取并尽力刷新群名；NapCat 离线时不阻塞页面且使用旧缓存。"""
        runtime = getattr(self.webui_state.server, "insights", None)
        if runtime is None:
            return {}
        with contextlib.suppress(Exception):
            run_coro(self.webui_state.refresh_group_names())
        return runtime.store.group_name_map()

    @staticmethod
    def _decorate_memory_payload(payload: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
        """将记忆面板中的群聊显示名替换为群名，群号保留在数据字段用于筛选和保存。"""
        if not isinstance(payload, dict) or not names:
            return payload
        for item in payload.get("items", []):
            if not isinstance(item, dict) or item.get("kind") != "group":
                continue
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            group_id = str(target.get("group_id") or item.get("id", "").removeprefix("group:"))
            group_name = names.get(group_id)
            if group_name:
                item["group_name"] = group_name
                item["display_name"] = group_name
                item["searchable"] = f"{item.get('searchable', '')} {group_name}"
        if payload.get("kind") == "group":
            target = payload.get("content", {}).get("target", {}) if isinstance(payload.get("content"), dict) else {}
            group_id = str(target.get("group_id") or payload.get("id", "").removeprefix("group:"))
            if names.get(group_id):
                payload["group_name"] = names[group_id]
                payload["display_name"] = names[group_id]
        for info in payload.get("group_infos", []):
            if not isinstance(info, dict):
                continue
            group_id = str(info.get("group_id") or "")
            if names.get(group_id):
                info["group_name"] = names[group_id]
                info["display_name"] = names[group_id]
        payload["group_names"] = names
        return payload

    def _handle_summary_groups(self) -> None:
        try:
            self._group_name_cache()
            groups = self._insights_runtime().store.group_ids()
        except Exception as exc:
            return self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        self._send_json({"ok": True, "groups": groups})

    def _handle_summary_schedules(self) -> None:
        try:
            self._group_name_cache()
            schedules = self._insights_runtime().store.group_summary_schedules()
            # 兼容旧版只保存 HH:MM 的计划：首次展示时给出下一次执行日期，保存后即持久化。
            for row in schedules:
                for kind, days in (("daily", 1), ("weekly", 7), ("monthly", 30)):
                    field = f"{kind}_next_at"
                    if int(row.get(f"{kind}_enabled") or 0) and not str(row.get(field) or "").strip():
                        row[field] = (datetime.now().astimezone() + timedelta(days=days)).replace(
                            second=0, microsecond=0, tzinfo=None
                        ).isoformat(timespec="minutes")
        except Exception as exc:
            return self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        self._send_json({"ok": True, "schedules": schedules})

    def _handle_summary_schedule_save(self) -> None:
        payload = self._read_json()
        try:
            group_id = str((payload or {}).get("group_id") or "").strip()
            if not group_id:
                raise ValueError("群号不能为空")

            def plan(kind: str, default_days: int) -> tuple[bool, str, str]:
                value = (payload or {}).get(kind)
                value = value if isinstance(value, dict) else {}
                enabled = bool(value.get("enabled", False))
                raw_next = str(value.get("next_at") or value.get("time") or "").strip()
                if not enabled:
                    return False, (raw_next[-5:] if len(raw_next) >= 5 else "00:10"), ""
                now_local = datetime.now().astimezone().replace(second=0, microsecond=0)
                if not raw_next:
                    parsed = now_local + timedelta(days=default_days)
                else:
                    try:
                        parsed = datetime.fromisoformat(raw_next.replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise ValueError(f"{kind}下一次执行时间格式无效，应为日期和时间") from exc
                    if parsed.tzinfo is not None:
                        parsed = parsed.astimezone().replace(tzinfo=None)
                parsed = parsed.replace(second=0, microsecond=0)
                if parsed < datetime.now().astimezone().replace(second=0, microsecond=0, tzinfo=None):
                    raise ValueError(f"{kind}下一次执行时间不能早于当前时间")
                return enabled, parsed.strftime("%H:%M"), parsed.isoformat(timespec="minutes")

            daily_enabled, daily_time, daily_next_at = plan("daily", 1)
            weekly_enabled, weekly_time, weekly_next_at = plan("weekly", 7)
            monthly_enabled, monthly_time, monthly_next_at = plan("monthly", 30)
            self._insights_runtime().store.save_group_summary_schedule(
                group_id,
                daily_enabled=daily_enabled,
                daily_time=daily_time,
                weekly_enabled=weekly_enabled,
                weekly_time=weekly_time,
                monthly_enabled=monthly_enabled,
                monthly_time=monthly_time,
                daily_next_at=daily_next_at,
                weekly_next_at=weekly_next_at,
                monthly_next_at=monthly_next_at,
            )
            schedules = self._insights_runtime().store.group_summary_schedules()
            schedule = next((item for item in schedules if str(item.get("group_id")) == group_id), None)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        self._send_json({"ok": True, "schedule": schedule})

    def _handle_summaries(self, query: str) -> None:
        params = parse_qs(query)
        try:
            names = self._group_name_cache()
            items = self._insights_runtime().store.list_summaries(
                str(params.get("group_id", [""])[0]).strip(),
                int(params.get("limit", ["100"])[0]),
            )
            for item in items:
                item["group_name"] = names.get(str(item.get("group_id") or ""), "")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "items": items})

    def _handle_summary_detail(self, query: str) -> None:
        summary_id = str(parse_qs(query).get("id", [""])[0]).strip()
        try:
            detail = self._insights_runtime().store.summary_detail(summary_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        if detail is None:
            return self._send_error(HTTPStatus.NOT_FOUND, "总结记录不存在")
        detail["group_name"] = self._group_name_cache().get(str(detail.get("group_id") or ""), "")
        self._send_json({"ok": True, "summary": detail})

    def _handle_summary_generate(self) -> None:
        payload = self._read_json()
        try:
            group_id = str((payload or {}).get("group_id") or "").strip()
            raw_period_type = str((payload or {}).get("period_type") or "").strip().lower()
            period_date = str((payload or {}).get("period_date") or "").strip()
            trigger_type = "manual_send" if bool((payload or {}).get("send", False)) else "manual"
            if raw_period_type in {"daily", "weekly", "monthly"}:
                # 新接口按当前时刻和周期生成，周期边界由后端统一计算。
                summary_id = run_coro(
                    self._insights_runtime().summaries.submit(
                        group_id, trigger_type=trigger_type, period_type=raw_period_type,
                        anchor=period_date or None,
                    )
                )
            else:
                # 兼容旧版前端或第三方调用方，保留一次性自定义范围入口。
                period_start = datetime.fromisoformat(str((payload or {}).get("period_start") or ""))
                period_end = datetime.fromisoformat(str((payload or {}).get("period_end") or ""))
                if period_start.tzinfo is None or period_end.tzinfo is None:
                    raise ValueError("时间必须包含时区")
                summary_id = run_coro(
                    self._insights_runtime().summaries.submit(
                        group_id, period_start.isoformat(), period_end.isoformat(), "manual"
                    )
                )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "id": summary_id, "status": "queued"}, status=HTTPStatus.CREATED)

    def _handle_summary_export(self, query: str) -> None:
        params = parse_qs(query)
        summary_id = str(params.get("id", [""])[0]).strip()
        export_format = str(params.get("format", ["markdown"])[0]).strip().lower()
        try:
            detail = self._insights_runtime().store.summary_detail(summary_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        if detail is None:
            return self._send_error(HTTPStatus.NOT_FOUND, "总结记录不存在")
        detail["group_name"] = self._group_name_cache().get(str(detail.get("group_id") or ""), "")
        if export_format == "json":
            body = json.dumps(detail, ensure_ascii=False, indent=2).encode("utf-8")
            return self._send_download(body, f"group-summary-{summary_id[:8]}.json", "application/json")
        if export_format in {"html", "visual", "report"}:
            # 图文报告直接在新标签页打开，页面内提供打印/保存 PDF 按钮。
            return self._send_html(group_summary_html(detail))
        if export_format == "image":
            try:
                image_path = render_group_summary_image(
                    detail,
                    self._insights_runtime().store.path.parent / "summary_reports" / f"{summary_id}.png",
                )
                body = image_path.read_bytes()
            except Exception as exc:
                return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"图文报告生成失败：{exc}")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Disposition", "inline; filename=group-summary.png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if export_format not in {"md", "markdown"}:
            return self._send_error(HTTPStatus.BAD_REQUEST, "导出格式只支持 markdown、json、html 或 image")
        body = summary_markdown(detail).encode("utf-8")
        self._send_download(body, f"group-summary-{summary_id[:8]}.md", "text/markdown")

    def _handle_insights_config(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            save_insights_env(payload)
            status = run_coro(self._insights_runtime().reload_config())
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, **status})

    def _handle_insights_check(self) -> None:
        """WebUI 中的连通性检查；只访问 /models，不发送评测内容。"""
        try:
            run_coro(self._insights_runtime().check_judge_connection())
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "message": "评测模型接口认证成功"})

    def _handle_manual_evaluation(self) -> None:
        """提交一条“模型评测”样本，区别于系统自动采集的 system 来源。"""
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            question = str(payload.get("question") or "").strip()
            answer = str(payload.get("answer") or "").strip()
            if not question or not answer:
                raise ValueError("问题和回答不能为空")
            sample = EvaluationSample(
                turn_id=f"webui-{int(time.time() * 1000)}",
                conversation_id=str(payload.get("conversation_id") or "webui:model"),
                group_id=str(payload.get("group_id") or ""),
                question=question,
                answer=answer,
                context=str(payload.get("context") or ""),
                source="model",
                model_type=str(payload.get("model_type") or "chat").strip() if str(payload.get("model_type") or "chat").strip() in {"chat", "vision", "voice"} else "chat",
                model_name=str(payload.get("model_name") or "").strip()[:160],
            )
            evaluation_id = run_coro(self._insights_runtime().evaluations.enqueue(sample))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "id": evaluation_id, "status": "queued", "source": "model"}, status=HTTPStatus.CREATED)

    def _handle_music_project_stage(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            project_id = _valid_singing_job_id(str(payload.get("id") or ""))
            stage = str(payload.get("stage") or "").strip()
            if stage not in {"separation", "inference", "mix"}:
                raise ValueError("歌曲处理阶段无效")
            params = payload.get("parameters")
            if not isinstance(params, dict):
                params = {}
            result = _music_bridge_request(
                f"/api/projects/{project_id}/stages/{stage}",
                "POST",
                params,
            )
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        self._send_json(result, status=HTTPStatus.ACCEPTED)

    def _handle_music_project_operation(self, operation: str) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            return self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            project_id = _valid_singing_job_id(str(payload.get("id") or ""))
            routes = {
                "pipeline": f"/api/projects/{project_id}/pipeline",
                "confirm": f"/api/projects/{project_id}/actions/confirm",
                "rollback": f"/api/projects/{project_id}/actions/rollback",
                "reset": f"/api/projects/{project_id}/actions/reset",
                "recover": f"/api/projects/{project_id}/actions/recover",
                "segment": f"/api/projects/{project_id}/segments/rerun",
                "export": f"/api/projects/{project_id}/exports",
            }
            route = routes[operation]
            forwarded = {key: value for key, value in payload.items() if key != "id"}
            result = _music_bridge_request(route, "POST", forwarded, timeout=30)
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        status = HTTPStatus.ACCEPTED if operation in {"pipeline", "segment", "export"} else HTTPStatus.OK
        self._send_json(result, status=status)


