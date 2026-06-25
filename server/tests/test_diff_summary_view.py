"""DiffSummaryView API 测试 -- GET /api/chat/coding-sessions/{id}/diff-summary/。

验证 diff 摘要查询 API 的正确性，包括认证、状态返回、404 处理、truncated 标记。
"""

from __future__ import annotations

import uuid

import pytest

from chat.models import CodingSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_with_diff(project, repository, user):
    """创建包含 diff_summary 的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        space=project, title="Diff 摘要测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案\n- Diff 摘要步骤",
        branch_name="feat20260409.diff-test",
        status=CodingSession.Status.RUNNING,
        diff_summary={
            "files": [
                {
                    "path": "src/main.py",
                    "additions": 10,
                    "deletions": 2,
                    "change_type": "modified",
                },
                {
                    "path": "src/new_file.py",
                    "additions": 50,
                    "deletions": 0,
                    "change_type": "added",
                },
            ],
            "total_additions": 60,
            "total_deletions": 2,
            "truncated": False,
        },
    )


@pytest.fixture()
def session_without_diff(project, repository, user):
    """创建未设置 diff_summary 的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        space=project, title="无 diff 测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案",
        branch_name="feat20260409.no-diff",
        status=CodingSession.Status.RUNNING,
    )


@pytest.fixture()
def session_with_truncated_diff(project, repository, user):
    """创建 truncated=True 的 diff_summary CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        space=project, title="Truncated diff 测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案",
        branch_name="feat20260409.truncated-diff",
        status=CodingSession.Status.RUNNING,
        diff_summary={
            "files": [{"path": f"file{i}.py", "additions": 1, "deletions": 0, "change_type": "modified"} for i in range(50)],
            "total_additions": 500,
            "total_deletions": 100,
            "truncated": True,
        },
    )


# ---------------------------------------------------------------------------
# GET 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDiffSummaryView:
    """GET /api/chat/coding-sessions/{id}/diff-summary/ 测试。"""

    def test_get_diff_summary_success(self, authenticated_client, session_with_diff):
        """有 diff_summary 时返回 200 + JSON 数据（含 files/total_additions/total_deletions/truncated）。"""
        url = f"/api/chat/coding-sessions/{session_with_diff.id}/diff-summary/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert len(response.data["files"]) == 2
        assert response.data["total_additions"] == 60
        assert response.data["total_deletions"] == 2
        assert response.data["truncated"] is False

    def test_get_diff_summary_empty(self, authenticated_client, session_without_diff):
        """未设置 diff_summary 时返回 200 + {}。"""
        url = f"/api/chat/coding-sessions/{session_without_diff.id}/diff-summary/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data == {}

    def test_get_diff_summary_not_found(self, authenticated_client):
        """不存在的 session_id 返回 404。"""
        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/diff-summary/"
        response = authenticated_client.get(url)
        assert response.status_code == 404

    def test_get_diff_summary_truncated(self, authenticated_client, session_with_truncated_diff):
        """truncated=True 时返回数据包含 truncated=True。"""
        url = f"/api/chat/coding-sessions/{session_with_truncated_diff.id}/diff-summary/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["truncated"] is True
        assert response.data["total_additions"] == 500
        assert response.data["total_deletions"] == 100
        assert len(response.data["files"]) == 50
