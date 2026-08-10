from __future__ import annotations

from atri_qq_bot.retrieval import ContextRetrievalPlanner, RetrievalSettings, SemanticMemoryRepository


def test_repository_uses_fts5_with_a_hard_scope_boundary(tmp_path) -> None:
    repo = SemanticMemoryRepository(tmp_path / "semantic.sqlite3")
    repo.replace_scope_source(
        "private:10001",
        "user_profile",
        [{"layer": "l1", "title": "兴趣", "content": "喜欢铜锣烧", "importance": 0.9}],
    )
    repo.replace_scope_source(
        "private:20002",
        "user_profile",
        [{"layer": "l1", "title": "私密", "content": "生日是 8 月 2 日", "importance": 0.9}],
    )

    assert [item.content for item in repo.search("private:10001", "铜锣烧")] == ["喜欢铜锣烧"]
    assert repo.search("private:10001", "生日") == []


def test_planner_uses_relevant_profile_memory_and_stays_compact(tmp_path) -> None:
    planner = ContextRetrievalPlanner(
        RetrievalSettings(enabled=True, database_path=tmp_path / "semantic.sqlite3", max_context_chars=900)
    )
    profile = {
        "conversation_id": "private:10001",
        "affection_state": "相处得很自然",
        "personal_question_interval": "五到八轮",
        "structured_memory": {
            "l1": [
                {
                    "category": "interest", "key": "喜欢的食物", "value": "铜锣烧",
                    "confidence": 0.9, "updated_at": 1,
                }
            ],
            "l2": [], "l3": [], "candidates": [],
        },
    }

    context = planner.build(profile, "今天吃点什么好")

    assert "铜锣烧" in context
    assert "不要说自己在读取记忆" in context
    assert len(context) < 900


def test_planner_retrieves_lore_only_for_lore_questions(tmp_path, monkeypatch) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "lore.md").write_text("# 世界设定\n亚托莉是 YHN-04B，高性能机器人。", encoding="utf-8")
    (prompt_dir / "atri_persona.md").write_text("# 角色\n她会嘴硬，但不编造原作细节。", encoding="utf-8")
    monkeypatch.setattr("atri_qq_bot.retrieval.planner.PROMPT_DIR", prompt_dir)

    planner = ContextRetrievalPlanner(RetrievalSettings(enabled=True, database_path=tmp_path / "semantic.sqlite3"))
    profile = {
        "conversation_id": "private:1", "personal_question_interval": "五到八轮",
        "structured_memory": {"l1": [], "l2": [], "l3": [], "candidates": []},
    }

    lore_context = planner.build(profile, "亚托莉的型号是什么？")
    casual_context = planner.build(profile, "今天心情有点差")

    assert "YHN-04B" in lore_context
    assert "YHN-04B" not in casual_context


def test_repository_can_store_and_search_optional_vectors_without_a_vector_database(tmp_path) -> None:
    repo = SemanticMemoryRepository(tmp_path / "semantic.sqlite3")
    repo.replace_scope_source(
        "private:1",
        "user_profile",
        [
            {"layer": "l1", "title": "兴趣", "content": "喜欢音游", "importance": 0.9},
            {"layer": "l1", "title": "兴趣", "content": "喜欢做饭", "importance": 0.9},
        ],
    )
    candidates = repo.embedding_candidates("bge-m3:latest")
    vectors = {entry_id: ([1.0, 0.0] if "音游" in content else [0.0, 1.0]) for entry_id, content in candidates}
    for entry_id, vector in vectors.items():
        repo.save_embedding(entry_id, "bge-m3:latest", vector)

    result = repo.vector_search("private:1", "bge-m3:latest", [0.95, 0.05])

    assert result[0].content == "喜欢音游"
    assert repo.embedding_count("bge-m3:latest") == 2
