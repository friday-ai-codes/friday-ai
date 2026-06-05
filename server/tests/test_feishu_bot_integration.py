"""Integration tests for Feishu bot webhook entry."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework import status

from feishu.models import FeishuBotMessage


@pytest.fixture(autouse=True)
def _feishu_dev_settings():
    with override_settings(FEISHU_SIGNATURE_REQUIRED=False, FEISHU_ENCRYPT_KEY=""):
        yield


@pytest.mark.django_db
class TestFeishuBotWebhookIntegration:
    def _payload(self, *, event_id: str, message_id: str, content: str, mentions=None, message_type: str = "text", sender_type: str = "user", parent_id: str = "") -> dict:
        payload: dict = {
            "header": {"event_type": "im.message.receive_v1", "event_id": event_id},
            "event": {
                "message": {
                    "chat_id": "chat_webhook",
                    "chat_type": "group",
                    "message_id": message_id,
                    "message_type": message_type,
                    "content": content,
                },
                "sender": {
                    "sender_id": {"open_id": "ou_user"},
                    "sender_type": sender_type,
                },
            },
        }
        if mentions is not None:
            payload["event"]["message"]["mentions"] = mentions
        if parent_id:
            payload["event"]["message"]["parent_id"] = parent_id
        return payload

    def test_valid_group_mention_returns_200_and_handoffs(self, api_client) -> None:
        payload = self._payload(
            event_id="evt-hook-1",
            message_id="msg-hook-1",
            content='{"text":"@Friday 请看下部署失败","mentions":[{"name":"Friday"}]}',
            mentions=[{"name": "Friday"}],
        )

        with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
            response = api_client.post("/api/feishu/im/message/", payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"
        assert response.data["result"] == "bot_message_accepted"
        assert FeishuBotMessage.objects.filter(message_id="msg-hook-1").exists()
        mock_schedule.assert_called_once_with("msg-hook-1")

    def test_non_mentioned_group_message_is_ignored_but_fast_acked(self, api_client) -> None:
        payload = self._payload(
            event_id="evt-hook-2",
            message_id="msg-hook-2",
            content='{"text":"普通群聊消息"}',
            mentions=[],
        )

        with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
            response = api_client.post("/api/feishu/im/message/", payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ignored"
        assert response.data["reason"] == "mention_required"
        mock_schedule.assert_not_called()

    def test_bot_sender_is_silently_ignored(self, api_client) -> None:
        payload = self._payload(
            event_id="evt-hook-3",
            message_id="msg-hook-3",
            content='{"text":"@Friday 我是机器人"}',
            mentions=[{"name": "Friday"}],
            sender_type="bot",
        )

        with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
            response = api_client.post("/api/feishu/im/message/", payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ignored"
        assert response.data["reason"] == "sender_is_bot"
        mock_schedule.assert_not_called()

    def test_duplicate_event_only_processes_once(self, api_client) -> None:
        payload = self._payload(
            event_id="evt-hook-dup",
            message_id="msg-hook-dup",
            content='{"text":"@Friday 重复消息","mentions":[{"name":"Friday"}]}',
            mentions=[{"name": "Friday"}],
        )

        with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
            response1 = api_client.post("/api/feishu/im/message/", payload, format="json")
            response2 = api_client.post("/api/feishu/im/message/", payload, format="json")

        assert response1.status_code == status.HTTP_200_OK
        assert response1.data["status"] == "ok"
        assert response2.status_code == status.HTTP_200_OK
        assert response2.data["status"] == "duplicate"
        mock_schedule.assert_called_once_with("msg-hook-dup")

    def test_post_message_with_quote_is_normalized_and_handed_off(self, api_client) -> None:
        payload = self._payload(
            event_id="evt-hook-4",
            message_id="msg-hook-4",
            content={
                "zh_cn": {
                    "content": [
                        [{"tag": "at", "user_id": "bot"}, {"tag": "text", "text": " 帮我看 websocket "}],
                    ]
                }
            },
            mentions=[{"name": "Friday"}],
            message_type="post",
            parent_id="quoted-msg-1",
        )

        with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
            response = api_client.post("/api/feishu/im/message/", payload, format="json")

        stored = FeishuBotMessage.objects.get(message_id="msg-hook-4")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"
        assert stored.quote_message_id == "quoted-msg-1"
        assert stored.normalized_text == "帮我看 websocket"
        mock_schedule.assert_called_once_with("msg-hook-4")

    def test_attachment_only_message_still_fast_handoffs_for_background_clarification(self, api_client) -> None:
        payload = self._payload(
            event_id="evt-hook-5",
            message_id="msg-hook-5",
            content='{"file_name":"trace.log","file_key":"file_1"}',
            mentions=[{"name": "Friday"}],
            message_type="file",
        )

        with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
            response = api_client.post("/api/feishu/im/message/", payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"
        assert response.data["result"] == "bot_message_accepted"
        mock_schedule.assert_called_once_with("msg-hook-5")
