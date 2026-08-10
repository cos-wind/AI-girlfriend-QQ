from __future__ import annotations

from atri_qq_bot.prompting import PROMPT_DIR, load_prompt, render_prompt


PROMPT_NAMES = (
    "atri_persona",
    "reply_contract",
    "language_guard",
    "language_retry",
    "rewrite",
    "comfort_repair",
    "group_chat",
    "lore",
    "tool_use",
    "visual_analysis",
    "voice_policy",
    "iteration",
    "scene_control",
    "proactive",
    "proactive_topic_rule",
)


def test_all_runtime_prompt_documents_are_loadable() -> None:
    for name in PROMPT_NAMES:
        content = load_prompt(name)
        assert content
        assert (PROMPT_DIR / f"{name}.md").is_file()


def test_prompt_loader_renders_only_named_placeholders() -> None:
    rendered = render_prompt("voice_policy", explicit="允许", autonomous="不允许", relation="私聊")
    assert "允许" in rendered
    assert "不允许" in rendered
    assert "{{explicit}}" not in rendered
