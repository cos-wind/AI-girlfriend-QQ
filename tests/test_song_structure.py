from __future__ import annotations

from tools.voice.analyze_song_structure import choose_section_count, snap_boundaries


def test_section_count_stays_between_three_and_five() -> None:
    assert choose_section_count(60) == 3
    assert choose_section_count(180) == 4
    assert choose_section_count(300) == 5


def test_boundaries_snap_to_bars_without_tiny_sections() -> None:
    snapped = snap_boundaries(
        [0.0, 31.0, 63.0, 96.0],
        [float(value) for value in range(0, 97, 4)],
        duration=96.0,
        section_count=3,
    )

    assert snapped == [0.0, 32.0, 64.0, 96.0]

