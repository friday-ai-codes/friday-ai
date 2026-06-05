"""Chat Web Push API tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat.models import ChatPushSubscription
from chat.push_service import ChatPushService, WebPushConfig


@pytest.mark.django_db
class TestChatWebPushApi:
    def test_public_key_endpoint_returns_vapid_key(self, authenticated_client):
        with patch(
            "chat.push_service.ChatPushService.aget_or_create_vapid_config",
            new=AsyncMock(
                return_value=WebPushConfig(
                    public_key="test-public-key",
                    private_key_pem="pem",
                    subject="mailto:test@example.com",
                )
            ),
        ):
            response = authenticated_client.get("/api/chat/push/public-key/")

        assert response.status_code == 200
        assert response.json()["public_key"] == "test-public-key"

    def test_subscribe_endpoint_creates_subscription(self, authenticated_client, user):
        response = authenticated_client.post(
            "/api/chat/push/subscriptions/",
            {
                "endpoint": "https://push.example.com/sub-1",
                "keys": {
                    "p256dh": "p256dh-key",
                    "auth": "auth-key",
                },
                "user_agent": "pytest",
            },
            format="json",
        )

        assert response.status_code == 200
        subscription = ChatPushSubscription.objects.get(endpoint="https://push.example.com/sub-1")
        assert subscription.user_id == user.id
        assert subscription.is_active is True

    def test_unsubscribe_endpoint_deactivates_subscription(self, authenticated_client, user):
        ChatPushSubscription.objects.create(
            user=user,
            endpoint="https://push.example.com/sub-2",
            p256dh="p256dh-key",
            auth="auth-key",
        )

        response = authenticated_client.post(
            "/api/chat/push/subscriptions/unsubscribe/",
            {"endpoint": "https://push.example.com/sub-2"},
            format="json",
        )

        assert response.status_code == 200
        subscription = ChatPushSubscription.objects.get(endpoint="https://push.example.com/sub-2")
        assert subscription.is_active is False


@pytest.mark.django_db(transaction=True)
class TestChatPushServiceNotify:
    """ChatPushService.anotify_deep_analysis_complete 测试。"""

    async def test_notify_returns_zero_when_no_user(self):
        result = await ChatPushService.anotify_deep_analysis_complete(
            user_id=None,
            conversation_id="cid",
            conversation_title="Test",
            answer_preview="Preview",
        )
        assert result == 0

    async def test_notify_returns_zero_when_no_subscriptions(self, user):
        result = await ChatPushService.anotify_deep_analysis_complete(
            user_id=str(user.id),
            conversation_id="cid",
            conversation_title="Test",
            answer_preview="Preview",
        )
        assert result == 0

    async def test_notify_delivers_to_active_subscriptions(self, user):
        await ChatPushSubscription.objects.acreate(
            user=user,
            endpoint="https://push.example.com/sub-notify",
            p256dh="p256dh-key",
            auth="auth-key",
            is_active=True,
        )

        with (
            patch("chat.push_service.webpush") as mock_webpush,
            patch.object(
                ChatPushService,
                "aget_or_create_vapid_config",
                new=AsyncMock(return_value=WebPushConfig(
                    public_key="pub",
                    private_key_pem="pem",
                    subject="mailto:test@localhost",
                )),
            ),
        ):
            mock_webpush.return_value = MagicMock()
            result = await ChatPushService.anotify_deep_analysis_complete(
                user_id=str(user.id),
                conversation_id="cid",
                conversation_title="Test",
                answer_preview="Preview",
            )

        assert result == 1
        mock_webpush.assert_called_once()

    async def test_notify_graceful_on_db_error(self):
        """数据库异常（如缺表）应降级返回 0，不抛异常。"""
        from django.db.utils import OperationalError

        mock_qs = MagicMock()

        async def _raise_on_aiter(*a, **kw):
            raise OperationalError("no such table: chat_push_subscriptions")

        mock_qs.__aiter__ = _raise_on_aiter
        mock_manager = MagicMock()
        mock_manager.filter.return_value = mock_qs

        with patch.object(ChatPushSubscription, "objects", mock_manager):
            result = await ChatPushService.anotify_deep_analysis_complete(
                user_id="user-1",
                conversation_id="cid",
                conversation_title="Test",
                answer_preview="Preview",
            )
            assert result == 0
