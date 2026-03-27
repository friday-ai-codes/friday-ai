"""Webhook 端点测试。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import pytest
from rest_framework import status
# ============================================================================
# 飞书 Webhook 测试
# ============================================================================
@pytest.mark.django_db
class TestFeishuWebhook:
 """飞书 Webhook 接口测试。"""
 def test_url_verification_challenge(self, api_client, urls):
 """测试 URL 验证挑战响应。"""
 response = api_client.post(
 urls.feishu_webhook,
 {
 "type": "url_verification",
 "challenge": "test-challenge-token",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["challenge"] == "test-challenge-token"
 def test_webhook_missing_header_payload(self, api_client, urls):
 """测试缺少 header 或 payload 的 webhook。"""
 response = api_client.post(
 urls.feishu_webhook,
 {"some": "data"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
 def test_webhook_missing_project_key(self, api_client, urls):
 """测试缺少 project_key 的 webhook。"""
 response = api_client.post(
 urls.feishu_webhook,
 {
 "header": {"event_type": "WorkitemCreateEvent"},
 "payload": {},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
 assert "reason" in response.data
 def test_webhook_project_not_configured(self, api_client, urls):
 """测试未配置项目的 webhook。"""
 response = api_client.post(
 urls.feishu_webhook,
 {
 "header": {"event_type": "WorkitemCreateEvent"},
 "payload": {"project_key": "unknown-project"},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
 assert "未配置" in response.data["reason"]
# ============================================================================
# 带项目配置的飞书 Webhook 测试
# ============================================================================
@pytest.mark.django_db
class TestFeishuWebhookWithProject:
 """带项目配置的飞书 Webhook 接口测试。"""
 def test_webhook_token_verification_failed(self, api_client, project, urls):
 """测试错误 token 的 webhook。"""
 response = api_client.post(
 urls.feishu_webhook,
 {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": "wrong-token",
 },
 "payload": {"project_key": project.feishu_project_key},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
 def test_webhook_success(self, api_client, project, urls):
 """测试成功的 webhook 处理。"""
 response = api_client.post(
 urls.feishu_webhook,
 {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": project.feishu_webhook_token,
 "uuid": "test-event-uuid-001",
 },
 "payload": {
 "project_key": project.feishu_project_key,
 "id": 12345,
 "name": "Test Work Item",
 },
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "accepted"
 assert response.data["event_type"] == "WorkitemCreateEvent"
 def test_webhook_duplicate_event(self, api_client, project, urls):
 """测试重复事件被忽略。"""
 import uuid
 # Use a unique event_uuid for this test to avoid collision with other tests
 unique_uuid = f"duplicate-test-{uuid.uuid4}"
 webhook_data = {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": project.feishu_webhook_token,
 "uuid": unique_uuid,
 },
 "payload": {
 "project_key": project.feishu_project_key,
 "id": 12345,
 },
 }
 # 第一次请求
 response1 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
 assert response1.status_code == status.HTTP_200_OK
 assert response1.data["status"] == "accepted"
 # 重复请求 — 内存去重应捕获并返回 duplicate，不抛 IntegrityError
 response2 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
 assert response2.status_code == status.HTTP_200_OK
 assert response2.data["status"] == "duplicate"
 @pytest.mark.xfail(reason="_processed_events 已从 feishu.views 移除，幂等机制重构", strict=False)
 def test_webhook_duplicate_after_memory_clear(self, api_client, project, urls):
 """测试服务器重启后（内存集合清空），DB 唯一约束仍能去重。"""
 import uuid
 from feishu.views import _processed_events
 unique_uuid = f"mem-clear-test-{uuid.uuid4}"
 webhook_data = {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": project.feishu_webhook_token,
 "uuid": unique_uuid,
 },
 "payload": {
 "project_key": project.feishu_project_key,
 "id": 12345,
 },
 }
 # 第一次请求 → accepted
 response1 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
 assert response1.status_code == status.HTTP_200_OK
 assert response1.data["status"] == "accepted"
 # 模拟服务器重启：清空内存去重集合
 _processed_events.discard(unique_uuid)
 # 第二次请求 → DB unique 约束应捕获重复，返回 duplicate
 response2 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
 assert response2.status_code == status.HTTP_200_OK
 assert response2.data["status"] == "duplicate"
 def test_webhook_null_event_uuid_not_conflict(self, api_client, project, urls):
 """测试 event_uuid 为 None 时，多次请求不冲突（unique 允许多个 NULL）。"""
 webhook_data = {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": project.feishu_webhook_token,
 # 不设置 uuid → event_uuid 为 None
 },
 "payload": {
 "project_key": project.feishu_project_key,
 "id": 12345,
 },
 }
 # 两次请求都应正常处理
 response1 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
 assert response1.status_code == status.HTTP_200_OK
 assert response1.data["status"] == "accepted"
 response2 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
 assert response2.status_code == status.HTTP_200_OK
 assert response2.data["status"] == "accepted"
