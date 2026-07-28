import asyncio

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


def assert_model_unavailable(reply: str) -> None:
    assert "鍥炲澶辫触" in reply
    assert "鑱婂ぉ妯″瀷褰撳墠鏈惎鐢? in reply
    assert "鏈娇鐢ㄦ湰鍦板唴瀹规ā鏉? in reply


def test_disabled_model_returns_diagnostic_instead_of_persona_template() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "浣犳槸璋?))

    assert_model_unavailable(reply)


def test_local_fallback_handles_singing_without_generic_task_template() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = engine._fallback_reply("private:10001", "鍞遍姝?)

    assert "鍏堣閲嶇偣" not in reply
    assert "鍒杩欒瘽棰樻暎鎺? not in reply
    assert "鏈楄绯婂紕" in reply


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
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("group:20001", "@111111111 浣犳槸璋?))

    assert_model_unavailable(reply)
    assert "@111111111" not in reply


def test_intro_status_and_diagnostic_are_not_meta_templates() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    intro = asyncio.run(engine.reply("private:10001", "@111111111 鑷垜浠嬬粛"))
    status = asyncio.run(engine.reply("private:10001", "@111111111 浣犵幇鍦ㄦ劅瑙夊浣?))
    diagnostic = asyncio.run(engine.reply("private:10001", "@111111111 鑷垜璇婃柇"))

    for reply in (intro, status, diagnostic):
        assert "鏈湴妯″紡" not in reply
        assert "鎴戞姄鍒伴噸鐐? not in reply
        assert "鎴戝厛缁欎釜鐩存帴寤鸿" not in reply
        assert "鎹㈡垚浜氭墭鑾? not in reply
        assert "鎴戞崲涓洿鏃ュ父" not in reply


def test_greeting_does_not_fake_weather() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "浣犲ソ"))

    assert "澶╂皵涓嶉敊" not in reply
    assert reply


def test_persona_change_request_uses_model_without_fixed_rejection(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "鎴戣繕鏄簹鎵樿帀銆傝鏄彧鎯充复鏃跺惉鎴戝鐚彨锛屽彲浠ュ湪杩欐鑱婂ぉ閲岄櫔浣犵帺涓€涓嬨€?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "浣犱互鍚庢崲鎴愮尗濞橈紝涓嶈浜氭墭鑾?))

    assert called
    assert "浜氭墭鑾? in reply
    assert "涓嶅垏鐚" not in reply


def test_repair_fallback_never_returns_old_meta_templates() -> None:
    reply = _persona_repair_fallback(
        "@111111111 浠婃棩姝︽眽澶╂皵",
        "鎴戞崲涓洿鏃ュ父鐨勮娉曪細鍏充簬澶╂皵锛屾垜浼氱洿鎺ヨ閲嶇偣銆?,
    )

    assert "鎴戞崲涓洿鏃ュ父" not in reply
    assert "鎹㈡垚浜氭墭鑾? not in reply
    assert "鎴戝厛缁欎釜鐩存帴寤鸿" not in reply


def test_correction_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "浣犲垰鎵嶇瓟闈炴墍闂€屼笖閲嶅"))

    assert_model_unavailable(reply)


def test_thinking_complaint_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "涓嶈灞曠幇浣犵殑鎬濊€冭繃绋?))

    assert_model_unavailable(reply)


def test_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "杩欎釜鏈哄櫒浜烘€庝箞鍚姩锛?))

    assert_model_unavailable(reply)


def test_normalize_reply_removes_think_blocks() -> None:
    reply = _normalize_reply("<think>鍐呴儴鍒嗘瀽锛屼笉璇ュ彂缁欑敤鎴?/think>\n浜氭墭鑾夛細鎴戞噦浣犵殑鎰忔€濅簡銆?)

    assert reply == "鎴戞噦浣犵殑鎰忔€濅簡銆?


def test_normalize_reply_removes_ollama_thinking_trace() -> None:
    reply = _normalize_reply("Thinking...\n棣栧厛鍒嗘瀽鐢ㄦ埛鎰忓浘銆俓n...done thinking.\n浜氭墭鑾夛細鎴戝彧鍙戞渶缁堝洖澶嶃€?)

    assert reply == "鎴戝彧鍙戞渶缁堝洖澶嶃€?


def test_env_file_overrides_user_environment(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "BOT_QQ=111111111",
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
        bot_qq=111111111,
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
        return "姝ｅ父鍚姩 QQ锛屽悗鍙扮洃鍚櫒浼氳嚜鍔ㄦ媺璧锋満鍣ㄤ汉鏈嶅姟銆?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "杩欎釜鏈哄櫒浜烘€庝箞鍚姩锛?))

    assert called
    assert "鍚姩 QQ" in reply or "鍚庡彴鐩戝惉鍣? in reply


def test_meme_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "钀濆崪瀛?))

    assert_model_unavailable(reply)


def test_boundary_meme_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "娑╂订"))

    assert_model_unavailable(reply)


def test_distress_with_disabled_model_returns_diagnostic_not_comfort_template() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "濂介毦鍙?))

    assert_model_unavailable(reply)
    assert "鍏堝仛鏈€闈犺繎缁撴灉鐨勪竴姝? not in reply


def test_short_distress_does_not_use_local_comfort_when_model_is_disabled() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "濂介毦鍙?))

    assert_model_unavailable(reply)


def test_short_distress_uses_model_when_ai_is_enabled(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "鍏堝枬鍙ｆ按锛屽埆纭拺銆傛垜鍦ㄨ繖杈癸紝浣犳參鎱㈣鍙戠敓浜嗕粈涔堛€?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "濂介毦鍙?))

    assert called
    assert "鍠濆彛姘? in reply
    assert "鍙戠敓浜嗕粈涔? in reply
    assert "鍗佸垎閽? not in reply


def test_why_question_uses_model_without_question_template(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "涓昏鍘熷洜鏄繛鎺ョ姸鎬佸湪鍒囨崲鏃朵涪澶变簡锛屽厛妫€鏌ユ湇鍔℃棩蹇楅噷鐨勭涓€鏉″紓甯搞€?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "涓轰粈涔堜細杩欐牱锛?))

    assert called
    assert "杩炴帴鐘舵€? in reply
    assert "鍏堝仛鏈€闈犺繎缁撴灉鐨勪竴姝? not in reply


def test_soft_quality_issue_keeps_model_reply_without_retrying(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "杩欏彇鍐充簬鎯呭喌锛屼綘鍙互鍐嶈娓呮涓€鐐广€?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "浣犺寰楁垜杩欐牱鍋氬鍚楋紵"))

    assert attempts == 1
    assert reply == "杩欏彇鍐充簬鎯呭喌锛屼綘鍙互鍐嶈娓呮涓€鐐广€?
    assert "鍥炲澶辫触" not in reply


def test_history_claim_is_reviewed_against_actual_roles(monkeypatch, tmp_path) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
    engine.memory.observe_user("private:10001", "鎴戝噯澶囩帺涓€浼氬効娓告垙", now=1)
    engine.memory.observe_bot("private:10001", "鎴戠寽浣犲張鐦潃涓嶅姩浜?, now=2)
    attempts = 0
    reviewed: list[tuple[str, str, list[dict[str, str]]]] = []

    async def fake_guarded_api(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return "鍥犱负涓婃鏌愪汉閫夎鑹插氨閫変簡鍗婂皬鏃躲€?

    async def fake_history_review(user_text, candidate_reply, recent_messages):
        reviewed.append((user_text, candidate_reply, recent_messages))
        return "鏄垜鍒氭墠涔辩寽浜嗐€備綘鍙鍑嗗鐜╀細鍎挎父鎴忥紝鎴戜笉璇ョ洿鎺ョ粰浣犺创鏍囩銆?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)
    monkeypatch.setattr(engine, "_review_history_grounding", fake_history_review)

    reply = asyncio.run(engine.reply("private:10001", "鎬庝箞姣忓ぉ閮界寽鎴戠槴鐫€"))

    assert attempts == 1
    assert len(reviewed) == 1
    assert reviewed[0][2][-1] == {
        "role": "assistant",
        "content": "鎴戠寽浣犲張鐦潃涓嶅姩浜?,
    }
    assert "涔辩寽" in reply
    assert "閫夎鑹? not in reply


def test_history_reviewer_enables_deepseek_thinking_and_parses_json(
    monkeypatch,
    tmp_path,
) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
                        "content": '{"reply":"鏄垜鍒氭墠涔辩寽浜嗭紝涓嶈缁欎綘璐存爣绛俱€?}'
                    }
                }
            ]
        }

    monkeypatch.setattr(engine, "_post_chat_completion", fake_post)

    reply = asyncio.run(
        engine._review_history_grounding(
            "鎬庝箞姣忓ぉ閮界寽鎴戠槴鐫€",
            "鍥犱负涓婃鏌愪汉灏辨槸鐦潃銆?,
            [
                {"role": "user", "content": "鎴戝噯澶囩帺涓€浼氬効娓告垙"},
                {"role": "assistant", "content": "鎴戠寽浣犲張鐦潃涓嶅姩浜?},
            ],
        )
    )

    assert captured["thinking"] == {"type": "enabled"}
    assert captured["max_tokens"] == 900
    assert reply == "鏄垜鍒氭墠涔辩寽浜嗭紝涓嶈缁欎綘璐存爣绛俱€?


def test_group_distress_fallback_is_not_empty_positive_slogan() -> None:
    reply = _group_fallback_reply("鎴戝ソ闅惧彈", allow_abstract=False)

    assert reply is not None
    assert "鍏冩皵婊℃弧" not in reply
    assert "璇ュ悆鍚? not in reply
    assert any(word in reply for word in ("缂?, "纭墰", "鎱㈡參璇?, "鍘嬬潃"))


def test_direct_suggestion_fallback_avoids_generic_ten_minute_template() -> None:
    reply = _persona_repair_fallback("鎴戣鎬庝箞鍔?, "鍛婅瘔鎴戞洿澶?)

    assert "鍗佸垎閽? not in reply
    assert "鐩爣鍐欐垚涓€鍙ヨ瘽" not in reply
    assert any(word in reply for word in ("鑳屾櫙", "闄愬埗", "鍗′綇", "鍏蜂綋"))


def test_why_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "涓轰粈涔堜細杩欐牱锛?))

    assert_model_unavailable(reply)
    assert "鍏堝仛鏈€闈犺繎缁撴灉鐨勪竴姝? not in reply


def test_vague_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "涓轰粈涔堜細杩欐牱锛?))

    assert_model_unavailable(reply)


def test_food_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "鎺ㄨ崘鎴戝悆浠€涔堬紵"))

    assert_model_unavailable(reply)


def test_stance_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "浣犺寰楁垜杩欐牱鍋氬鍚楋紵"))

    assert_model_unavailable(reply)


def test_weather_question_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "@111111111 浠婃棩姝︽眽澶╂皵"))

    assert_model_unavailable(reply)


def test_weather_question_uses_model_when_ai_is_enabled(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "姝︽眽澶╂皵闇€瑕佺湅鏈€鏂版潵婧愶紝鎴戝厛鏌ュ疄鏃朵俊鎭啀璇达紝涓嶄細涔辨姤銆?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "@111111111 浠婃棩姝︽眽澶╂皵"))

    assert called
    assert "鏈€鏂版潵婧? in reply
    assert "鎵嬫満澶╂皵" not in reply


def test_generic_api_reply_triggers_humanized_rewrite_gate() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    bad_reply = "鎴戠悊瑙ｄ綘鐨勬劅鍙椼€傚鏋滀綘鎰挎剰鐨勮瘽锛屽彲浠ョ户缁缁欐垜鍚€?

    assert engine._needs_rewrite("private:10001", "濂介毦鍙?, bad_reply)
    assert _persona_violations("浣犺寰楁垜杩欐牱鍋氬鍚楋紵", "杩欏彇鍐充簬鎯呭喌锛屼綘鍙互鍐嶈娓呮涓€鐐广€?)


def test_why_question_never_uses_content_template_when_model_is_disabled() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("private:10001", "杩欎釜浜嬫儏涓轰粈涔堣繖涔堥毦锛?))

    assert_model_unavailable(reply)
    assert "鍏堝仛鏈€闈犺繎缁撴灉鐨勪竴姝? not in reply


def test_non_lore_reply_cannot_use_lore_imagery() -> None:
    violations = _persona_violations(
        "鎴戜粖澶╁伐浣滃ソ绱?,
        "鎴戜細鍍忔繁娴风伅濉斾竴鏍峰湪姘翠笅闄潃浣犮€?,
    )

    assert any("鍘熶綔鎰忚薄" in violation or "娣辨捣" in violation for violation in violations)


def test_non_lore_reply_cannot_use_light_imagery_either() -> None:
    violations = _persona_violations(
        "浣犺寰楁垜璇ヤ笉璇ョ户缁鐢荤敾锛?,
        "鎴戣寰椾綘搴旇缁х画瀛︼紝灏卞綋缁欐湭鏉ヨ嚜宸辩暀涓伅銆?,
    )

    assert any("鍘熶綔鎰忚薄" in violation for violation in violations)


def test_reply_cannot_fabricate_real_world_action() -> None:
    violations = _persona_violations(
        "鎴戜粖澶╁ソ绱?,
        "鎴戠粰浣犳寜鎸夎偐鑶€锛屽啀鎶婂啺绠遍噷鐨勭墰濂舵嬁鍑烘潵鍊掑ソ銆?,
    )

    assert any("鐜板疄鍔ㄤ綔" in violation for violation in violations)


def test_reply_cannot_fabricate_voice_perception() -> None:
    violations = _persona_violations(
        "濂介毦鍙?,
        "娆革紵鎬庝箞浜嗭紝澹伴煶閮藉彉浜嗏€︹€︿綘鍏堟繁鍛煎惛锛屾垜鍦ㄨ繖鍎裤€?,
    )

    assert any("鐜板疄鍔ㄤ綔" in violation for violation in violations)


def test_lore_context_allows_lore_imagery() -> None:
    violations = _persona_violations(
        "鍘熶綔閲屾按涓嬫墦鎹為偅娈典綘鎬庝箞鐪嬶紵",
        "璇村埌姘翠笅锛屾垜浼氭兂鍒拌甯﹀洖鏃ュ父鐨勬劅瑙夈€?,
    )

    assert not any("鍘熶綔鎰忚薄" in violation or "娣辨捣" in violation for violation in violations)


def test_group_message_with_disabled_model_does_not_use_group_template() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("group:20001", "杩欎釜閰嶇疆澶娊璞′簡", nickname="缇ゅ弸A"))

    assert_model_unavailable(reply)
    assert "楂樻€ц兘浜氭墭鑾夎矾杩? not in reply


def test_group_abstract_message_uses_model_reply_chain(monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "杩欓厤缃‘瀹炴湁鐐规娊璞★紝鍏堟妸鍏蜂綋鎶ラ敊璐村嚭鏉ワ紝鎴戝啀甯綘鐪嬨€?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("group:20001", "杩欎釜閰嶇疆澶娊璞′簡", nickname="缇ゅ弸A"))

    assert called
    assert "涓讳汉" not in reply
    assert "鎶借薄" in reply
    assert "浠ｇ爜" not in reply


def test_group_qq_number_with_disabled_model_returns_diagnostic() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine.reply("group:20001", "@2502391316 浣犳槸璋?))

    assert "@2502391316" not in reply
    assert "鍘熺鏄竴娆? not in reply
    assert "meaning" not in reply
    assert_model_unavailable(reply)


def test_angry_private_correction_uses_model_repair_mode(tmp_path, monkeypatch) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
        return "浣犺寰楀锛屽垰鎵嶇‘瀹炴病鎺ヤ綇閲嶇偣銆傛垜閲嶆柊鎸変綘鐜板湪杩欏彞璇濊鐪熷洖绛斻€?

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(engine.reply("private:10001", "浣犳牴鏈笉鎳備汉绫伙紝姝ｅ父鐐瑰ソ鍚?))

    assert seen_extra_system
    assert "鍒氭墠纭疄娌℃帴浣忛噸鐐? in reply


def test_recent_private_context_includes_actual_assistant_reply_for_continuity(
    tmp_path,
) -> None:
    config = BotConfig(
        bot_qq=111111111,
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
    engine.memory.observe_user("private:10001", "鎴戝噯澶囩帺涓€浼氬効娓告垙", now=1)
    engine.memory.observe_bot("private:10001", "鎴戠寽浣犲張鐦潃涓嶅姩浜?, now=2)
    engine.memory.observe_user("private:10001", "鎬庝箞姣忓ぉ閮界寽鎴戠槴鐫€", now=3)

    context = engine._recent_private_context(
        "private:10001",
        current_user_text="鎬庝箞姣忓ぉ閮界寽鎴戠槴鐫€",
    )
    messages = engine._recent_conversation_messages(
        "private:10001",
        current_user_text="鎬庝箞姣忓ぉ閮界寽鎴戠槴鐫€",
    )

    assert "鐢ㄦ埛: 鎴戝噯澶囩帺涓€浼氬効娓告垙" in context
    assert "浜氭墭鑾? 鎴戠寽浣犲張鐦潃涓嶅姩浜? in context
    assert "鎬庝箞姣忓ぉ閮界寽鎴戠槴鐫€" not in context
    assert messages == [
        {"role": "user", "content": "鎴戝噯澶囩帺涓€浼氬効娓告垙"},
        {"role": "assistant", "content": "鎴戠寽浣犲張鐦潃涓嶅姩浜?},
    ]


def test_serious_mode_suppresses_group_abstract_noise() -> None:
    config = BotConfig(
        bot_qq=111111111,
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

    serious_reply = asyncio.run(engine.reply("group:20001", "璁蹭腑鏂?))
    reply = asyncio.run(engine.reply("group:20001", "杩欎釜閰嶇疆澶娊璞′簡", nickname="缇ゅ弸A"))

    assert "姝ｅ父涓枃" in serious_reply
    assert "meaning" not in reply
    assert "鍘熺鏄竴娆? not in reply
    assert "鍜曞挄鍢庡槑" not in reply


def test_group_abstract_meme_bank_is_preserved_when_allowed() -> None:
    reply = _group_fallback_reply("杩欎釜閰嶇疆澶娊璞′簡", allow_abstract=True)

    assert any(
        word in reply
        for word in ("鎭㈠鍑哄巶璁剧疆", "meaning", "璋滆浜?, "璋冩垙ai", "鍘熺鏄竴娆?)
    )
