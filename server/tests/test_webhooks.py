"""Webhook 端点测试。

使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""

import pytest
from rest_framework import status

from feishu.models import TriggerLog

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
        unique_uuid = f"duplicate-test-{uuid.uuid4()}"

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

        # 重复请求 — ProcessedEvent 快路径应捕获并返回 duplicate，不抛 IntegrityError
        response2 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
        assert response2.status_code == status.HTTP_200_OK
        assert response2.data["status"] == "duplicate"

        # 幂等的业务性质：同一 event_uuid 只留下一条处理记录，重复投递不再走处理链路
        assert TriggerLog.objects.filter(event_uuid=unique_uuid).count() == 1

    @pytest.mark.django_db(transaction=True)
    def test_webhook_duplicate_when_processed_event_missing(self, api_client, project, urls):
        """ProcessedEvent 快路径记录缺失时，TriggerLog.event_uuid unique 约束仍能兜底去重。

        幂等由两层保证：ProcessedEvent 表（先查后写的快路径）与 TriggerLog.event_uuid
        的 DB unique 约束。这里删掉第一层记录（模拟过期清理 / 多进程竞态下漏查），
        验证第二层仍然拦得住，重复事件不会被二次处理。

        用 transaction=True 跑真实提交语义：兜底路径靠捕获 IntegrityError 生效，
        若包在 pytest 默认的外层事务里，该异常会污染事务、无法断言后续 DB 状态。
        """
        import uuid

        from feishu.models import ProcessedEvent

        unique_uuid = f"processed-event-missing-{uuid.uuid4()}"

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

        # 第一次请求 → accepted，并写入两层幂等记录
        response1 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
        assert response1.status_code == status.HTTP_200_OK
        assert response1.data["status"] == "accepted"
        assert ProcessedEvent.objects.filter(event_id=unique_uuid).exists()
        assert TriggerLog.objects.filter(event_uuid=unique_uuid).count() == 1

        # 移除第一层快路径记录，只留 DB unique 约束兜底
        ProcessedEvent.objects.filter(event_id=unique_uuid).delete()
        log_count_before = TriggerLog.objects.count()

        # 第二次请求 → TriggerLog unique 约束捕获重复，返回 duplicate 而非 500
        response2 = api_client.post(urls.feishu_webhook, webhook_data, format="json")
        assert response2.status_code == status.HTTP_200_OK
        assert response2.data["status"] == "duplicate"
        assert response2.data["uuid"] == unique_uuid
        # 重复投递没有产生任何新的处理记录
        assert TriggerLog.objects.count() == log_count_before
        assert TriggerLog.objects.filter(event_uuid=unique_uuid).count() == 1

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
