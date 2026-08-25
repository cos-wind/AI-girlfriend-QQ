from __future__ import annotations

from pathlib import Path

from PIL import Image

import atri_qq_bot.insights.image_report as image_report
from atri_qq_bot.insights.image_report import render_group_summary_image
from atri_qq_bot.insights.summary import _statistics


def _detail(opinion: str) -> dict:
    return {
        "group_name": "测试群",
        "period_type": "daily",
        "message_count": 3,
        "topics": [
            {
                "title": "具体话题",
                "participants": ["甲", "乙"],
                "summary": "群友围绕一个具体事件交换了信息并形成了阶段性结论。",
                "atri_view": opinion,
            }
        ],
        "statistics": {
            "message_count": 3,
            "member_count": 2,
            "total_characters": 30,
            "active_hours": 1,
            "hour_distribution": [3] + [0] * 23,
            "active_members": [
                {"user_id": "1", "nickname": "甲", "messages": 2, "characters": 20},
                {"user_id": "2", "nickname": "乙", "messages": 1, "characters": 10},
            ],
        },
    }


def test_group_summary_image_wraps_opinion_and_numbers_topics(tmp_path: Path, monkeypatch) -> None:
    # 测试只验证排版，不访问 QQ 图床。
    monkeypatch.setattr(image_report, "_avatar", lambda user_id, size: None)
    calls: list[str] = []
    original_text_block = image_report._text_block

    def capture_text_block(*args, **kwargs):
        calls.append(str(args[1] if len(args) > 1 else ""))
        return original_text_block(*args, **kwargs)

    monkeypatch.setattr(image_report, "_text_block", capture_text_block)
    short = tmp_path / "short.png"
    long = tmp_path / "long.png"
    render_group_summary_image(_detail("短锐评。"), short)
    render_group_summary_image(
        _detail("这是一段足够长的亚托莉锐评，用于确认文本会在气泡内按可用宽度换行，而不会越过卡片右边界或覆盖后续模块。" * 4),
        long,
    )

    assert any("#01" in value for value in calls)
    with Image.open(short) as short_image, Image.open(long) as long_image:
        assert short_image.width == long_image.width == 1200
        assert long_image.height > short_image.height


def test_statistics_calculates_member_share_percent() -> None:
    messages = [
        {"user_id": "1", "nickname": "甲", "content": "一", "created_at": "2026-08-22T00:00:00+00:00"},
        {"user_id": "1", "nickname": "甲", "content": "二", "created_at": "2026-08-22T00:01:00+00:00"},
        {"user_id": "2", "nickname": "乙", "content": "三", "created_at": "2026-08-22T00:02:00+00:00"},
    ]
    stats = _statistics(messages)

    assert stats["active_members"][0]["share_percent"] == 66.7
    assert stats["active_members"][1]["share_percent"] == 33.3
