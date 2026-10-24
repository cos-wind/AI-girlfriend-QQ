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


def test_planner_injects_persistent_group_rules_and_topics(tmp_path) -> None:
    """人工写进记忆的"规范"与"话题"要常驻注入，不靠关键词碰运气。

    历史问题：一条"不要有攻击性"只有在这句话恰好聊到"攻击"时才会被 FTS 召回，
    日常聊天根本碰不到它，于是"写了规范却不起效"。
    """

    planner = ContextRetrievalPlanner(
        RetrievalSettings(enabled=True, database_path=tmp_path / "semantic.sqlite3")
    )
    profile = {
        "conversation_id": "group:20001",
        "personal_question_interval": "五到八轮",
        "structured_memory": {
            "l1": [
                {"key": "profile_fact:新记忆", "value": "温柔可爱不要有攻击性", "confidence": 0.9, "updated_at": 1},
                {"key": "兴趣", "value": "原神", "confidence": 0.9, "updated_at": 2},
                {"key": "群体讨厌", "value": "ntr", "confidence": 0.9, "updated_at": 3},
            ],
            "l2": [{"key": "major:negative", "value": "蠢货", "confidence": 0.7, "updated_at": 4}],
            "l3": [], "candidates": [],
        },
    }

    context = planner.build(profile, "今天天气不错")  # 与规范/话题关键词都无关

    assert "本群约定" in context
    assert "温柔可爱不要有攻击性" in context
    assert "本群偏好与话题" in context
    assert "原神" in context
    # 负面类目与 L2 事件不进入常驻注入
    assert "ntr" not in context
    assert "蠢货" not in context


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


def test_lore_index_excludes_generic_persona_chunks_from_plot_retrieval(tmp_path, monkeypatch) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "lore.md").write_text(
        "# 起点：命令与有用性\n亚托莉提出成为夏生先生的腿，因为她想用行动补足夏生的困难。",
        encoding="utf-8",
    )
    (prompt_dir / "atri_persona.md").write_text(
        "# 通用人格\n亚托莉说话要自然、简短，不要每句话使用高性能。",
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.retrieval.planner.PROMPT_DIR", prompt_dir)

    planner = ContextRetrievalPlanner(
        RetrievalSettings(enabled=True, database_path=tmp_path / "semantic.sqlite3")
    )
    profile = {
        "conversation_id": "private:1",
        "personal_question_interval": "五到八轮",
        "structured_memory": {"l1": [], "l2": [], "l3": [], "candidates": []},
    }

    planner.build(profile, "为什么要成为夏生先生的腿？")
    entries = planner.repository.search("lore:atri", "为什么要成为夏生先生的腿？", 10)

    assert entries
    assert all(entry.metadata.get("document") == "lore.md" for entry in entries)
    assert "补足夏生的困难" in entries[0].content


def test_plot_lore_marks_forty_five_days_as_a_negotiated_period(tmp_path, monkeypatch) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "lore.md").write_text(
        "# 起点\n四十五天是向夏生争取的共同生活与暂缓处理期限，不是乃音子原命令写死的时限。",
        encoding="utf-8",
    )
    monkeypatch.setattr("atri_qq_bot.retrieval.planner.PROMPT_DIR", prompt_dir)
    planner = ContextRetrievalPlanner(
        RetrievalSettings(enabled=True, database_path=tmp_path / "semantic.sqlite3")
    )
    profile = {
        "conversation_id": "private:1",
        "personal_question_interval": "五到八轮",
        "structured_memory": {"l1": [], "l2": [], "l3": [], "candidates": []},
    }

    context = planner.build(profile, "四十五天是原作命令写死的吗？")

    assert "共同生活与暂缓处理期限" in context
    assert "不是乃音子原命令写死的时限" in context


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
