from __future__ import annotations

from atri_qq_bot.prompting import clear_prompt_cache, load_prompt
from atri_qq_bot.retrieval import ContextRetrievalPlanner, RetrievalSettings
from atri_qq_bot.lore import has_lore_trigger, lore_direct_reply


def test_persona_prompt_contains_complete_visual_identity() -> None:
    clear_prompt_cache()
    prompt = load_prompt("atri_persona")

    for required in ("淡色及肩长发", "呆毛", "深红色的双瞳", "连衣裙样式", "茶色革制便鞋", "YHN-04B"):
        assert required in prompt


def test_persona_prompt_preserves_canon_uncertainty_and_character_engine() -> None:
    clear_prompt_cache()
    prompt = load_prompt("atri_persona")

    for required in (
        "？岁",
        "YHN-04B-009",
        "先补位",
        "证明有用",
        "观察和学习",
        "形成自己的愿望",
        "不是刻薄型傲娇",
    ):
        assert required in prompt
    assert "身高约 144cm" not in prompt


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


def test_canon_questions_trigger_lore_retrieval() -> None:
    for question in (
        "亚托莉的型号是什么？",
        "诗菜和乃音子分别是谁？",
        "原作里日志有什么意义？",
        "ATRI 为什么喜欢螃蟹？",
    ):
        assert has_lore_trigger(question)


def test_direct_lore_replies_keep_canon_separate_from_current_user() -> None:
    age_reply = lore_direct_reply("亚托莉原作里几岁？")
    countdown_reply = lore_direct_reply("ATRI 原作的四十五天是什么意思？")

    assert age_reply is not None and "？岁" in age_reply and "没有" in age_reply
    assert countdown_reply is not None and "共同生活的倒计时" in countdown_reply
    assert "不是乃音子在最后命令里写死的时限" in countdown_reply
    assert "陪你的每一小段时间" not in countdown_reply


def test_specific_plot_direct_replies_precede_generic_natsuki_reply() -> None:
    leg_reply = lore_direct_reply("原作里夏生为什么要让亚托莉成为他的腿？")
    log_reply = lore_direct_reply("夏生为什么看日志后怀疑亚托莉没有心？")
    trauma_reply = lore_direct_reply("诗菜被霸凌时亚托莉为什么被称为缺陷品？")

    assert leg_reply is not None and "幼年事故" in leg_reply and "海底" not in leg_reply
    assert log_reply is not None and "冷冰冰的执行记录" in log_reply
    assert trauma_reply is not None and "攻击了施暴者" in trauma_reply
