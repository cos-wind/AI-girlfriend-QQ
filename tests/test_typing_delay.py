"""拟人打字节奏与配置收敛的回归测试。

覆盖两件事：
1. ``_typing_delay`` / ``_first_reply_delay`` 必须随字数增长、受配置上下界约束；
2. 分段/发送/表情相关配置在 loader 就被夹住，避免 WebUI 里的非法值
   （负数、超范围、小数）把运行配置写坏。
"""

from __future__ import annotations

from types import SimpleNamespace

from atri_qq_bot.config import loader
from atri_qq_bot.onebot import _first_reply_delay, _send_delay, _typing_delay
from atri_qq_bot.onebot.server_parts.helpers import _visible_char_count


def _config(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "message_send_delay_min": 0.5,
        "message_send_delay_max": 1.5,
        "typing_chars_per_second": 5.0,
        "typing_max_delay_seconds": 12.0,
        "reply_first_delay_min": 0.8,
        "reply_first_delay_max": 2.5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_visible_char_count_ignores_whitespace() -> None:
    assert _visible_char_count(" 你好 世界\n") == 4
    assert _visible_char_count(None) == 0


def test_typing_delay_grows_with_message_length() -> None:
    config = _config()
    short = _typing_delay(config, "在的")
    long = _typing_delay(config, "我刚刚把今天的安排重新捋了一遍，晚上八点前应该都有空")
    assert short >= config.message_send_delay_min
    assert long > short
    assert long <= config.typing_max_delay_seconds


def test_typing_delay_respects_ceiling_and_floor() -> None:
    config = _config(typing_max_delay_seconds=3.0)
    assert _typing_delay(config, "字" * 200) <= 3.0
    assert _typing_delay(config, "") >= config.message_send_delay_min


def test_first_reply_delay_stays_inside_configured_bounds() -> None:
    config = _config()
    for text in ("", "嗯", "字" * 50, "字" * 400):
        delay = _first_reply_delay(config, text)
        assert config.reply_first_delay_min <= delay <= config.reply_first_delay_max


def test_send_delay_remains_backward_compatible() -> None:
    config = _config()
    delay = _send_delay(config)
    assert config.message_send_delay_min <= delay <= config.message_send_delay_max


def test_loader_clamps_invalid_message_and_sticker_settings(
    monkeypatch,
) -> None:
    # 不读真实 .env，避免污染测试进程环境。
    monkeypatch.setattr(loader, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MESSAGE_SPLIT_MAX_CHARS", "-5")
    monkeypatch.setenv("MESSAGE_SPLIT_MAX_PARTS", "0")
    monkeypatch.setenv("MESSAGE_SEND_DELAY_MIN", "5")
    monkeypatch.setenv("MESSAGE_SEND_DELAY_MAX", "1")
    monkeypatch.setenv("STICKER_CHANCE", "40")
    monkeypatch.setenv("STICKER_COOLDOWN_SECONDS", "-30")
    monkeypatch.setenv("TYPING_CHARS_PER_SECOND", "0")
    monkeypatch.setenv("REPLY_FIRST_DELAY_MIN", "-3")
    monkeypatch.setenv("REPLY_FIRST_DELAY_MAX", "0")

    config = loader.load_config()

    assert config.message_split_max_chars == 8
    assert config.message_split_max_parts == 1
    assert config.message_send_delay_min == 5.0
    # max 低于 min 时被抬到 min，保证 uniform(min, max) 不会反转。
    assert config.message_send_delay_max == 5.0
    assert config.sticker_chance == 1.0
    assert config.sticker_cooldown_seconds == 0
    assert config.typing_chars_per_second == 0.5
    assert config.reply_first_delay_min == 0.0
    assert config.reply_first_delay_max == 0.0


def test_loader_accepts_reasonable_typing_settings(monkeypatch) -> None:
    monkeypatch.setattr(loader, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("TYPING_CHARS_PER_SECOND", "6.5")
    monkeypatch.setenv("TYPING_MAX_DELAY_SECONDS", "9")
    monkeypatch.setenv("REPLY_FIRST_DELAY_MIN", "1.2")
    monkeypatch.setenv("REPLY_FIRST_DELAY_MAX", "3.4")

    config = loader.load_config()

    assert config.typing_chars_per_second == 6.5
    assert config.typing_max_delay_seconds == 9.0
    assert config.reply_first_delay_min == 1.2
    assert config.reply_first_delay_max == 3.4
