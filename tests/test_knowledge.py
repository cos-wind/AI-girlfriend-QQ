from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import struct
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from atri_qq_bot.knowledge import KnowledgeStore
from atri_qq_bot.knowledge.ingestion import archive_analysis, run_pending
from atri_qq_bot.knowledge.store import RevisionConflict
from atri_qq_bot.memory import UserMemoryStore
from atri_qq_bot.retrieval import SemanticMemoryRepository
from atri_qq_bot.toolbox import ToolAnalyzer


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path / "knowledge.sqlite3")


def test_full_original_restart_deduplication_and_scope(store):
    text = "学习记录\n" * 900 + "末尾边界公式 E=mc^2"
    item = store.create("private:1", text, external_id="message:123")
    same = store.create("private:1", "重复投递", external_id="message:123")
    assert item["id"] == same["id"]
    second = store.create("private:1", text)
    assert second["id"] != item["id"]
    reopened = KnowledgeStore(store.path)
    assert reopened.get("private:1", item["id"])["text"] == text
    assert reopened.search("private:1", "末尾边界公式")
    assert reopened.search("private:2", "末尾边界公式") == []
    with pytest.raises(KeyError):
        reopened.get("private:2", item["id"])


def test_revision_replaces_index_and_draft_but_preserves_authored_diary(store):
    item = store.create("private:1", "旧词彩虹猫", title="学习", occurred_at=1792500000)
    day = item["day"]
    authored = store.save_diary("private:1", day, "今天我很开心")
    revised = store.revise("private:1", item["id"], "新词流星雨", 1)
    assert revised["revision"] == 2
    assert not store.search("private:1", "彩虹猫")
    assert store.search("private:1", "流星雨")[0]["revision"] == 2
    diary = store.diary("private:1", day)
    assert "彩虹猫" not in diary["draft"] and "流星雨" in diary["draft"]
    assert diary["authored"]["text"] == "今天我很开心"
    assert store.search("private:1", "开心")[0]["kind"] == "diary"
    with pytest.raises(RevisionConflict):
        store.revise("private:1", item["id"], "过期页面", 1)
    with pytest.raises(RevisionConflict):
        store.save_diary("private:1", day, "过期日记", 0)
    assert store.get("private:1", authored["id"])["text"] == "今天我很开心"
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT text FROM knowledge_revisions WHERE source_id=? AND revision=1", (item["id"],)).fetchone()[0] == "旧词彩虹猫"


def test_beijing_day_boundaries_and_date_recall(store):
    before = datetime(2026, 10, 20, 15, 59, tzinfo=timezone.utc).timestamp()
    after = before + 60
    one = store.create("private:1", "昨天玩游戏", occurred_at=before)
    two = store.create("private:1", "今天学习线性代数", occurred_at=after)
    assert one["day"] == "2026-10-20" and two["day"] == "2026-10-21"
    assert len(store.sources("private:1", "2026-10-21")) == 1
    assert not store.search("private:1", "游戏", "2026-10-21")
    assert "线性代数" in store.recall("private:1", "回顾 2026-10-21")
    assert "昨天玩游戏" not in store.recall("private:1", "回顾 2026-10-21")


def test_delete_purges_evidence_vectors_attachments_and_blocks_stale_job(store):
    item = store.create("private:1", "初始记录", raw=b"original", filename="x.txt", enqueue=True)
    job = store.claim_job()
    entry_id = store.index.embedding_candidates("fake")[0][0]
    store.index.save_embedding(entry_id, "fake", [1, 0])
    store.delete("private:1", item["id"])
    assert not store.finish_job(job, text="僵尸结果")
    assert not store.search("private:1", "初始记录")
    assert store.index.embedding_count() == 0
    assert item["id"] not in store.diary("private:1", item["day"])["draft"]
    with sqlite3.connect(store.path) as conn:
        for table in ("knowledge_sources", "knowledge_revisions", "knowledge_jobs"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_job_leases_restart_correction_and_explicit_retry(store):
    item = store.create("private:1", "", raw=b"data", enqueue=True)
    job1 = store.claim_job(lease_seconds=-1)
    job2 = KnowledgeStore(store.path).claim_job()
    assert job1["token"] != job2["token"]
    assert not store.finish_job(job1, text="旧 worker")
    assert store.claim_job() is None
    assert store.finish_job(job2, error="临时失败")
    assert store.get("private:1", item["id"])["job_status"] == "failed"
    assert store.claim_job() is None
    store.retry("private:1", item["id"])
    job3 = store.claim_job()
    store.revise("private:1", item["id"], "用户纠正", 1)
    assert not store.finish_job(job3, text="过期解析")
    assert store.get("private:1", item["id"])["text"] == "用户纠正"


def test_durable_file_job_runs_existing_parser_without_network(store):
    raw = ("原始代码\n" * 800 + "尾部公式token").encode()
    item = store.create("private:1", "", raw=raw, filename="sample.py", enqueue=True)
    assert run_pending(KnowledgeStore(store.path), SimpleNamespace(toolbox_vision_enabled=False)) == 1
    result = store.get("private:1", item["id"])
    assert result["job_status"] == "done"
    assert result["text"] == raw.decode()
    assert result["revision"] == 2
    assert store.search("private:1", "尾部公式")


def test_export_has_original_and_current_revision_without_other_scope(store):
    item = store.create("private:1", "傅里叶变换", raw=b"original", filename="../../example.txt")
    store.create("private:2", "另一人的秘密")
    store.revise("private:1", item["id"], "傅里叶级数", 1)
    with zipfile.ZipFile(io.BytesIO(store.export("private:1", item["day"]))) as archive:
        names = archive.namelist()
        assert all(".." not in name for name in names)
        markdown = archive.read(item["day"] + ".md").decode()
        assert "傅里叶级数" in markdown and "另一人的秘密" not in markdown
        assert archive.read(f"attachments/{item['id']}/example.txt") == b"original"
        source = json.loads(archive.read(f"sources/{item['id']}.json"))
        assert source["revision"] == 2


def test_generated_diary_is_not_extra_evidence_and_roles_are_explicit(store):
    item = store.create("private:1", "我准备打游戏", kind="message")
    store.create("private:1", "我已经替你打通关了", kind="assistant", coverage="assistant_output")
    for _ in range(3):
        draft = store.diary("private:1", item["day"])["draft"]
        assert "用户说" in draft and "助手回复" in draft
    assert len(store.sources("private:1")) == 2


def test_private_memory_captures_before_shortening_and_skips_group_promotions(tmp_path):
    memory = UserMemoryStore(tmp_path / "users.json")
    full = "我今天研究物理\n" * 400 + "稀有尾部关键字"
    memory.observe_user("private:1", full, event_id="same")
    memory.observe_user("private:1", full, event_id="same")
    memory.observe_user("private:1", "群里公开的身份", visibility="group", source_context="group:2")
    memory.observe_user("group:2", "群消息")
    memory.observe_bot("private:1", "这是回复")
    items = memory.knowledge.sources("private:1")
    assert len(items) == 2
    saved = next(i for i in items if i["kind"] == "message")
    assert memory.knowledge.get("private:1", saved["id"])["text"] == full
    assert "稀有尾部关键字" in memory.recall_context("private:1", "稀有尾部关键字")
    assert memory.knowledge.sources("group:2") == []


def test_read_only_does_not_create_or_mutate_sources(tmp_path, store):
    missing = KnowledgeStore(tmp_path / "absent.sqlite3", read_only=True)
    missing.ensure_schema()
    assert not missing.path.exists()
    item = store.create("private:1", "知识")
    reader = KnowledgeStore(store.path, read_only=True)
    assert reader.get("private:1", item["id"])["text"] == "知识"
    with pytest.raises(ValueError):
        reader.revise("private:1", item["id"], "不能写", 1)


def test_embeddings_survive_refresh_and_models_coexist(tmp_path):
    repo = SemanticMemoryRepository(tmp_path / "semantic.sqlite3")
    rows = [{"title": "学习", "content": "矩阵乘法"}]
    repo.replace_scope_source("private:1", "profile", rows)
    key = repo.embedding_candidates("a")[0][0]
    repo.save_embedding(key, "a", [1, 0])
    repo.save_embedding(key, "b", [0, 1])
    repo.replace_scope_source("private:1", "profile", rows)
    assert repo.embedding_count() == 2
    assert repo.embedding_candidates("a") == []
    repo.replace_scope_source("private:1", "profile", [{"title": "学习", "content": "微积分"}])
    assert repo.embedding_count() == 0
    repo.save_embedding(key, "a", [1, 0])  # late embedding may not resurrect removed content
    assert repo.embedding_count() == 0


def test_legacy_embedding_schema_migration_retains_vectors(tmp_path):
    path = tmp_path / "old.sqlite3"
    repo = SemanticMemoryRepository(path)
    repo.replace_scope_source("private:1", "profile", [{"title": "学习", "content": "矩阵"}])
    key = repo.embedding_candidates("a")[0][0]
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE semantic_embeddings")
        conn.execute("CREATE TABLE semantic_embeddings(entry_id TEXT PRIMARY KEY,model TEXT,dimensions INTEGER,vector BLOB,updated_at REAL)")
        conn.execute("INSERT INTO semantic_embeddings VALUES (?,?,?,?,?)", (key, "a", 2, struct.pack("<2f", 1, 0), 1))
    migrated = SemanticMemoryRepository(path)
    assert migrated.embedding_count("a") == 1
    migrated.save_embedding(key, "b", [0, 1])
    assert migrated.embedding_count() == 2
    assert migrated.vector_search("private:1", "a", [1, 0])[0].content == "矩阵"


def test_pdf_keeps_page_anchors_and_admits_twenty_page_limit(monkeypatch, store):
    import pypdf

    pages = [SimpleNamespace(extract_text=lambda i=i: f"第{i + 1}页微积分原文") for i in range(25)]
    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(pages=pages))
    analyzer = ToolAnalyzer(SimpleNamespace())
    result = asyncio.run(analyzer._analyze_file_bytes(b"pdf original", "paper.pdf", "paper.pdf"))
    material = result.knowledge_materials[0]
    assert "1-20/25" in material["coverage"]
    assert material["blocks"][-1]["anchor"] == "page:20"
    assert "第25页" not in material["text"]
    source_id = archive_analysis(store, "private:1", result, event_id="pdf1")[0]
    assert store.get("private:1", source_id)["raw_bytes"] == len(b"pdf original")
    assert store.search("private:1", "微积分")[0]["anchor"].startswith("page:")


def test_archival_field_does_not_enter_model_prompt():
    from atri_qq_bot.toolbox_parts.analysis_result import ToolAnalysisResult

    result = ToolAnalysisResult("学术", "严谨", findings=["摘要"],
                                knowledge_materials=[{"text": "ARCHIVE_ONLY_TEXT", "raw": b"secret"}])
    assert "ARCHIVE_ONLY_TEXT" not in result.prompt_context()
    assert "ARCHIVE_ONLY_TEXT" not in repr(result)


def test_semantic_retrieval_fuses_rankings_and_obeys_scope_and_revision(store):
    one = store.create("private:1", "离散傅里叶变换", title="数学")
    other = store.create("private:2", "秘密音乐", title="私密")
    for key, text in store.index.embedding_candidates("fake"):
        store.index.save_embedding(key, "fake", [1, 0])
    reader = KnowledgeStore(store.path, read_only=True)
    hits = reader.search("private:1", "频谱分析", vector=[1, 0], model="fake")
    assert hits and {h["id"] for h in hits} == {one["id"]}
    assert other["id"] not in {h["id"] for h in hits}
    store.revise("private:1", one["id"], "张量运算", 1)
    assert not reader.index.vector_search("private:1", "fake", [1, 0])
    assert not reader.search("private:1", "频谱分析", vector=[1, 0], model="fake")


def test_edit_and_index_rollback_together_on_index_failure(store, monkeypatch):
    item = store.create("private:1", "有效原始记录")

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store.index, "replace_scope_source", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.revise("private:1", item["id"], "未提交新记录", 1)
    assert store.get("private:1", item["id"])["revision"] == 1
    assert store.search("private:1", "原始记录")
    assert not store.search("private:1", "未提交")


def test_concurrent_claim_has_only_one_owner(store):
    from concurrent.futures import ThreadPoolExecutor

    store.create("private:1", "", raw=b"x", enqueue=True)
    with ThreadPoolExecutor(max_workers=2) as workers:
        jobs = list(workers.map(lambda _: KnowledgeStore(store.path).claim_job(), range(2)))
    assert len([j for j in jobs if j is not None]) == 1


def test_raw_original_survives_parser_failure_and_can_be_exported(store):
    item = store.create("private:1", "", raw=b"not a real docx", filename="bad.docx", enqueue=True)
    assert run_pending(store, SimpleNamespace()) == 1
    source = store.get("private:1", item["id"])
    assert source["job_status"] == "failed"
    with zipfile.ZipFile(io.BytesIO(store.export("private:1", item["day"]))) as archive:
        assert archive.read(f"attachments/{item['id']}/bad.docx") == b"not a real docx"


def test_vector_unavailable_falls_back_to_full_text(store, monkeypatch):
    from atri_qq_bot.knowledge import retrieval

    store.create("private:1", "向量失败仍应找到的拉普拉斯变换")
    key = store.index.embedding_candidates("fake")[0][0]
    store.index.save_embedding(key, "fake", [1, 0])

    def fail(*args):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(retrieval.OllamaEmbeddingClient, "embed", fail)
    hits = retrieval.retrieve(store, "private:1", "拉普拉斯变换", config=SimpleNamespace(memory_vector_enabled=True, memory_embedding_model="fake"))
    assert hits and "拉普拉斯" in hits[0]["content"]


def test_unsupported_file_is_failed_instead_of_indexing_filename_as_content(store):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("main.py", "print(123)")
    item = store.create("private:1", "", raw=raw.getvalue(), filename="project.zip", enqueue=True)
    run_pending(store, SimpleNamespace())
    source = store.get("private:1", item["id"])
    assert source["job_status"] == "failed"
    assert source["raw_bytes"] == len(raw.getvalue())
    assert not store.search("private:1", "project")


def test_video_original_is_archived_when_frame_analysis_is_disabled(store):
    analyzer = ToolAnalyzer(SimpleNamespace(toolbox_video_frame_analysis_enabled=False))
    analyzer.video_frame_analysis_enabled = False
    result = asyncio.run(analyzer._analyze_video_bytes(b"video bytes", "clip.mp4", "clip.mp4"))
    source_id = archive_analysis(store, "private:1", result)[0]
    source = store.get("private:1", source_id)
    assert source["raw_bytes"] == 11
    assert source["coverage"] == "video_original_only;frame_analysis_disabled"
