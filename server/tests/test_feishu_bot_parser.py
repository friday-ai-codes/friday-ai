"""Tests for Feishu bot inbound parser."""

from __future__ import annotations

from feishu.bot.parser import extract_message_attachments, normalize_im_message


def _base_payload() -> dict:
    return {
        "header": {"event_id": "evt-1", "event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "chat_id": "chat_1",
                "chat_type": "group",
                "message_id": "msg_1",
                "message_type": "text",
                "content": '{"text":"@Friday hello world","mentions":[{"name":"Friday"}]}',
            },
            "sender": {
                "sender_id": {"open_id": "ou_user"},
                "sender_type": "user",
            },
        },
    }


def test_normalize_text_message_strips_bot_mention() -> None:
    message = normalize_im_message(_base_payload())

    assert message.chat_id == "chat_1"
    assert message.message_id == "msg_1"
    assert message.mentioned_bot is True
    assert message.normalized_text == "hello world"
    assert message.has_effective_body is True


def test_normalize_post_message_extracts_quote_and_attachment() -> None:
    payload = _base_payload()
    payload["event"]["message"] = {
        "chat_id": "chat_1",
        "chat_type": "group",
        "message_id": "msg_2",
        "message_type": "post",
        "parent_id": "quoted_1",
        "content": {
            "zh_cn": {
                "content": [
                    [
                        {"tag": "at", "user_id": "bot"},
                        {"tag": "text", "text": " 请帮我看这个报错 "},
                    ],
                    [
                        {"tag": "file", "file_key": "file_1", "file_name": "trace.log"},
                    ],
                ]
            }
        },
    }

    message = normalize_im_message(payload)

    assert message.mentioned_bot is True
    assert message.quote_message_id == "quoted_1"
    assert message.normalized_text == "请帮我看这个报错"
    assert message.attachments[0]["name"] == "trace.log"


def test_normalize_image_message_extracts_image_attachment() -> None:
    payload = _base_payload()
    payload["event"]["message"] = {
        "chat_id": "chat_1",
        "chat_type": "group",
        "message_id": "msg_img",
        "message_type": "image",
        "content": '{"image_key":"img_1"}',
    }

    message = normalize_im_message(payload)

    assert message.normalized_text == ""
    assert message.has_effective_body is True
    assert message.attachments == [{"tag": "image", "image_key": "img_1", "name": "image"}]


def test_extract_message_attachments_from_raw_payload() -> None:
    payload = _base_payload()
    payload["event"]["message"] = {
        "chat_id": "chat_1",
        "chat_type": "group",
        "message_id": "msg_post_img",
        "message_type": "post",
        "content": {
            "zh_cn": {
                "content": [
                    [{"tag": "text", "text": "看图"}],
                    [{"tag": "img", "image_key": "img_post_1", "title": "截图"}],
                ]
            }
        },
    }

    attachments = extract_message_attachments(payload)

    assert attachments == [
        {"tag": "img", "file_key": "", "image_key": "img_post_1", "name": "截图"},
    ]


def test_normalize_bot_sender_marks_sender_is_bot() -> None:
    payload = _base_payload()
    payload["event"]["sender"] = {
        "sender_id": {"open_id": "ou_bot"},
        "sender_type": "bot",
    }

    message = normalize_im_message(payload)

    assert message.sender_is_bot is True
