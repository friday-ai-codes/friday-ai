"""agents App 冒烟测试。"""

import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
class TestAgentSessionModel:
    """AgentSession 模型创建与查询。"""

    def test_create_session(self):
        from agents.models import AgentSession

        session = AgentSession.objects.create(session_id="smoke-session-001")
        assert AgentSession.objects.filter(pk=session.pk).exists()


@pytest.mark.django_db
class TestToolListView:
    """ToolListView 端点冒烟。"""

    def test_tool_list_200(self, authenticated_client):
        url = reverse("tool-list")
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_200_OK
