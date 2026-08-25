from __future__ import annotations

import json
from pathlib import Path

from atri_qq_bot.music.library import (
    complete_song_catalog,
    delivery_song_catalog,
    delivery_song_catalog_prompt,
    find_complete_song,
    find_delivery_song,
    select_delivery_segment,
)
from atri_qq_bot.music.session import SingingConversationController
from tools.voice.analyze_song_structure import choose_delivery_boundaries


def test_delivery_catalog_only_reads_published_segments(tmp_path: Path) -> None:
    complete = tmp_path / "完整音乐"
    delivery = tmp_path / "完整音乐片段"
    complete.mkdir()
    (complete / "不应发送.wav").write_bytes(b"complete")
    song_dir = delivery / "她踏上了旅程"
    song_dir.mkdir(parents=True)
    (song_dir / "01.wav").write_bytes(b"prepared")
    (song_dir / "manifest.json").write_text(
        json.dumps(
            {
                "title": "她踏上了旅程",
                "segments": [{"index": 1, "file": "01.wav", "start_seconds": 0, "end_seconds": 30}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    songs = delivery_song_catalog(delivery)

    assert len(songs) == 1
    assert songs[0].segments[0].path == (song_dir / "01.wav").resolve()
    assert find_delivery_song("唱《她踏上了旅程》", delivery) == songs[0]
    assert find_delivery_song("唱《不存在的歌》", delivery) is None


def test_song_folder_name_is_canonical_and_selection_uses_song_and_segment(
    tmp_path: Path,
) -> None:
    delivery = tmp_path / "完整音乐片段"
    first = delivery / "第一首"
    second = delivery / "第二首"
    for folder in (first, second):
        folder.mkdir(parents=True)
        for index in (1, 2):
            (folder / f"{index:02d}.wav").write_bytes(b"prepared")
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "title": "D:/old/path/should-not-be-used",
                    "segments": [
                        {"index": 1, "file": "01.wav", "start_seconds": 0, "end_seconds": 28},
                        {"index": 2, "file": "02.wav", "start_seconds": 28, "end_seconds": 56},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    songs = delivery_song_catalog(delivery)
    assert [song.title for song in songs] == ["第一首", "第二首"]
    assert find_delivery_song("唱一首歌", delivery) is None
    song, segment, reason = select_delivery_segment("唱《第二首》第2段", root=delivery)
    assert (song.title, segment.index, reason) == ("第二首", 2, "ok")
    complete = tmp_path / "完整音乐"
    complete.mkdir()
    (complete / "第一首.wav").write_bytes(b"complete")
    (complete / "第二首.wav").write_bytes(b"complete")
    prompt = delivery_song_catalog_prompt(complete)
    assert "《第一首》" in prompt and "《第二首》" in prompt
    assert "整首" in prompt and "片段编号" not in prompt


def test_selection_is_independent_of_group_at_mention_and_tolerates_natural_alias(
    tmp_path: Path,
) -> None:
    delivery = tmp_path / "完整音乐片段"
    first = delivery / "Mystic Light Quest (秘光寻旅)"
    second = delivery / "铁花飞"
    for folder in (first, second):
        folder.mkdir(parents=True)
        (folder / "01.wav").write_bytes(b"prepared")
        (folder / "02.wav").write_bytes(b"prepared")
        (folder / "manifest.json").write_text(
            json.dumps(
                {"segments": [{"index": 1, "file": "01.wav"}, {"index": 2, "file": "02.wav"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    song, segment, reason = select_delivery_segment("@群友 唱秘光之旅 第2段", root=delivery)
    assert (song.title, segment.index, reason) == ("Mystic Light Quest (秘光寻旅)", 2, "ok")
    song, segment, reason = select_delivery_segment("@群友 唱第二首", root=delivery)
    assert (song.title, segment.index, reason) == ("铁花飞", 1, "ok")
    song, segment, reason = select_delivery_segment(
        "@群友 接着唱",
        fallback_song_title="铁花飞",
        previous_segment_index=1,
        root=delivery,
    )
    assert (song.title, segment.index, reason) == ("铁花飞", 2, "ok")


def test_delivery_boundaries_stay_on_bars_and_near_target_duration() -> None:
    boundaries = choose_delivery_boundaries(
        93.0,
        [float(value) for value in range(0, 94, 4)],
        target_seconds=30.0,
    )

    assert boundaries[0] == 0.0
    assert boundaries[-1] == 93.0
    assert all(boundary % 4 == 0 for boundary in boundaries[1:-1])
    lengths = [end - start for start, end in zip(boundaries, boundaries[1:])]
    assert all(20.0 <= length <= 45.0 for length in lengths)


def _build_natural_language_catalog(root: Path) -> Path:
    complete = root / "完整音乐"
    complete.mkdir()
    for title in ("秘光寻旅", "逐渐变快", "铁花飞"):
        (complete / f"{title}.wav").write_bytes(b"complete-song")
    # 旧版工具误把动作名写成过音频文件，不能把这种内部词当作歌名。
    (complete / "execute.wav").write_bytes(b"not-a-song")
    return complete


def test_complete_song_catalog_is_the_only_qq_source(tmp_path: Path) -> None:
    complete = tmp_path / "完整音乐"
    fragments = tmp_path / "完整音乐片段" / "铁花飞"
    complete.mkdir()
    fragments.mkdir(parents=True)
    full_song = complete / "Mystic Light Quest (秘光寻旅).wav"
    full_song.write_bytes(b"full-song")
    (complete / "execute.wav").write_bytes(b"artifact")
    (fragments / "01.wav").write_bytes(b"fragment")

    songs = complete_song_catalog(complete)

    assert [song.title for song in songs] == ["Mystic Light Quest (秘光寻旅)"]
    assert songs[0].segments[0].path == full_song.resolve()
    assert find_complete_song("@群友 唱秘光之旅", complete) == songs[0]
    assert all("完整音乐片段" not in str(segment.path) for song in songs for segment in song.segments)


def test_natural_singing_conversation_keeps_intent_and_really_changes_song(
    tmp_path: Path,
) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    controller = SingingConversationController(root=complete)

    first = controller.resolve("group:1:user:2", "@ATRI 随便唱首歌")
    assert first.handled and first.segment is not None
    assert first.song is not None and first.song.title != "execute"

    changed = controller.resolve("group:1:user:2", "换一首，别再唱这首了")
    assert changed.handled and changed.segment is not None
    assert changed.song is not None and changed.song.title != first.song.title

    continued = controller.resolve("group:1:user:2", "接着唱")
    assert continued.song is not None and continued.song.title == changed.song.title
    assert continued.segment is not None and continued.segment.path.parent == complete.resolve()

    climax = controller.resolve("group:1:user:2", "直接唱高潮那段")
    assert climax.song is not None and climax.song.title == changed.song.title
    assert climax.segment is not None
    assert climax.segment.path.parent == complete.resolve()

    named_change = controller.resolve("group:1:user:2", "换成铁花飞")
    assert named_change.song is not None and named_change.song.title == "铁花飞"
    assert named_change.segment is not None and named_change.segment.index == 1


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
    assert unknown.handled and unknown.segment is None
    assert "还没学会" in unknown.reply_text


def test_singing_context_is_isolated_per_group_user(tmp_path: Path) -> None:
    complete = _build_natural_language_catalog(tmp_path)
    controller = SingingConversationController(root=complete)

    user_a = controller.resolve("group:1:user:10", "唱铁花飞")
    user_b = controller.resolve("group:1:user:20", "唱秘光寻旅")
    user_a_next = controller.resolve("group:1:user:10", "下一段")

    assert user_a.song is not None and user_a.song.title == "铁花飞"
    assert user_b.song is not None and user_b.song.title == "秘光寻旅"
    assert user_a_next.song is not None and user_a_next.song.title == "铁花飞"
    assert user_a_next.segment is not None
    assert user_a_next.segment.path == (complete / "铁花飞.wav").resolve()
