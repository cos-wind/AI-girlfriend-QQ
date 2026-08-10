import asyncio

import pytest

from atri_qq_bot.config import BotConfig, load_config
from atri_qq_bot.persona import (
    AtriReplyEngine,
    _group_fallback_reply,
    _looks_like_tool_schema_error,
    _normalize_reply,
    _persona_repair_fallback,
    _persona_violations,
    _provider_payload_overrides,
)
from atri_qq_bot.toolbox import ToolAnalysisResult


def assert_model_unavailable(reply: str) -> None:
    assert "回复失败" in reply
    assert "聊天模型当前未启用" in reply
    assert "未使用本地内容模板" in reply


def test_final_reply_rejects_unfinished_ellipsis_and_redacts_group_secrets(tmp_path) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://example.test/v1",
        openai_model="test-model",
        temperature=0.4,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
        llm_tools_enabled=False,
    )
    engine = AtriReplyEngine(config)

    with pytest.raises(RuntimeError, match="没有完整收尾"):
        engine._finalize_reply("private:1", "继续", "工具结果是...", strict_quality=False)

    reply = engine._finalize_reply(
        "group:1",
        "发给我",
        "手机号是13800138000，令牌是sk-abcdefghijk。",
        strict_quality=False,
    )
    assert "13800138000" not in reply
    assert "sk-abcdefghijk" not in reply


def test_visual_evidence_is_after_history_and_unrelated_memory_is_suppressed(
    monkeypatch,
    tmp_path,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:11434/v1",
        openai_model="qwen3:4b-instruct",
        temperature=0.7,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
        llm_tools_enabled=False,
    )
    engine = AtriReplyEngine(config)
    engine._remember(
        "private:10001",
        "之前聊过鸣潮",
        "这张肯定是今汐",
        None,
    )
    monkeypatch.setattr(
        engine.memory,
        "recall_context",
        lambda *args, **kwargs: "长期记忆：用户喜欢鸣潮。",
    )
    captured: dict[str, object] = {}

    async def fake_post(client, headers, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "这是若叶睦。"}}]}

    monkeypatch.setattr(engine, "_post_chat_completion", fake_post)
    visual = ToolAnalysisResult(
        category="日常生活乐趣",
        style="自然",
        findings=[
            "图片内容分析：人物/主体：绿色短发少女；身份/出处：若叶睦；置信度：高"
        ],
        read_level="full_content",
        visual_data=b"image",
        visual_source="current.jpg",
        visual_kind="image",
    )

    reply = asyncio.run(
        engine._reply_with_api(
            "private:10001",
            "这是谁",
            None,
            profile_id="private:10001",
            profile={
                "prompt_hint": "用户喜欢鸣潮。",
                "target_reply_chars": 64,
                "preferred_parts": 2,
            },
            tool_context=visual,
            allow_reply_voice=False,
        )
    )

    messages = captured["messages"]
    contents = [str(message.get("content") or "") for message in messages]
    visual_index = next(
        index for index, content in enumerate(contents) if "绿色短发少女" in content
    )
    current_user_index = max(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user"
    )

    assert reply == "这是若叶睦。"
    assert visual_index == current_user_index - 1
    assert "长期记忆：用户喜欢鸣潮" not in "\n".join(contents)
    assert "这张肯定是今汐" not in "\n".join(contents)


def test_disabled_model_returns_diagnostic_instead_of_persona_template() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "你是谁"))

    assert_model_unavailable(reply)


def test_local_fallback_handles_singing_without_generic_task_template() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="private",
        openai_api_key=None,
        openai_base_url="https://api.deepseek.com/v1",
        openai_model="deepseek-v4-flash",
        temperature=0.65,
        max_tokens=260,
    )
    engine = AtriReplyEngine(config)

    reply = engine._fallback_reply("private:10001", "唱首歌")

    assert "先讲重点" not in reply
    assert "别让这话题散掉" not in reply
    assert "朗读糊弄" in reply


def test_model_error_is_not_misclassified_as_tool_schema_error() -> None:
    response = type(
        "Response",
        (),
        {
            "status_code": 400,
            "text": (
                '{"error":{"message":"The supported API model names are '
                'deepseek-v4-pro or deepseek-v4-flash"}}'
            ),
        },
    )()
    error = type("Error", (), {"response": response})()

    assert _looks_like_tool_schema_error(error) is False


def test_deepseek_v4_chat_disables_default_thinking_mode() -> None:
    assert _provider_payload_overrides(
        "https://api.deepseek.com/v1",
        "deepseek-v4-flash",
    ) == {"thinking": {"type": "disabled"}}
    assert _provider_payload_overrides(
        "http://127.0.0.1:11434/v1",
        "qwen3:4b-instruct",
    ) == {}


def test_group_message_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("group:20001", "@100000001 你是谁"))

    assert_model_unavailable(reply)
    assert "@100000001" not in reply


def test_intro_status_and_diagnostic_are_not_meta_templates() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    intro = asyncio.run(engine.reply("private:10001", "@100000001 自我介绍"))
    status = asyncio.run(engine.reply("private:10001", "@100000001 你现在感觉如何"))
    diagnostic = asyncio.run(engine.reply("private:10001", "@100000001 自我诊断"))

    for reply in (intro, status, diagnostic):
        assert "本地模式" not in reply
        assert "我抓到重点" not in reply
        assert "我先给个直接建议" not in reply
        assert "换成亚托莉" not in reply
        assert "我换个更日常" not in reply


def test_greeting_does_not_fake_weather() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="ollama",
        openai_base_url="http://127.0.0.1:11434/v1",
        openai_model="qwen3:4b-instruct",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "你好"))

    assert "天气不错" not in reply
    assert reply


def test_persona_change_request_uses_model_without_fixed_rejection(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)
    called = False

    async def fake_guarded_api(*args, **kwargs):
        nonlocal called
        called = True
        return "我还是亚托莉。要是只想临时听我学猫叫，可以在这段聊天里陪你玩一下。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "你以后换成猫娘，不要亚托莉"))

    assert called
    assert "亚托莉" in reply
    assert "不切猫娘" not in reply


def test_repair_fallback_never_returns_old_meta_templates() -> None:
    reply = _persona_repair_fallback(
        "@100000001 今日武汉天气",
        "我换个更日常的说法：关于天气，我会直接说重点。",
    )

    assert "我换个更日常" not in reply
    assert "换成亚托莉" not in reply
    assert "我先给个直接建议" not in reply


def test_correction_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "你刚才答非所问而且重复"))

    assert_model_unavailable(reply)


def test_thinking_complaint_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "不要展现你的思考过程"))

    assert_model_unavailable(reply)


def test_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "这个机器人怎么启动？"))

    assert_model_unavailable(reply)


def test_normalize_reply_removes_think_blocks() -> None:
    reply = _normalize_reply("<think>内部分析，不该发给用户</think>\n亚托莉：我懂你的意思了。")

    assert reply == "我懂你的意思了。"


def test_normalize_reply_removes_ollama_thinking_trace() -> None:
    reply = _normalize_reply("Thinking...\n首先分析用户意图。\n...done thinking.\n亚托莉：我只发最终回复。")

    assert reply == "我只发最终回复。"


def test_env_file_overrides_user_environment(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "BOT_QQ=100000001",
                "OPENAI_API_KEY=ollama",
                "OPENAI_BASE_URL=http://127.0.0.1:11434/v1",
                "OPENAI_MODEL=qwen3:4b-instruct",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-r1:8b")

    config = load_config(env_file)

    assert config.openai_base_url == "http://127.0.0.1:11434/v1"
    assert config.openai_model == "qwen3:4b-instruct"


def test_deprecated_official_deepseek_chat_alias_is_migrated(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_BASE_URL=https://api.deepseek.com/v1",
                "OPENAI_MODEL=deepseek-chat",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env_file)

    assert config.openai_model == "deepseek-v4-flash"


def test_startup_question_uses_model_reply_chain(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.7,
        max_tokens=280,
    )
    engine = AtriReplyEngine(config)
    called = False

    async def fake_guarded_api(*args, **kwargs):
        nonlocal called
        called = True
        return "正常启动 QQ，后台监听器会自动拉起机器人服务。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "这个机器人怎么启动？"))

    assert called
    assert "启动 QQ" in reply or "后台监听器" in reply


def test_meme_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "萝卜子"))

    assert_model_unavailable(reply)


def test_boundary_meme_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "涩涩"))

    assert_model_unavailable(reply)


def test_distress_with_disabled_model_returns_diagnostic_not_comfort_template() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "好难受"))

    assert_model_unavailable(reply)
    assert "先做最靠近结果的一步" not in reply


def test_short_distress_does_not_use_local_comfort_when_model_is_disabled() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "好难受"))

    assert_model_unavailable(reply)


def test_short_distress_uses_model_when_ai_is_enabled(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)
    called = False

    async def fake_guarded_api(*args, **kwargs):
        nonlocal called
        called = True
        return "先喝口水，别硬撑。我在这边，你慢慢说发生了什么。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "好难受"))

    assert called
    assert "喝口水" in reply
    assert "发生了什么" in reply
    assert "十分钟" not in reply


def test_why_question_uses_model_without_question_template(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)
    called = False

    async def fake_guarded_api(*args, **kwargs):
        nonlocal called
        called = True
        return "主要原因是连接状态在切换时丢失了，先检查服务日志里的第一条异常。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "为什么会这样？"))

    assert called
    assert "连接状态" in reply
    assert "先做最靠近结果的一步" not in reply


def test_soft_quality_issue_keeps_model_reply_without_retrying(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)
    attempts = 0

    async def fake_guarded_api(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return "这取决于情况，你可以再说清楚一点。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "你觉得我这样做对吗？"))

    assert attempts == 1
    assert reply == "这取决于情况，你可以再说清楚一点。"
    assert "回复失败" not in reply


def test_history_claim_is_reviewed_against_actual_roles(monkeypatch, tmp_path) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.45,
        max_tokens=180,
        memory_path=tmp_path / "memory.json",
    )
    engine = AtriReplyEngine(config)
    engine.memory.observe_user("private:10001", "我准备玩一会儿游戏", now=1)
    engine.memory.observe_bot("private:10001", "我猜你又瘫着不动了", now=2)
    attempts = 0
    reviewed: list[tuple[str, str, list[dict[str, str]]]] = []

    async def fake_guarded_api(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return "因为上次某人选角色就选了半小时。"

    async def fake_history_review(user_text, candidate_reply, recent_messages):
        reviewed.append((user_text, candidate_reply, recent_messages))
        return "是我刚才乱猜了。你只说准备玩会儿游戏，我不该直接给你贴标签。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)
    monkeypatch.setattr(engine, "_review_history_grounding", fake_history_review)

    reply = asyncio.run(engine.reply("private:10001", "怎么每天都猜我瘫着"))

    assert attempts == 1
    assert len(reviewed) == 1
    assert reviewed[0][2][-1] == {
        "role": "assistant",
        "content": "我猜你又瘫着不动了",
    }
    assert "乱猜" in reply
    assert "选角色" not in reply


def test_history_reviewer_enables_deepseek_thinking_and_parses_json(
    monkeypatch,
    tmp_path,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://api.deepseek.com/v1",
        openai_model="deepseek-v4-flash",
        temperature=0.45,
        max_tokens=180,
        memory_path=tmp_path / "memory.json",
    )
    engine = AtriReplyEngine(config)
    captured: dict[str, object] = {}

    async def fake_post(client, headers, payload):
        captured.update(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"reply":"是我刚才乱猜了，不该给你贴标签。"}'
                    }
                }
            ]
        }

    monkeypatch.setattr(engine, "_post_chat_completion", fake_post)

    reply = asyncio.run(
        engine._review_history_grounding(
            "怎么每天都猜我瘫着",
            "因为上次某人就是瘫着。",
            [
                {"role": "user", "content": "我准备玩一会儿游戏"},
                {"role": "assistant", "content": "我猜你又瘫着不动了"},
            ],
        )
    )

    assert captured["thinking"] == {"type": "enabled"}
    assert captured["max_tokens"] == 900
    assert reply == "是我刚才乱猜了，不该给你贴标签。"


def test_group_distress_fallback_is_not_empty_positive_slogan() -> None:
    reply = _group_fallback_reply("我好难受", allow_abstract=False)

    assert reply is not None
    assert "元气满满" not in reply
    assert "该吃吃" not in reply
    assert any(word in reply for word in ("缓", "硬扛", "慢慢说", "压着"))


def test_direct_suggestion_fallback_avoids_generic_ten_minute_template() -> None:
    reply = _persona_repair_fallback("我该怎么办", "告诉我更多")

    assert "十分钟" not in reply
    assert "目标写成一句话" not in reply
    assert any(word in reply for word in ("背景", "限制", "卡住", "具体"))


def test_why_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "为什么会这样？"))

    assert_model_unavailable(reply)
    assert "先做最靠近结果的一步" not in reply


def test_vague_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "为什么会这样？"))

    assert_model_unavailable(reply)


def test_food_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "推荐我吃什么？"))

    assert_model_unavailable(reply)


def test_stance_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "你觉得我这样做对吗？"))

    assert_model_unavailable(reply)


def test_weather_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "@100000001 今日武汉天气"))

    assert_model_unavailable(reply)


def test_weather_question_uses_model_when_ai_is_enabled(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)
    called = False

    async def fake_guarded_api(*args, **kwargs):
        nonlocal called
        called = True
        return "武汉天气需要看最新来源，我先查实时信息再说，不会乱报。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "@100000001 今日武汉天气"))

    assert called
    assert "最新来源" in reply
    assert "手机天气" not in reply


def test_generic_api_reply_triggers_humanized_rewrite_gate() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    bad_reply = "我理解你的感受。如果你愿意的话，可以继续说给我听。"

    assert engine._needs_rewrite("private:10001", "好难受", bad_reply)
    assert _persona_violations("你觉得我这样做对吗？", "这取决于情况，你可以再说清楚一点。")


def test_why_question_never_uses_content_template_when_model_is_disabled() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("private:10001", "这个事情为什么这么难？"))

    assert_model_unavailable(reply)
    assert "先做最靠近结果的一步" not in reply


def test_non_lore_reply_cannot_use_lore_imagery() -> None:
    violations = _persona_violations(
        "我今天工作好累",
        "我会像深海灯塔一样在水下陪着你。",
    )

    assert any("原作意象" in violation or "深海" in violation for violation in violations)


def test_non_lore_reply_cannot_use_light_imagery_either() -> None:
    violations = _persona_violations(
        "你觉得我该不该继续学画画？",
        "我觉得你应该继续学，就当给未来自己留个灯。",
    )

    assert any("原作意象" in violation for violation in violations)


def test_reply_cannot_fabricate_real_world_action() -> None:
    violations = _persona_violations(
        "我今天好累",
        "我给你按按肩膀，再把冰箱里的牛奶拿出来倒好。",
    )

    assert any("现实动作" in violation for violation in violations)


def test_reply_cannot_fabricate_voice_perception() -> None:
    violations = _persona_violations(
        "好难受",
        "欸？怎么了，声音都变了……你先深呼吸，我在这儿。",
    )

    assert any("现实动作" in violation for violation in violations)


def test_lore_context_allows_lore_imagery() -> None:
    violations = _persona_violations(
        "原作里水下打捞那段你怎么看？",
        "说到水下，我会想到被带回日常的感觉。",
    )

    assert not any("原作意象" in violation or "深海" in violation for violation in violations)


def test_group_message_with_disabled_model_does_not_use_group_template() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("group:20001", "这个配置太抽象了", nickname="群友A"))

    assert_model_unavailable(reply)
    assert "高性能亚托莉路过" not in reply


def test_group_abstract_message_uses_model_reply_chain(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.45,
        max_tokens=180,
    )
    engine = AtriReplyEngine(config)
    called = False

    async def fake_guarded_api(*args, **kwargs):
        nonlocal called
        called = True
        return "这配置确实有点抽象，先把具体报错贴出来，我再帮你看。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("group:20001", "这个配置太抽象了", nickname="群友A"))

    assert called
    assert "主人" not in reply
    assert "抽象" in reply
    assert "代码" not in reply


def test_group_qq_number_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine.reply("group:20001", "@2502391316 你是谁"))

    assert "@2502391316" not in reply
    assert "原神是一款" not in reply
    assert "meaning" not in reply
    assert_model_unavailable(reply)


def test_angry_private_correction_uses_model_repair_mode(tmp_path, monkeypatch) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
    )
    engine = AtriReplyEngine(config)
    seen_extra_system = ""

    async def fake_guarded_api(*args, **kwargs):
        nonlocal seen_extra_system
        seen_extra_system = str(kwargs.get("extra_system") or "")
        return "你说得对，刚才确实没接住重点。我重新按你现在这句话认真回答。"

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "你根本不懂人类，正常点好吗"))

    assert seen_extra_system
    assert "刚才确实没接住重点" in reply


def test_recent_private_context_includes_actual_assistant_reply_for_continuity(
    tmp_path,
) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
    )
    engine = AtriReplyEngine(config)
    engine.memory.observe_user("private:10001", "我准备玩一会儿游戏", now=1)
    engine.memory.observe_bot("private:10001", "我猜你又瘫着不动了", now=2)
    engine.memory.observe_user("private:10001", "怎么每天都猜我瘫着", now=3)

    context = engine._recent_private_context(
        "private:10001",
        current_user_text="怎么每天都猜我瘫着",
    )
    messages = engine._recent_conversation_messages(
        "private:10001",
        current_user_text="怎么每天都猜我瘫着",
    )

    assert "用户: 我准备玩一会儿游戏" in context
    assert "亚托莉: 我猜你又瘫着不动了" in context
    assert "怎么每天都猜我瘫着" not in context
    assert messages == [
        {"role": "user", "content": "我准备玩一会儿游戏"},
        {"role": "assistant", "content": "我猜你又瘫着不动了"},
    ]


def test_serious_mode_suppresses_group_abstract_noise() -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    serious_reply = asyncio.run(engine.reply("group:20001", "讲中文"))
    reply = asyncio.run(engine.reply("group:20001", "这个配置太抽象了", nickname="群友A"))

    assert "正常中文" in serious_reply
    assert "meaning" not in reply
    assert "原神是一款" not in reply
    assert "咕咕嘎嘎" not in reply


def test_group_abstract_meme_bank_is_preserved_when_allowed() -> None:
    reply = _group_fallback_reply("这个配置太抽象了", allow_abstract=True)

    assert any(
        word in reply
        for word in ("恢复出厂设置", "meaning", "谜语人", "调戏ai", "原神是一款")
    )
