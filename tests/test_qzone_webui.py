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

    # get_emotion_list 更快，但会话刷新后可能返回空页面（即使同一好友在 QQ
    # 空间里可读），因此改为带显式 feed_owner 的 get_feeds_html_act_all 直读
    # 该好友自己的空间主页。
    assert calls[0][0] == "get_feeds_html_act_all"
    assert str(calls[0][1]["feed_owner"]) == "10001"
    assert calls[0][1]["include_image_data"] is False
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


def test_qzone_admin_accepts_manual_qq_and_rejects_invalid_ids() -> None:
    admin = QZoneAdmin(
        memory_payload(),
        QZoneBridgeClient(
            enabled_settings(), requester=lambda *_: {"data": {"items": []}}
        ),
    )

    # 记忆面板里没有的合法 QQ 号会被当作"手动添加"条目接受，
    # 这样界面才能手工读取任意好友的空间。Bridge 访问仍受回环地址限制保护
    # （见 test_qzone_bridge_rejects_non_loopback_urls）。
    result = admin.feeds("99999")
    assert result["ok"] is True
    assert result["user"]["user_id"] == "99999"
    assert result["user"]["affection_label"] == "手动添加"

    with pytest.raises(ValueError, match="QQ 号无效"):
        admin.feeds("not-a-qq")


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

    # QQ 空间控件在 WebUI 重构中从独立的 qzone 标签页搬进了「用户中心」，
    # 原来手选好友的 id="qzoneUser" 也由用户中心列表取代。
    assert "showTab(event,'users')" in html
    assert 'id="qzoneModelProfile"' in html
    assert 'id="directoryQzoneModelProfile"' in html
    assert 'id="qzoneGlobalModelProfile"' in html
    assert "saveGlobalQZoneModelProfile" in html
    assert "post_model_profile_id:" in html
    assert "loadQZoneModelProfiles" in html
    assert "loadProfiles(); loadQZoneModelProfiles();" in html
    assert "/api/qzone/feeds" in html
    assert "/api/qzone/like" in html
    assert "/api/qzone/comment" in html
    assert "发表生成评论" in html


def test_user_directory_qzone_publisher_has_model_selector() -> None:
    html = render_index()

    assert 'id="directoryQzoneModelProfile"' in html
    assert "post_model_profile_id:" in html


def test_qzone_global_model_selector_has_configured_chat_profiles_on_first_render(monkeypatch) -> None:
    from atri_webui.page import index

    monkeypatch.setattr(index, "load_model_profiles", lambda: [
        {"id": 'chat-"sample', "name": "示例聊天 <A>", "model": "sample-chat", "model_type": "chat"},
        {"id": "second-chat", "model": "other-chat"},
        {"id": "embedding-only", "model": "sample-embed", "model_type": "embedding"},
    ])
    html = render_index()

    assert 'value="chat-&quot;sample"' in html
    assert "示例聊天 &lt;A&gt;" in html
    assert 'value="second-chat"' in html
    assert 'value="embedding-only"' not in html
