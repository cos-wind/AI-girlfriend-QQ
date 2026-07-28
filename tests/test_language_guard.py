import asyncio
from pathlib import Path

from atri_qq_bot.config import BotConfig
from atri_qq_bot.language_guard import has_illegal_language_or_garbage
from atri_qq_bot.memory import UserMemoryStore
from atri_qq_bot.persona import AtriReplyEngine, _persona_violations


def _config(tmp_path: Path) -> BotConfig:
    return BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="ollama",
        openai_base_url="http://127.0.0.1:11434/v1",
        openai_model="qwen3:4b-instruct",
        temperature=0.60,
        max_tokens=180,
        frequency_penalty=0.35,
        memory_path=tmp_path / "users.json",
    )


def test_language_guard_blocks_foreign_scripts_and_garbage() -> None:
    assert has_illegal_language_or_garbage("賰賷賮賷丞 鬲賯賷賷賲 賴匕丕 丕賱賲賱賮責")
    assert has_illegal_language_or_garbage("鞎堧厱锛屼粖澶╂€庝箞鏍?)
    assert has_illegal_language_or_garbage("喔椸箟喔竾喔栢复喙堗笝鎴戝崱浣忎簡")
    assert has_illegal_language_or_garbage("袩褉懈胁械褌锛屽厛鍒繖鏍?)
    assert has_illegal_language_or_garbage("砖诇讜诐锛屼粖澶╂€庝箞鏍?)
    assert has_illegal_language_or_garbage("纬蔚喂维 蟽慰蠀锛屽厛鍒繖鏍?)
    assert has_illegal_language_or_garbage("[PAD151831] 杩欏彞涔变簡")
    assert has_illegal_language_or_garbage("鈳⑩帰鈮粹壌")
    assert has_illegal_language_or_garbage("garip 莽枚z眉mler 眉retme")
    assert has_illegal_language_or_garbage("BB69A5F64DA53BB1B02031762176BC0B")
    assert not has_illegal_language_or_garbage("鍝硷紝浠婂ぉ鍏堝枬鍙ｆ按鍐嶇户缁€?)
    assert not has_illegal_language_or_garbage("銇°倗銇ｃ仺寰呫仯銇?(锝€銉幌夈兓麓)")
    assert not has_illegal_language_or_garbage("important_interaction")


def test_persona_marks_illegal_language_as_violation() -> None:
    violations = _persona_violations("浠婂ぉ濂界儲", "賰賷賮賷丞 鬲賯賷賷賲 賴匕丕 丕賱賲賱賮锛熸垜鍏堝洖绛?)

    assert violations


def test_memory_skips_illegal_language_before_write(tmp_path: Path) -> None:
    store = UserMemoryStore(tmp_path / "users.json")

    store.observe_user("private:1", "賰賷賮賷丞 鬲賯賷賷賲 賴匕丕 丕賱賲賱賮锛?, now=1000)
    store.observe_bot("private:1", "鞎堧厱锛屼粖澶╂€庝箞鏍?, now=1001)

    assert store.recent_history("private:1") == []


def test_reply_retries_language_drift_with_lower_temperature(tmp_path: Path) -> None:
    class GuardedEngine(AtriReplyEngine):
        def __init__(self, config: BotConfig) -> None:
            super().__init__(config)
            self.temperatures: list[float | None] = []

        async def _reply_with_api(self, *args, **kwargs) -> str:  # type: ignore[no-untyped-def]
            self.temperatures.append(kwargs.get("temperature_override"))
            if len(self.temperatures) == 1:
                return "賰賷賮賷丞 鬲賯賷賷賲 賴匕丕 丕賱賲賱賮責"
            return "鍝硷紝杩欏彞鎴戦噸鏂拌娓呮锛氫粖澶╁厛鍒‖鎾戯紝鍠濆彛姘村啀鎱㈡參鏉ャ€?

    engine = GuardedEngine(_config(tmp_path))

    reply = asyncio.run(engine.reply("private:1", "闅忎究鑱婁袱鍙ヤ粖澶╃殑瀹夋帓"))

    assert "賰賷賮賷丞" not in reply
    assert "浠婂ぉ" in reply
    assert len(engine.temperatures) == 2
    assert engine.temperatures[0] is None
    assert engine.temperatures[1] is not None
    assert engine.temperatures[1] <= 0.45
