from __future__ import annotations

import base64 as _knowledge_base64
import binascii as _knowledge_binascii
import json as _knowledge_json
import sqlite3 as _knowledge_sqlite
from http import HTTPStatus as _KnowledgeHTTP
from urllib.parse import parse_qs as _knowledge_query, urlparse as _knowledge_url

from atri_qq_bot.knowledge import store as _knowledge_store
from atri_qq_bot.knowledge import ingestion as _knowledge_ingestion
from atri_qq_bot.knowledge import retrieval as _knowledge_retrieval
from ..page import knowledge as _knowledge_page
from .handler_support import WebUIHandlerMixin
from .handler_account import view_memory_admin_for, is_read_only_view_for


class HandlerKnowledgeMixin(WebUIHandlerMixin):
    def _knowledge_reader(self):
        return _knowledge_store.KnowledgeStore.for_memory(view_memory_admin_for(self).memory_path, read_only=True)

    def _knowledge_writer(self):
        return _knowledge_store.KnowledgeStore.for_memory(self.webui_state.running_memory_admin().memory_path)

    def _knowledge_resume(self):
        if not is_read_only_view_for(self):
            store = self._knowledge_writer()
            if store.path.exists():
                _knowledge_ingestion.start_pending(store, self.webui_state.config)

    def _handle_knowledge_get(self, path, query):
        if path == "/knowledge":
            return self._send_html(_knowledge_page.PAGE)
        params = {key: values[0] for key, values in _knowledge_query(query).items()}
        scope = params.get("scope", "")
        day = params.get("day", "")
        try:
            store = self._knowledge_reader()
            exists = store.path.exists()
            if path == "/api/knowledge/scopes":
                self._knowledge_resume()
                return self._send_json({"ok": True, "scopes": store.scopes() if exists else [],
                                        "read_only": is_read_only_view_for(self)})
            scope = store.validate_scope(scope)
            if day:
                store.validate_day(day)
            if path == "/api/knowledge/sources":
                self._knowledge_resume()
                payload = {"items": store.sources(scope, day) if exists else []}
            elif path == "/api/knowledge/source":
                if not exists:
                    raise KeyError("暂无来源")
                payload = {"source": store.get(scope, params.get("id", ""))}
            elif path == "/api/knowledge/search":
                payload = {"items": _knowledge_retrieval.retrieve(store, scope, params.get("q", ""), day,
                           config=self.webui_state.config) if exists else []}
            elif path == "/api/knowledge/diary":
                store.validate_day(day)
                payload = {"diary": store.diary(scope, day) if exists else
                           {"day": day, "draft": "暂无记录", "authored": None, "evidence": []}}
            elif path == "/api/knowledge/export":
                if not exists:
                    raise KeyError("暂无记录可导出")
                return self._send_download(store.export(scope, day), f"atri-knowledge-{day}.zip", "application/zip")
            else:
                return self._send_error(_KnowledgeHTTP.NOT_FOUND, "接口不存在")
            return self._send_json({"ok": True, **payload})
        except KeyError as exc:
            return self._send_error(_KnowledgeHTTP.NOT_FOUND, str(exc))
        except (ValueError, TypeError) as exc:
            return self._send_error(_KnowledgeHTTP.BAD_REQUEST, str(exc))
        except _knowledge_sqlite.Error:
            return self._send_error(_KnowledgeHTTP.SERVICE_UNAVAILABLE, "知识库暂不可用，请稍后重试")

    def _handle_knowledge_post(self, path):
        if self._refuse_when_read_only("修改知识库"):
            return
        try:
            # Dedicated bounded reader; the legacy JSON helper silently truncates at 1MB.
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 28_000_000:
                raise ValueError("请求为空或超过 28MB；单个上传文件最多 20MB")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError("请使用 application/json")
            origin = self.headers.get("Origin", "")
            if origin and _knowledge_url(origin).netloc != self.headers.get("Host", ""):
                return self._send_error(_KnowledgeHTTP.FORBIDDEN, "请求来源不匹配")
            payload = _knowledge_json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求必须为 JSON 对象")
            store = self._knowledge_writer()
            scope = store.validate_scope(payload.get("scope", ""))
            source_id = str(payload.get("id", ""))
            if path == "/api/knowledge/import":
                raw = None
                enqueue = "data" in payload
                if enqueue:
                    raw = _knowledge_base64.b64decode(payload["data"], validate=True)
                    if not raw or len(raw) > 20_000_000:
                        raise ValueError("单个文件须为 1 字节至 20MB")
                text = payload.get("text", "")
                if not enqueue and (not isinstance(text, str) or not text.strip()):
                    raise ValueError("请输入正文或上传附件")
                item = store.create(scope, "" if enqueue else text, title=payload.get("title") or payload.get("filename") or "笔记",
                                    kind="material" if enqueue else "note", filename=str(payload.get("filename", "")),
                                    raw=raw, coverage="pending_parse" if enqueue else "user_text", enqueue=enqueue)
                if enqueue:
                    _knowledge_ingestion.start_pending(store, self.webui_state.config)
                result = {"source": item}
            elif path == "/api/knowledge/revise":
                result = {"source": store.revise(scope, source_id, payload.get("text", ""), int(payload["revision"]))}
            elif path == "/api/knowledge/delete":
                store.delete(scope, source_id)
                result = {}
            elif path == "/api/knowledge/retry":
                store.retry(scope, source_id)
                _knowledge_ingestion.start_pending(store, self.webui_state.config)
                result = {}
            elif path == "/api/knowledge/diary":
                result = {"source": store.save_diary(scope, str(payload.get("day", "")), payload.get("text", ""), int(payload.get("revision", 0)))}
            else:
                return self._send_error(_KnowledgeHTTP.NOT_FOUND, "接口不存在")
            return self._send_json({"ok": True, **result})
        except _knowledge_store.RevisionConflict as exc:
            return self._send_error(_KnowledgeHTTP.CONFLICT, str(exc))
        except (ValueError, TypeError, KeyError, _knowledge_binascii.Error, UnicodeError) as exc:
            return self._send_error(_KnowledgeHTTP.BAD_REQUEST, str(exc))
        except _knowledge_sqlite.Error:
            return self._send_error(_KnowledgeHTTP.SERVICE_UNAVAILABLE, "知识库暂不可用，请稍后重试")
