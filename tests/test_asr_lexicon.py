from pathlib import Path

import pytest

from atri_voice_service.asr_lexicon import AsrLexicon, load_lexicon_payload, save_lexicon


@pytest.fixture
def lexicon(tmp_path):
    path = tmp_path / "hotwords.json"
    save_lexicon(path, [{
        "term": "亚托莉", "aliases": ["亚托利"],
        "greeting_aliases": ["要图利"],
    }])
    return AsrLexicon(path)


@pytest.mark.parametrize(("source", "expected"), [
    ("你好，要图利，今天我们去散步。", "你好，亚托莉，今天我们去散步。"),
    ("你好要图利", "你好亚托莉"),
    ("晚上好，要图利！", "晚上好，亚托莉！"),
    ("  嗨，要图利。", "  嗨，亚托莉。"),
    ("你好，亚托利。", "你好，亚托莉。"),
])
def test_corrects_observed_name_error_only_in_greeting(lexicon, source, expected):
    assert lexicon.correct(source) == expected


@pytest.mark.parametrize("text", [
    "这件事不要图利他人。", "你好，要图利他人吗？", "要图利的人是谁？",
    "他说你好，要图利，之后离开了。", "你好，不要脱衣，外面很冷。",
    "脱离危险后再回来。", "今天需要多少涂料？", "今天我们去散步。",
])
def test_greeting_correction_preserves_ordinary_speech(lexicon, text):
    assert lexicon.correct(text) == text


def test_context_rules_survive_load_save_and_live_reload(lexicon):
    payload = load_lexicon_payload(lexicon.path)
    assert payload["entries"][0]["greeting_aliases"] == ["要图利"]
    payload["entries"][0]["greeting_aliases"].append("亚图丽")
    save_lexicon(lexicon.path, payload["entries"])
    assert lexicon.correct("你好，亚图丽。") == "你好，亚托莉。"


def test_legacy_lexicon_payload_stays_compatible(tmp_path: Path):
    path = tmp_path / "legacy.json"
    entries = [{"term": "亚托莉", "aliases": ["亚托利"]}]
    assert save_lexicon(path, entries) == {"version": 1, "entries": entries}
    assert load_lexicon_payload(path) == {"version": 1, "entries": entries}
