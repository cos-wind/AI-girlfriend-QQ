"""评测读取接口的 HTTP 适配层。"""

from http import HTTPStatus
from urllib.parse import parse_qs


class EvaluationHandlersMixin:
    """只负责把评测查询转换成现有 WebUI handler 的响应。"""

    def _handle_insights_status(self) -> None:
        try:
            runtime = self._insights_runtime()
            payload = runtime.public_status()
            self._group_name_cache()
            payload["groups"] = runtime.store.group_ids()
        except Exception as exc:
            return self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        self._send_json({"ok": True, **payload})

    def _handle_evaluation_dashboard(self, query: str) -> None:
        try:
            params = parse_qs(query)
            days = int(params.get("days", ["30"])[0])
            source = str(params.get("source", [""])[0]).strip()
            model_type = str(params.get("model_type", [""])[0]).strip()
            data = self._view_insights_store().evaluation_dashboard(days, source, model_type)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, **data})

    def _handle_evaluations(self, query: str) -> None:
        params = parse_qs(query)
        try:
            maximum_raw = str(params.get("max_score", [""])[0]).strip()
            data = self._view_insights_store().list_evaluations(
                status=str(params.get("status", [""])[0]).strip(),
                source=str(params.get("source", [""])[0]).strip(),
                model_type=str(params.get("model_type", [""])[0]).strip(),
                dimension=str(params.get("dimension", [""])[0]).strip(),
                maximum_score=float(maximum_raw) if maximum_raw else None,
                query=str(params.get("q", [""])[0]).strip(),
                limit=int(params.get("limit", ["100"])[0]),
                offset=int(params.get("offset", ["0"])[0]),
            )
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, **data})

    def _handle_evaluation_detail(self, query: str) -> None:
        evaluation_id = str(parse_qs(query).get("id", [""])[0]).strip()
        try:
            detail = self._view_insights_store().evaluation_detail(evaluation_id)
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        if detail is None:
            return self._send_error(HTTPStatus.NOT_FOUND, "评测记录不存在")
        self._send_json({"ok": True, "evaluation": detail})

    def _handle_evaluation_retry(self) -> None:
        if self._refuse_insights_write("重试评测"):
            return
        from .server import run_coro
        payload = self._read_json()
        try:
            evaluation_id = str((payload or {}).get("id") or "").strip()
            if not evaluation_id:
                raise ValueError("缺少评测记录 ID")
            if not run_coro(self._insights_runtime().evaluations.retry(evaluation_id)):
                raise ValueError("只能重试失败的评测，记录可能已被处理")
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "id": evaluation_id, "status": "queued"})

    def _handle_evaluation_retry_failed(self) -> None:
        if self._refuse_insights_write("重试失败评测"):
            return
        from .server import run_coro
        payload = self._read_json()
        try:
            source = str((payload or {}).get("source") or "").strip()
            if source not in {"", "system", "model"}:
                raise ValueError("评测来源无效")
            count = run_coro(self._insights_runtime().evaluations.retry_failed(source=source))
        except Exception as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        self._send_json({"ok": True, "count": count})

