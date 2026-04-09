"""CommitConfirmView API 测试 -- GET/POST /api/chat/coding-sessions/{id}/commit-confirm/。
验证 commit message 确认流程的 REST API，包括状态校验、错误处理、graph resume。
"""
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from rest_framework.test import APIClient
from chat.models import CodingSession
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def awaiting_session(project, repository):
 """创建 awaiting_confirmation 状态的 CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试对话")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案\n- 步骤 1",
 affected_files=[{"path": "src/main.py", "change_type": "modify"}],
 branch_name="feat20260409.test-coding",
 status=CodingSession.Status.AWAITING_CONFIRMATION,
 confirmation_step="commit_message",
 suggested_commit_message="feat: add new feature",
 )
@pytest.fixture
def running_session(project, repository):
 """创建 running 状态的 CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试对话 running")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案",
 branch_name="feat20260409.test-running",
 status=CodingSession.Status.RUNNING,
 )
# ---------------------------------------------------------------------------
# GET 测试
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestCommitConfirmGet:
 """GET /api/chat/coding-sessions/{id}/commit-confirm/ 测试。"""
 def test_get_suggested_commit_message(self, authenticated_client, awaiting_session):
 """awaiting_confirmation + commit_message 步骤返回 200 + 建议消息。"""
 url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
 response = authenticated_client.get(url)
 assert response.status_code == 200
 assert response.data["suggested_commit_message"] == "feat: add new feature"
 assert response.data["affected_files"] == [
 {"path": "src/main.py", "change_type": "modify"}
 ]
 def test_get_wrong_status_returns_409(self, authenticated_client, running_session):
 """running 状态返回 409。"""
 url = f"/api/chat/coding-sessions/{running_session.id}/commit-confirm/"
 response = authenticated_client.get(url)
 assert response.status_code == 409
 def test_get_wrong_step_returns_409(self, authenticated_client, awaiting_session):
 """awaiting_confirmation 但 confirmation_step != commit_message 返回 409。"""
 awaiting_session.confirmation_step = "pr_review"
 awaiting_session.save(update_fields=["confirmation_step"])
 url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
 response = authenticated_client.get(url)
 assert response.status_code == 409
 def test_get_not_found_returns_404(self, authenticated_client):
 """不存在的 session_id 返回 404。"""
 fake_id = uuid.uuid4
 url = f"/api/chat/coding-sessions/{fake_id}/commit-confirm/"
 response = authenticated_client.get(url)
 assert response.status_code == 404
# ---------------------------------------------------------------------------
# POST 测试
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestCommitConfirmPost:
 """POST /api/chat/coding-sessions/{id}/commit-confirm/ 测试。"""
 def test_post_confirm_commit_message(self, authenticated_client, awaiting_session):
 """POST 有效 commit_message 返回 200 + 序列化数据。"""
 mock_compiled = MagicMock
 mock_compiled.ainvoke = AsyncMock
 mock_graph_builder = MagicMock
 mock_graph_builder.compile.return_value = mock_compiled
 with (
 patch(
 "orchestration.coding_graph.build_coding_graph",
 return_value=mock_graph_builder,
 ),
 patch(
 "orchestration.checkpointer.get_checkpointer",
 new_callable=AsyncMock,
 ),
 ):
 url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
 response = authenticated_client.post(
 url,
 {"commit_message": "feat: user edited message"},
 format="json",
 )
 assert response.status_code == 200
 assert "id" in response.data
 assert "status" in response.data
 def test_post_empty_message_returns_400(self, authenticated_client, awaiting_session):
 """POST 空 commit_message 返回 400。"""
 url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
 response = authenticated_client.post(
 url,
 {"commit_message": ""},
 format="json",
 )
 assert response.status_code == 400
 def test_post_wrong_status_returns_409(self, authenticated_client, running_session):
 """running 状态 POST 返回 409。"""
 url = f"/api/chat/coding-sessions/{running_session.id}/commit-confirm/"
 response = authenticated_client.post(
 url,
 {"commit_message": "feat: test"},
 format="json",
 )
 assert response.status_code == 409
 def test_post_too_long_message_returns_400(self, authenticated_client, awaiting_session):
 """commit_message 超过 5000 字符返回 400。"""
 long_msg = "x" * 5001
 url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
 response = authenticated_client.post(
 url,
 {"commit_message": long_msg},
 format="json",
 )
 assert response.status_code == 400
# ---------------------------------------------------------------------------
# State Recovery 测试
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestStateRecovery:
 """验证刷新后 commit-confirm 状态可恢复。"""
 def test_refresh_recovers_state(self, authenticated_client, awaiting_session):
 """awaiting_confirmation 状态可通过 GET 恢复 suggested_commit_message。"""
 url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
 response = authenticated_client.get(url)
 assert response.status_code == 200
 assert response.data["suggested_commit_message"] == "feat: add new feature"
 # 再次 GET 依然可恢复
 response2 = authenticated_client.get(url)
 assert response2.status_code == 200
 assert response2.data["suggested_commit_message"] == "feat: add new feature"
