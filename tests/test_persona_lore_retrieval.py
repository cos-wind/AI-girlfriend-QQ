from __future__ import annotations

from atri_qq_bot.prompting import clear_prompt_cache, load_prompt
from atri_qq_bot.retrieval import ContextRetrievalPlanner, RetrievalSettings
from atri_qq_bot.lore import appearance_direct_reply


def test_persona_prompt_contains_complete_visual_identity() -> None:
    clear_prompt_cache()
    prompt = load_prompt("atri_persona")

    for required in ("淡色及肩长发", "呆毛", "深红色的双瞳", "连衣裙样式", "茶色革制便鞋", "YHN-04B"):
        assert required in prompt


def test_lore_retrieval_recognises_atri_appearance_question(tmp_path) -> None:
    planner = ContextRetrievalPlanner(
        RetrievalSettings(enabled=True, database_path=tmp_path / "semantic.sqlite3")
    )
    profile = {
        "conversation_id": "private:appearance-test",
        "personal_question_interval": "五到八轮",
        "structured_memory": {"l1": [], "l2": [], "l3": [], "candidates": []},
    }

    context = planner.build(profile, "亚托莉，你还记得自己的外貌吗？发色、眼睛和衣服是什么样？")

    assert "深红色" in context
    assert "连衣裙" in context
    assert "YHN-04B" in context


def test_appearance_question_has_stable_fact_reply() -> None:
    reply = appearance_direct_reply(
        "亚托莉，你还记得自己的外貌吗？请说出发色、眼睛、衣服和型号。"
    )

    assert reply is not None
    for required in ("淡色及肩长发", "深红色", "连衣裙", "YHN-04B"):
        assert required in reply


def test_appearance_fallback_does_not_intercept_unrelated_chat() -> None:
    assert appearance_direct_reply("今天的天气怎么样？") is None
    assert appearance_direct_reply("这张图片里的人穿了什么？") is None
