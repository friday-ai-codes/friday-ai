"""PRConfirmView API 测试 -- GET/POST /api/chat/coding-sessions/{id}/pr-confirm/。

验证 PR 确认流程的 REST API，包括状态校验、输入校验、graph resume。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat.models import CodingSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pr_review_session(project, repository, user):
    """创建 awaiting_confirmation + pr_review 状态的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        project=project, title="PR 确认测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案\n- PR 流程步骤",
        affected_files=[{"path": "src/main.py", "change_type": "modify"}],
        branch_name="feat20260409.test-feature",
        status=CodingSession.Status.AWAITING_CONFIRMATION,
        confirmation_step="pr_review",
        suggested_pr_title="feat: test feature",
        suggested_pr_description="## Summary\n- Added test feature",
    )


@pytest.fixture()
def running_session(project, repository, user):
    """创建 running 状态的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        project=project, title="测试对话 running", created_by=user
    )
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
class TestPRConfirmGet:
    """GET /api/chat/coding-sessions/{id}/pr-confirm/ 测试。"""

    def test_get_returns_pr_draft(self, authenticated_client, pr_review_session):
        """awaiting_confirmation + pr_review 状态返回 200 + PR 草稿信息。"""
        url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["suggested_pr_title"] == "feat: test feature"
        assert response.data["suggested_pr_description"] == "## Summary\n- Added test feature"
        assert response.data["target_branch"] == "develop"
        assert "github.com" in response.data["branch_url"]
        assert "tree/feat20260409.test-feature" in response.data["branch_url"]

    def test_get_wrong_status_returns_409(self, authenticated_client, running_session):
        """running 状态返回 409。"""
        url = f"/api/chat/coding-sessions/{running_session.id}/pr-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 409

    def test_get_not_found_returns_404(self, authenticated_client):
        """不存在的 session_id 返回 404。"""
        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/pr-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestPRConfirmPost:
    """POST /api/chat/coding-sessions/{id}/pr-confirm/ 测试。"""

    def test_post_skip_returns_200(self, authenticated_client, pr_review_session):
        """POST skip=true 返回 200 + 序列化 CodingSession 数据。"""
        mock_compiled = MagicMock()
        mock_compiled.ainvoke = AsyncMock()

        mock_graph_builder = MagicMock()
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
            url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
            response = authenticated_client.post(
                url,
                {"skip": True},
                format="json",
            )

        assert response.status_code == 200
        assert "id" in response.data
        assert "status" in response.data

    def test_post_create_pr_returns_200(self, authenticated_client, pr_review_session):
        """POST skip=false + 有效字段返回 200，graph.ainvoke 收到正确的 resume 值。"""
        mock_compiled = MagicMock()
        mock_compiled.ainvoke = AsyncMock()

        mock_graph_builder = MagicMock()
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
            url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
            response = authenticated_client.post(
                url,
                {
                    "skip": False,
                    "title": "feat: test",
                    "description": "## Test\n- desc",
                    "target_branch": "main",
                },
                format="json",
            )

        assert response.status_code == 200
        # 验证 graph.ainvoke 被调用且 resume 值包含正确字段
        mock_compiled.ainvoke.assert_called_once()
        call_args = mock_compiled.ainvoke.call_args
        command = call_args[0][0]
        assert command.resume == {
            "skip_pr": False,
            "title": "feat: test",
            "description": "## Test\n- desc",
            "target_branch": "main",
        }

    def test_post_empty_title_returns_400(self, authenticated_client, pr_review_session):
        """POST skip=false 但 title 为空返回 400。"""
        url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {"skip": False, "title": "", "description": "desc", "target_branch": "main"},
            format="json",
        )
        assert response.status_code == 400

    def test_post_empty_description_returns_400(self, authenticated_client, pr_review_session):
        """POST skip=false 但 description 为空返回 400。"""
        url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {"skip": False, "title": "title", "description": "", "target_branch": "main"},
            format="json",
        )
        assert response.status_code == 400

    def test_post_title_too_long_returns_400(self, authenticated_client, pr_review_session):
        """POST title 超过 200 字符返回 400。"""
        url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {
                "skip": False,
                "title": "x" * 201,
                "description": "desc",
                "target_branch": "main",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_post_description_too_long_returns_400(self, authenticated_client, pr_review_session):
        """POST description 超过 10000 字符返回 400。"""
        url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {
                "skip": False,
                "title": "title",
                "description": "x" * 10001,
                "target_branch": "main",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_post_wrong_status_returns_409(self, authenticated_client, running_session):
        """running 状态 POST 返回 409。"""
        url = f"/api/chat/coding-sessions/{running_session.id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {"skip": True},
            format="json",
        )
        assert response.status_code == 409

    def test_post_not_found_returns_404(self, authenticated_client):
        """不存在的 session_id POST 返回 404。"""
        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {"skip": True},
            format="json",
        )
        assert response.status_code == 404

    def test_post_empty_target_branch_returns_400(self, authenticated_client, pr_review_session):
        """POST skip=false 但 target_branch 为空返回 400。"""
        url = f"/api/chat/coding-sessions/{pr_review_session.id}/pr-confirm/"
        response = authenticated_client.post(
            url,
            {"skip": False, "title": "t", "description": "d", "target_branch": ""},
            format="json",
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Serializer 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCodingSessionSerializer:
    """验证 CodingSessionSerializer 包含 PR 相关字段。"""

    def test_serializer_includes_pr_fields(self, pr_review_session):
        """CodingSessionSerializer 输出包含 suggested_pr_title 和 suggested_pr_description 字段。"""
        from chat.serializers import CodingSessionSerializer

        serializer = CodingSessionSerializer(pr_review_session)
        data = serializer.data
        assert "suggested_pr_title" in data
        assert data["suggested_pr_title"] == "feat: test feature"
        assert "suggested_pr_description" in data
        assert data["suggested_pr_description"] == "## Summary\n- Added test feature"
