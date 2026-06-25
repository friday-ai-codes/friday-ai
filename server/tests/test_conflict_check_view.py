"""ConflictCheckView API 测试 -- GET /api/chat/coding-sessions/{id}/conflict-check/。

验证冲突预检结果查询 API 的正确性，包括认证、状态返回、404 处理。
"""

from __future__ import annotations

import uuid

import pytest

from chat.models import CodingSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_with_conflict(project, repository, user):
    """创建包含 conflict_check_result 的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        space=project, title="冲突预检测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案\n- 冲突预检步骤",
        branch_name="feat20260409.conflict-test",
        status=CodingSession.Status.RUNNING,
        conflict_check_result={
            "has_conflicts": True,
            "conflicting_files": ["src/main.py", "src/utils.py"],
            "behind_by": 3,
            "suggestion": "以下 2 个文件同时被修改，可能存在合并冲突，建议在 push 前本地解决",
            "checked_at": "2026-04-09T12:00:00+00:00",
        },
    )


@pytest.fixture()
def session_without_conflict(project, repository, user):
    """创建未设置 conflict_check_result 的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        space=project, title="无冲突测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案",
        branch_name="feat20260409.no-conflict",
        status=CodingSession.Status.RUNNING,
    )


# ---------------------------------------------------------------------------
# GET 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestConflictCheckView:
    """GET /api/chat/coding-sessions/{id}/conflict-check/ 测试。"""

    def test_get_conflict_check_success(self, authenticated_client, session_with_conflict):
        """有 conflict_check_result 时返回 200 + JSON 数据。"""
        url = f"/api/chat/coding-sessions/{session_with_conflict.id}/conflict-check/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["has_conflicts"] is True
        assert response.data["behind_by"] == 3
        assert "checked_at" in response.data

    def test_get_conflict_check_empty(self, authenticated_client, session_without_conflict):
        """未设置 conflict_check_result 时返回 200 + {}。"""
        url = f"/api/chat/coding-sessions/{session_without_conflict.id}/conflict-check/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data == {}

    def test_get_conflict_check_not_found(self, authenticated_client):
        """不存在的 session_id 返回 404。"""
        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/conflict-check/"
        response = authenticated_client.get(url)
        assert response.status_code == 404

    def test_get_conflict_check_has_conflicts(self, authenticated_client, session_with_conflict):
        """has_conflicts=True 时返回 conflicting_files 列表。"""
        url = f"/api/chat/coding-sessions/{session_with_conflict.id}/conflict-check/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["has_conflicts"] is True
        assert "src/main.py" in response.data["conflicting_files"]
        assert "src/utils.py" in response.data["conflicting_files"]
        assert len(response.data["conflicting_files"]) == 2
