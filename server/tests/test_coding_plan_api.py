"""CodingPlan REST 端点测试。

GET /api/chat/coding-plans/?conversation_id=<uuid>  -- 列表
GET /api/chat/coding-plans/<uuid>/                   -- 详情
"""

from __future__ import annotations

import uuid

import pytest

from chat.models import CodingPlan, CodingSession, Conversation


@pytest.fixture
def conversation(db, project, user):
    return Conversation.objects.create(
        project=project, title="REST 测试对话", created_by=user
    )


@pytest.fixture
def second_conversation(db, project):
    return Conversation.objects.create(project=project, title="另一对话")


@pytest.fixture
def two_plans(db, conversation):
    """同一 conversation 下两个 CodingPlan。"""
    plan1 = CodingPlan.objects.create(
        conversation=conversation,
        tech_plan="## 方案 1",
        affected_files=[{"file_path": "a.py", "change_type": "modify"}],
        title="方案 1",
    )
    plan2 = CodingPlan.objects.create(
        conversation=conversation,
        tech_plan="## 方案 2",
        affected_files=[{"file_path": "b.py", "change_type": "add"}],
        title="方案 2",
    )
    return plan1, plan2


@pytest.mark.django_db(transaction=True)
class TestCodingPlanListAPI:
    def test_list_coding_plans_by_conversation(
        self, authenticated_client, conversation, two_plans
    ):
        """GET 返回 200 + 2 个 plan，按 created_at 倒序。"""
        url = f"/api/chat/coding-plans/?conversation_id={conversation.id}"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert isinstance(response.data, list)
        assert len(response.data) == 2
        # 倒序：plan2 在前
        plan1, plan2 = two_plans
        assert response.data[0]["id"] == str(plan2.id)
        assert response.data[1]["id"] == str(plan1.id)

    def test_list_coding_plans_requires_conversation_id(self, authenticated_client):
        """GET 不带 conversation_id 返回 400。"""
        url = "/api/chat/coding-plans/"
        response = authenticated_client.get(url)
        assert response.status_code == 400
        assert "conversation_id" in response.data["detail"]

    def test_list_coding_plans_for_unknown_conversation(self, authenticated_client):
        """conversation 不存在 → 200 + 空数组（避免越权信号）。"""
        url = f"/api/chat/coding-plans/?conversation_id={uuid.uuid4()}"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data == []

    def test_list_isolates_by_conversation(
        self, authenticated_client, conversation, second_conversation, two_plans
    ):
        """其它 conversation 看不到本 conversation 的 plan。"""
        url = f"/api/chat/coding-plans/?conversation_id={second_conversation.id}"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data == []


@pytest.mark.django_db(transaction=True)
class TestCodingPlanDetailAPI:
    def test_detail_coding_plan(self, authenticated_client, two_plans):
        """GET detail 返回 200 + 字段完整 + affected_files 用 file_path。"""
        plan1, _ = two_plans
        url = f"/api/chat/coding-plans/{plan1.id}/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        data = response.data
        assert data["id"] == str(plan1.id)
        assert data["tech_plan"] == "## 方案 1"
        assert data["title"] == "方案 1"
        assert data["affected_files"][0]["file_path"] == "a.py"
        assert "feishu_doc_token" in data
        assert "feishu_doc_url" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_detail_coding_plan_404(self, authenticated_client):
        """未知 plan_id 返回 404。"""
        url = f"/api/chat/coding-plans/{uuid.uuid4()}/"
        response = authenticated_client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestCodingSessionSerializerExposesPlanId:
    """CodingSessionSerializer 暴露 coding_plan_id 字段。"""

    def test_serializer_shows_plan_id_when_linked(
        self, authenticated_client, conversation, repository, two_plans
    ):
        plan1, _ = two_plans
        session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            coding_plan=plan1,
            tech_plan="## 关联 plan 的 session",
            affected_files=[{"file_path": "x.py", "change_type": "modify"}],
        )
        url = f"/api/chat/coding-sessions/{session.id}/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["coding_plan_id"] == str(plan1.id)

    def test_serializer_returns_null_plan_id_when_not_linked(
        self, authenticated_client, conversation, repository
    ):
        session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 无 plan 关联",
            affected_files=[],
        )
        url = f"/api/chat/coding-sessions/{session.id}/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["coding_plan_id"] is None
