"""ConversationService 扩展集成测试：对话级模型选择。

测试 implementation 新增的对话级模型选择功能。
使用 AsyncClient 测试对话创建 API。

注意：/messages/ 端点已在 implementation 中删除，替换为 /stream/ SSE 端点。
原有的 TestSendMessageWithRole 和 TestConversationModelSelection 测试类已移除。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def user_and_token(db):
    """创建测试用户并生成 JWT token。"""
    user = await User.objects.acreate_user(
        username="testuser111",
        password="testpass123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def auth_headers(user_and_token):
    """带 Authorization header 的 dict。"""
    _, access_token = user_and_token
    return {"authorization": f"Bearer {access_token}"}


# ============================================================================
# 创建对话 + 模型选择测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateConversationWithModel:
    """创建对话时指定模型的测试。"""

    async def test_create_with_model(self, auth_headers, project):
        """创建对话时指定 model 参数，返回中包含 model 字段。"""
        client = AsyncClient()
        payload = {
            "space_id": str(project.id),
            "title": "测试对话",
            "model": "claude-sonnet-4-20250514",
        }

        resp = await client.post(
            "/api/chat/conversations/",
            data=payload,
            content_type="application/json",
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["model"] == "claude-sonnet-4-20250514"

    async def test_create_without_model(self, auth_headers, project):
        """创建对话不指定 model，默认为空字符串。"""
        client = AsyncClient()
        payload = {
            "space_id": str(project.id),
        }

        resp = await client.post(
            "/api/chat/conversations/",
            data=payload,
            content_type="application/json",
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["model"] == ""
