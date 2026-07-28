from atri_qq_bot.onebot import _merge_message_batch, extract_plain_text, should_reply
import json


def test_extract_plain_text_from_string() -> None:
    assert extract_plain_text("浣犲ソ锛屼簹鎵樿帀") == "浣犲ソ锛屼簹鎵樿帀"


def test_extract_plain_text_from_segments() -> None:
    message = [
        {"type": "at", "data": {"qq": "111111111"}},
        {"type": "text", "data": {"text": " 鍦ㄥ悧"}},
        {"type": "image", "data": {"file": "x.jpg"}},
    ]

    assert extract_plain_text(message) == "@缇ゅ弸 鍦ㄥ悧[琛ㄦ儏鍖?鍥剧墖:x.jpg]"


def test_extract_plain_text_from_all_at_segment() -> None:
    message = [
        {"type": "at", "data": {"qq": "all"}},
        {"type": "text", "data": {"text": " 闆嗗悎"}},
    ]

    assert extract_plain_text(message) == "@鍏ㄤ綋鎴愬憳 闆嗗悎"


def test_extract_plain_text_from_mface_segment() -> None:
    message = [
        {"type": "mface", "data": {"summary": "绗戝摥"}},
        {"type": "face", "data": {"id": "14"}},
    ]

    assert extract_plain_text(message) == "[鍔ㄧ敾琛ㄦ儏:绗戝摥][QQ琛ㄦ儏:14]"


def test_extract_plain_text_from_file_video_and_share_segments() -> None:
    share_payload = {
        "meta": {
            "detail_1": {
                "title": "缃楃繑锛氬浣曢潰瀵瑰珘濡?,
                "qqdocurl": "https://b23.tv/example",
            }
        }
    }
    message = [
        {"type": "file", "data": {"name": "璇惧爞绗旇.txt", "file_id": "abc"}},
        {"type": "video", "data": {"title": "瀵濆椤圭洰璁板綍"}},
        {"type": "json", "data": {"data": json.dumps(share_payload, ensure_ascii=False)}},
    ]

    text = extract_plain_text(message)

    assert "[鏂囦欢:璇惧爞绗旇.txt]" in text
    assert "[瑙嗛:瀵濆椤圭洰璁板綍]" in text
    assert "缃楃繑锛氬浣曢潰瀵瑰珘濡? in text
    assert "https://b23.tv/example" in text


def test_private_message_should_reply() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "private",
        "user_id": 10001,
        "message": "浣犲ソ",
    }

    assert should_reply(event, 111111111, "mention")


def test_private_message_should_reply_in_smart_mode() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "private",
        "user_id": 10001,
        "message": "浣犲ソ",
    }

    assert should_reply(event, 111111111, "smart")


def test_group_message_requires_mention_in_mention_mode() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "浣犲ソ",
    }

    assert not should_reply(event, 111111111, "mention")


def test_group_smart_mode_does_not_reply_to_owner_without_mention() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 3187537485,
        "message": "浣犲ソ",
    }

    assert not should_reply(event, 111111111, "smart", (3187537485,))


def test_group_smart_mode_replies_to_obvious_chat_trigger() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "甯垜鐪嬬湅杩欎釜鎬庝箞澶勭悊",
    }

    assert should_reply(event, 111111111, "smart")


def test_group_smart_mode_does_not_reply_to_random_group_chatter() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": "浠婂ぉ涓嬪崍涓夌偣寮€浼?,
    }

    assert not should_reply(event, 111111111, "smart")


def test_group_message_replies_when_bot_is_mentioned() -> None:
    event = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "group",
        "group_id": 20001,
        "user_id": 10001,
        "message": [{"type": "at", "data": {"qq": "111111111"}}],
    }

    assert should_reply(event, 111111111, "mention")


def test_message_batch_merges_share_card_and_followup_text() -> None:
    first = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "private",
        "user_id": 10001,
        "message": [{"type": "video", "data": {"title": "娴嬭瘯瑙嗛"}}],
    }
    second = {
        "post_type": "message",
        "self_id": 111111111,
        "message_type": "private",
        "user_id": 10001,
        "message": "鍒嗘瀽涓€涓?,
    }

    _, merged = _merge_message_batch([(object(), first), (object(), second)])
    text = extract_plain_text(merged["message"])

    assert "[瑙嗛:娴嬭瘯瑙嗛]" in text
    assert "鍒嗘瀽涓€涓? in text
