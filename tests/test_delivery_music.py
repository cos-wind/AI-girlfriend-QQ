from __future__ import annotations

from pathlib import Path

import pytest

from atri_qq_bot.music.library import song_catalog, save_song
from atri_qq_bot.music.session import SingingConversationController
from atri_qq_bot.runtime.paths import DATA_DIR, MUSIC_ROOT


def _build_natural_language_catalog(root: Path) -> Path:
    complete = root / "music"
    complete.mkdir()
    for title in ("秘光寻旅", "逐渐变快", "铁花飞"):
        (complete / f"{title}.wav").write_bytes(b"complete-song")
    # 旧版工具误把动作名写成过音频文件，不能把这种内部词当作歌名。
    (complete / "execute.wav").write_bytes(b"not-a-song")
    return complete


def test_song_catalog_is_the_only_qq_source(tmp_path: Path) -> None:
    complete = tmp_path / "music"
    nested = complete / "nested"
    complete.mkdir()
    nested.mkdir()
    full_song = complete / "Mystic Light Quest (秘光寻旅).wav"
    full_song.write_bytes(b"full-song")
    (complete / "execute.wav").write_bytes(b"artifact")
    (nested / "01.wav").write_bytes(b"fragment")

    songs = song_catalog(complete)

    assert [song.title for song in songs] == ["Mystic Light Quest (秘光寻旅)"]
    assert songs[0].path == full_song.resolve()
    assert MUSIC_ROOT == DATA_DIR / "music"


def test_singing_always_lists_catalog_before_confirmed_selection(
    tmp_path: Path,
) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    controller = SingingConversationController(root=complete)

    first = controller.resolve("group:1:user:2", "@ATRI 随便唱首歌")
    assert first.handled and first.reason == "catalog" and first.song is None
    assert "铁花飞" in first.reply_text and "execute" not in first.reply_text
    selected = controller.resolve("group:1:user:2", "就铁花飞吧")
    assert selected.song is not None and selected.song.title == "铁花飞"
    assert selected.song.path == (complete / "铁花飞.wav").resolve()
    assert not controller.resolve("group:1:user:2", "然后呢").handled
    assert not controller.resolve("group:1:user:2", "铁花飞").handled


def test_named_request_requires_confirmation(tmp_path: Path) -> None:
    controller = SingingConversationController(root=_build_natural_language_catalog(tmp_path))
    first = controller.resolve("private:1", "给我唱铁花飞")
    assert first.handled and first.song is None and "歌单" in first.reply_text
    confirmed = controller.resolve("private:1", "是的，就这首")
    assert confirmed.song is not None and confirmed.song.title == "铁花飞"
    assert not controller.resolve("private:1", "确认").handled


@pytest.mark.parametrize("text", [
    "今天听到有人唱歌", "合唱团今天放假", "我不会唱歌", "来一段代码",
    "唱好啦！《小星星》来听", "唱歌服务好像没开机，稍后再试试吧",
    "好耶！我去练《モニタリング》啦，唱好要几分钟，稍等哦～",
    "哼哒，我才不会经常说有点开心呢", "哼哼～你说还没学会？",
    "唱歌模块已经解耦了", "这首歌怎么唱", "不要唱歌", "我想听你解释这段代码",
    "你唱歌真好听", "歌单功能有bug", "开头很精彩", "然后呢", "下一段",
])
def test_ordinary_chat_never_enters_singing(tmp_path: Path, text: str) -> None:
    from atri_qq_bot.voice.delivery import detect_explicit_delivery_intent

    controller = SingingConversationController(root=_build_natural_language_catalog(tmp_path))
    assert detect_explicit_delivery_intent(text) is None
    assert not controller.resolve("private:1", text).handled
    controller.resolve("private:1", "唱歌")
    assert not controller.resolve("private:1", text).handled
    assert not controller.resolve("private:1", "第二首").handled


@pytest.mark.parametrize("text", ["唱歌", "亚托莉，唱首歌吧", "给我唱两句吧", "想听你唱歌", "来一首歌", "点歌", "你会唱什么歌？"])
def test_explicit_requests_show_catalog(tmp_path: Path, text: str) -> None:
    controller = SingingConversationController(root=_build_natural_language_catalog(tmp_path))
    decision = controller.resolve("private:1", text)
    assert decision.handled and decision.reason == "catalog" and decision.song is None


def test_normal_chat_does_not_scan_music_library(tmp_path: Path, monkeypatch) -> None:
    controller = SingingConversationController(root=_build_natural_language_catalog(tmp_path))
    controller.resolve("private:2", "唱歌")

    def unexpected_scan(*args):
        raise AssertionError("普通聊天不应扫描歌曲目录")

    monkeypatch.setattr("atri_qq_bot.music.session.song_catalog", unexpected_scan)
    assert not controller.resolve("private:1", "你好").handled
    assert not controller.resolve("private:2", "然后呢").handled


def test_selection_expires_and_does_not_follow_changed_catalog_order(tmp_path: Path) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    now = [0.0]
    controller = SingingConversationController(root=complete, ttl_seconds=60, clock=lambda: now[0])
    controller.resolve("private:1", "唱铁花飞")
    now[0] = 61.0
    assert not controller.resolve("private:1", "确认").handled

    controller.resolve("private:1", "唱歌")
    original = song_catalog(complete)
    (complete / "AAA新歌曲.wav").write_bytes(b"new-song")
    selected = controller.resolve("private:1", "1")
    assert selected.song is not None and selected.song.title == original[0].title

    controller.resolve("private:1", "唱歌")
    songs = song_catalog(complete)
    songs[0].path.unlink()
    missing = controller.resolve("private:1", "1")
    assert missing.handled and missing.reason == "catalog" and missing.song is None


def test_song_names_preserve_non_chinese_languages_and_exact_selection(tmp_path: Path) -> None:
    complete = tmp_path / "music"
    complete.mkdir()
    (complete / "モニタリング.wav").write_bytes(b"full-song")
    controller = SingingConversationController(root=complete)
    assert controller.resolve("private:1", "唱《モニタリング》").song is None
    selected = controller.resolve("private:1", "确认")
    assert selected.song is not None and selected.song.title == "モニタリング"
    controller.resolve("private:1", "唱歌")
    assert controller.resolve("private:1", "唱《モニタリン》").song is None


def test_singing_followups_understand_catalog_answers_and_unknown_songs(
    tmp_path: Path,
) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    controller = SingingConversationController(root=complete)

    catalog = controller.resolve("private:2", "你都会唱什么歌？")
    assert catalog.handled and catalog.reply_text
    assert "秘光寻旅" in catalog.reply_text and "execute" not in catalog.reply_text

    selected = controller.resolve("private:2", "第二首")
    assert selected.handled and selected.song is not None

    unknown = controller.resolve("private:3", "给我唱只因你太美")
    assert unknown.handled and unknown.song is None
    assert "歌单" in unknown.reply_text and "铁花飞" in unknown.reply_text


def test_singing_context_is_isolated_per_group_user(tmp_path: Path) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    controller = SingingConversationController(root=complete)

    controller.resolve("group:1:user:10", "唱铁花飞")
    controller.resolve("group:1:user:20", "唱秘光寻旅")
    assert not controller.resolve("group:2:user:10", "确认").handled
    user_a = controller.resolve("group:1:user:10", "确认")
    user_b = controller.resolve("group:1:user:20", "确认")

    assert user_a.song is not None and user_a.song.title == "铁花飞"
    assert user_b.song is not None and user_b.song.title == "秘光寻旅"
    assert user_a.song.path == (complete / "铁花飞.wav").resolve()


def test_invalid_selection_does_not_choose_another_song(tmp_path: Path) -> None:
    controller = SingingConversationController(root=_build_natural_language_catalog(tmp_path))
    controller.resolve("private:1", "唱歌")
    invalid = controller.resolve("private:1", "第一二首")
    assert invalid.handled and invalid.reason == "catalog" and invalid.song is None


def test_missing_named_selection_refreshes_catalog(tmp_path: Path) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    controller = SingingConversationController(root=complete)
    controller.resolve("private:1", "唱歌")
    (complete / "铁花飞.wav").unlink()
    missing = controller.resolve("private:1", "铁花飞")
    assert missing.handled and missing.reason == "catalog" and missing.song is None
    assert "铁花飞" not in missing.reply_text


def test_song_import_is_atomic_and_preserves_existing_files(tmp_path: Path) -> None:
    first = save_song("铁花飞.wav", b"original", root=tmp_path)
    second = save_song("铁花飞.wav", b"new", root=tmp_path)
    assert first.read_bytes() == b"original"
    assert second.read_bytes() == b"new"
    assert [song.path for song in song_catalog(tmp_path)] == [first, second]
    assert not list(tmp_path.glob("*.uploading"))
    with pytest.raises(ValueError):
        save_song("not-a-song.txt", b"text", root=tmp_path)


def test_confirmation_does_not_rescan_or_read_audio(tmp_path: Path, monkeypatch) -> None:
    controller = SingingConversationController(root=_build_natural_language_catalog(tmp_path))
    controller.resolve("private:1", "唱铁花飞")

    def unexpected_io(*args, **kwargs):
        raise AssertionError("确认歌曲只传文件路径，不扫描目录或读取音频")

    monkeypatch.setattr("atri_qq_bot.music.session.song_catalog", unexpected_io)
    monkeypatch.setattr(Path, "read_bytes", unexpected_io)
    selected = controller.resolve("private:1", "确认")
    assert selected.song is not None and selected.song.title == "铁花飞"
