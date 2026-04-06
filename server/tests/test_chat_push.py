"""Chat Web Push API tests."""
from unittest.mock import AsyncMock, patch
import pytest
from chat.models import ChatPushSubscription
from chat.push_service import WebPushConfig
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
 assert response.json["public_key"] == "test-public-key"
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
