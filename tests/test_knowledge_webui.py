from __future__ import annotations

import base64
import http.server
import io
import json
import threading
import zipfile
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from atri_qq_bot.knowledge import KnowledgeStore
from atri_qq_bot.knowledge import ingestion
from atri_webui import server as webui_server


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, "start_pending", lambda *a: None)
    admin = SimpleNamespace(memory_path=tmp_path / "running" / "users.json")
    other = SimpleNamespace(memory_path=tmp_path / "other" / "users.json")
    state = SimpleNamespace(config=SimpleNamespace(), read_only=False)
    state.running_memory_admin = lambda: admin
    state.view_memory_admin = lambda: other if state.read_only else admin
    state.is_read_only_view = lambda: state.read_only

    class Handler(webui_server.AtriWebUIHandler):
        webui_state = state

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, payload=None, decode=True, **headers):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(f"http://127.0.0.1:{server.server_port}{path}", data=data,
                      headers={"Content-Type": "application/json", **headers})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            return response.code, json.loads(body) if decode else body

    yield request, state, admin, other
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_workbench_text_diary_search_correction_export_and_delete(workbench):
    request, state, admin, _ = workbench
    assert request("/knowledge", decode=False)[0] == 200
    status, result = request("/api/knowledge/scopes")
    assert result["scopes"] == []
    assert not (admin.memory_path.parent / "knowledge.sqlite3").exists()
    status, result = request("/api/knowledge/import", {"scope": "private:1", "title": "物理", "text": "旧词拉格朗日"})
    assert status == 200
    source = result["source"]
    query = urlencode({"scope": "private:1", "day": source["day"]})
    _, result = request("/api/knowledge/diary?" + query)
    assert "拉格朗日" in result["diary"]["draft"]
    status, _ = request("/api/knowledge/diary", {"scope": "private:1", "day": source["day"], "text": "复习完成"})
    assert status == 200
    status, result = request("/api/knowledge/revise", {"scope": "private:1", "id": source["id"], "revision": 1, "text": "新词哈密顿量"})
    assert status == 200 and result["source"]["revision"] == 2
    assert request("/api/knowledge/revise", {"scope": "private:1", "id": source["id"], "revision": 1, "text": "stale"})[0] == 409
    _, result = request("/api/knowledge/search?" + query + "&q=" + urlencode({"": "拉格朗日"})[1:])
    assert result["items"] == []
    _, result = request("/api/knowledge/search?" + query + "&" + urlencode({"q": "哈密顿量"}))
    assert result["items"][0]["id"] == source["id"]
    _, result = request("/api/knowledge/diary?" + query)
    assert "拉格朗日" not in result["diary"]["draft"]
    assert result["diary"]["authored"]["text"] == "复习完成"
    status, body = request("/api/knowledge/export?" + query, decode=False)
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert "哈密顿量" in archive.read(source["day"] + ".md").decode()
    assert request("/api/knowledge/delete", {"scope": "private:1", "id": source["id"]})[0] == 200
    assert request("/api/knowledge/source?" + urlencode({"scope": "private:1", "id": source["id"]}))[0] == 404


def test_read_only_account_selection_isolates_reads_and_refuses_all_writes(workbench):
    request, state, admin, other = workbench
    first = KnowledgeStore.for_memory(admin.memory_path)
    first.create("private:1", "运行账号独有秘密")
    state.read_only = True
    assert request("/api/knowledge/scopes")[1]["scopes"] == []
    assert not (other.memory_path.parent / "knowledge.sqlite3").exists()
    second = KnowledgeStore.for_memory(other.memory_path)
    source = second.create("private:1", "另一个账号记录")
    assert request("/api/knowledge/scopes")[1]["read_only"]
    query = urlencode({"scope": "private:1", "q": "秘密"})
    assert request("/api/knowledge/search?" + query)[1]["items"] == []
    for action in ("import", "revise", "delete", "diary", "retry"):
        assert request("/api/knowledge/" + action, {"scope": "private:1", "id": source["id"], "text": "x"})[0] == 400
    assert second.get("private:1", source["id"])["text"] == "另一个账号记录"


def test_attachment_persists_before_parsing_and_invalid_inputs_are_rejected(workbench):
    request, state, admin, _ = workbench
    status, result = request("/api/knowledge/import", {"scope": "private:1", "filename": "code.py", "data": base64.b64encode(b"print(123)").decode()})
    assert status == 200
    assert result["source"]["job_status"] == "pending"
    assert result["source"]["raw_bytes"] == 10
    for data in ({"scope": ""}, {"scope": "private:1", "data": "bad!"}, {"scope": "private:1", "text": 5}):
        assert request("/api/knowledge/import", data)[0] == 400
    assert request("/api/knowledge/import", {"scope": "private:1", "text": "a"}, Origin="https://other.invalid")[0] == 403
    assert request("/api/knowledge/sources?scope=private:1&day=invalid")[0] == 400
