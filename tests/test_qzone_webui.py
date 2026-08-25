from __future__ import annotations

from typing import Any

import pytest

from atri_webui.page import render_index
from atri_webui.qzone_admin import (
    QZoneAdmin,
    QZoneBridgeClient,
    QZoneBridgeError,
    QZoneBridgeSettings,
    normalize_feeds,
    qzone_memory_users,
)


def memory_payload() -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "person:10001",
                "kind": "person",
                "display_name": "小明（QQ 10001 / 统一人物档案）",
                "last_user_at_text": "刚刚",
                "affection_label": "熟悉",
                "target": {"user_id": "10001"},
            },
            {
                "id": "group:20001",
                "kind": "group",
                "display_name": "测试群",
                "target": {"group_id": "20001"},
            },
        ]
    }


def enabled_settings() -> QZoneBridgeSettings:
    return QZoneBridgeSettings(
        enabled=True,
        base_url="http://127.0.0.1:5700",
        access_token="test-token",
        timeout_seconds=8,
    )


def test_qzone_users_only_include_people_from_memory_panel() -> None:
    users = qzone_memory_users(memory_payload())

    assert users == [
        {
            "user_id": "10001",
            "display_name": "小明（QQ 10001 / 统一人物档案）",
            "last_user_at_text": "刚刚",
            "affection_label": "熟悉",
        }
    ]


def test_qzone_admin_reads_and_normalizes_selected_users_feeds() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def request(action: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((action, params))
        return {
            "status": "ok",
            "retcode": 0,
            "data": {
                "items": [
                    {
                        "tid": "feed-1",
                        "uin": 10001,
                        "nickname": "小明",
                        "content": "今天天气很好",
                        "abstime": 1_700_000_000,
                        "isLiked": False,
                        "comments": [{"id": "c1"}],
                    }
                ]
            },
        }

    admin = QZoneAdmin(
        memory_payload(),
        QZoneBridgeClient(enabled_settings(), requester=request),
    )
    result = admin.feeds("10001", 10)

    assert calls[0][0] == "get_emotion_list"
    assert calls[0][1]["user_id"] == 10001
    assert result["feeds"][0]["tid"] == "feed-1"
    assert result["feeds"][0]["content"] == "今天天气很好"
    assert result["feeds"][0]["comment_count"] == 1


def test_qzone_admin_sends_manual_like_and_comment_actions() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def request(action: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((action, params))
        return {"status": "ok", "retcode": 0}

    admin = QZoneAdmin(
        memory_payload(),
        QZoneBridgeClient(enabled_settings(), requester=request),
    )

    admin.like({"user_id": "10001", "tid": "feed-1", "abstime": 123})
    admin.comment({"user_id": "10001", "tid": "feed-1", "content": "真不错～"})

    assert calls == [
        ("send_like", {"user_id": 10001, "tid": "feed-1", "abstime": 123}),
        (
            "send_comment",
            {"target_uin": 10001, "target_tid": "feed-1", "content": "真不错～"},
        ),
    ]


def test_qzone_admin_rejects_users_not_in_memory_panel() -> None:
    admin = QZoneAdmin(
        memory_payload(),
        QZoneBridgeClient(enabled_settings(), requester=lambda *_: {}),
    )

    with pytest.raises(ValueError, match="记忆面板"):
        admin.feeds("99999")


def test_qzone_bridge_rejects_non_loopback_urls() -> None:
    client = QZoneBridgeClient(
        QZoneBridgeSettings(
            enabled=True,
            base_url="https://example.com",
            access_token="",
            timeout_seconds=8,
        ),
        requester=lambda *_: {},
    )

    with pytest.raises(QZoneBridgeError, match="回环地址"):
        client.action("get_emotion_list", {})


def test_qzone_feed_normalizer_does_not_expose_raw_image_data() -> None:
    feeds = normalize_feeds(
        {
            "data": {
                "items": [
                    {
                        "tid": "feed-1",
                        "content": "图片动态",
                        "images": [{"data": "very-long-base64"}],
                    }
                ]
            }
        },
        {"user_id": "10001", "display_name": "小明"},
    )

    assert feeds[0]["image_count"] == 1
    assert "images" not in feeds[0]
    assert "very-long-base64" not in str(feeds)


def test_webui_contains_manual_qzone_controls() -> None:
    html = render_index()

    assert "onclick=\"showTab(event,'qzone')\"" in html
    assert 'id="qzoneUser"' in html
    assert "/api/qzone/feeds" in html
    assert "/api/qzone/like" in html
    assert "/api/qzone/comment" in html
    assert "确认并发布评论" in html
