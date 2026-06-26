from atri_qq_bot.onebot import _merge_message_batch, extract_plain_text, should_reply
import json


def test_extract_plain_text_from_string() -> None:
    assert extract_plain_text("你好，亚托莉") == "你好，亚托莉"


def test_extract_plain_text_from_segments() -> None:
    message = [
        {"type": "at", "data": {"qq": "3380609082"}},
        {"type": "text", "data": {"text": " 在吗"}},
        {"type": "image", "data": {"file": "x.jpg"}},
    ]

    assert extract_plain_text(message) == "@群友 在吗[表情包/图片:x.jpg]"


def test_extract_plain_text_from_all_at_segment() -> None:
    message = [
        {"type": "at", "data": {"qq": "all"}},
        {"type": "text", "data": {"text": " 集合"}},
    ]

    assert extract_plain_text(message) == "@全体成员 集合"


def test_extract_plain_text_from_mface_segment() -> None:
    message = [
        {"type": "mface", "data": {"summary": "笑哭"}},
        {"type": "face", "data": {"id": "14"}},
    ]

    assert extract_plain_text(message) == "[动画表情:笑哭][QQ表情:14]"


def test_extract_plain_text_from_file_video_and_share_segments() -> None:
    share_payload = {
        "meta": {
            "detail_1": {
                "title": "罗翔：如何面对嫉妒",
                "qqdocurl": "https://b23.tv/example",
            }
        }
    }
    message = [
        {"type": "file", "data": {"name": "课堂笔记.txt", "file_id": "abc"}},
        {"type": "video", "data": {"title": "寝室项目记录"}},
        {"type": "json", "data": {"data": json.dumps(share_payload, ensure_ascii=False)}},
    ]

    text = extract_plain_text(message)

    assert "[文件:课堂笔记.txt]" in text
    assert "[视频:寝室项目记录]" in text
    assert "罗翔：如何面对嫉妒" in text
    assert "https://b23.tv/example" in text


def test_private_message_should_reply() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "private",
        "user_id": 10001,
        "message": "你好",
    }

    assert should_reply(event, 3380609082, "mention")


def test_private_message_should_reply_in_smart_mode() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "private",
        "user_id": 10001,
        "message": "你好",
    }

    assert should_reply(event, 3380609082, "smart")


def test_group_message_requires_mention_in_mention_mode() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "你好",
    }

    assert not should_reply(event, 3380609082, "mention")


def test_group_smart_mode_does_not_reply_to_owner_without_mention() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 3187537485,
        "message": "你好",
    }

    assert not should_reply(event, 3380609082, "smart", (3187537485,))


def test_group_smart_mode_replies_to_obvious_chat_trigger() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "帮我看看这个怎么处理",
    }

    assert should_reply(event, 3380609082, "smart")


def test_group_smart_mode_does_not_reply_to_random_group_chatter() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "今天下午三点开会",
    }

    assert not should_reply(event, 3380609082, "smart")


def test_group_message_replies_when_bot_is_mentioned() -> None:
    event = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [{"type": "at", "data": {"qq": "3380609082"}}],
    }

    assert should_reply(event, 3380609082, "mention")


def test_message_batch_merges_share_card_and_followup_text() -> None:
    first = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "private",
        "user_id": 10001,
        "message": [{"type": "video", "data": {"title": "测试视频"}}],
    }
    second = {
        "post_type": "message",
        "self_id": 3380609082,
        "message_type": "private",
        "user_id": 10001,
        "message": "分析一下",
    }

    _, merged = _merge_message_batch([(object(), first), (object(), second)])
    text = extract_plain_text(merged["message"])

    assert "[视频:测试视频]" in text
    assert "分析一下" in text
