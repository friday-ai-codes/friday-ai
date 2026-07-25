"""implementation Task 2: Summary API 端点测试。

测试 POST generate-summary（200/409/401）和 GET summary-status 端点。
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from repositories.models import AISummaryStatus, Repository


@pytest.mark.django_db
class TestGenerateSummaryEndpoint:
    """Test 1-3: POST /api/repositories/{id}/generate-summary/ 端点行为。"""

    @pytest.fixture
    def mock_dispatch(self, monkeypatch):
        """Mock dispatch_repo_summary 避免真实 dispatch。"""
        async def fake_dispatch(repository):
            repository.ai_summary_status = AISummaryStatus.PENDING
            await repository.asave(update_fields=["ai_summary_status"])
            return "reposummary-fake12345678"

        monkeypatch.setattr(
            "repositories.summary_service.dispatch_repo_summary",
            fake_dispatch,
        )

    def test_generate_summary_returns_200(
        self,
        authenticated_admin_client: APIClient,
        repository: Repository,
        mock_dispatch,
    ) -> None:
        """POST generate-summary 对空间管理员/超管返回 200 + dispatch_task_id。"""
        url = f"/api/repositories/{repository.id}/generate-summary/"
        response = authenticated_admin_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "dispatch_task_id" in data
        assert data["status"] == "pending"

    def test_generate_summary_returns_409_when_running(
        self,
        authenticated_admin_client: APIClient,
        repository: Repository,
    ) -> None:
        """POST generate-summary 当 ai_summary_status==running 时返回 409。"""
        repository.ai_summary_status = AISummaryStatus.RUNNING
        repository.save(update_fields=["ai_summary_status"])

        url = f"/api/repositories/{repository.id}/generate-summary/"
        response = authenticated_admin_client.post(url)
        assert response.status_code == status.HTTP_409_CONFLICT
        data = response.json()
        assert "摘要正在生成中" in data["detail"]

    def test_generate_summary_returns_409_when_pending(
        self,
        authenticated_admin_client: APIClient,
        repository: Repository,
    ) -> None:
        """POST generate-summary 当 ai_summary_status==pending 时也返回 409。"""
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])

        url = f"/api/repositories/{repository.id}/generate-summary/"
        response = authenticated_admin_client.post(url)
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_generate_summary_returns_401_for_unauthenticated(
        self,
        api_client: APIClient,
        repository: Repository,
    ) -> None:
        """POST generate-summary 对未登录用户返回 401。"""
        url = f"/api/repositories/{repository.id}/generate-summary/"
        response = api_client.post(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_generate_summary_returns_403_for_non_admin(
        self,
        authenticated_client: APIClient,
        repository: Repository,
        mock_dispatch,
    ) -> None:
        """#11：非空间管理员的已登录用户不得触发建立知识（fail-closed 403）。"""
        url = f"/api/repositories/{repository.id}/generate-summary/"
        response = authenticated_client.post(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        # 未越权派发：状态保持未开始
        repository.refresh_from_db()
        assert repository.ai_summary_status == AISummaryStatus.NOT_STARTED


@pytest.mark.django_db
class TestSummaryStatusEndpoint:
    """Test 4: GET /api/repositories/{id}/summary-status/ 端点。"""

    def test_summary_status_returns_correct_fields(
        self,
        authenticated_client: APIClient,
        repository: Repository,
    ) -> None:
        """GET summary-status 返回 status/progress/summary/generated_at/error 五个字段。"""
        url = f"/api/repositories/{repository.id}/summary-status/"
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "status" in data
        assert "progress" in data
        assert "summary" in data
        assert "generated_at" in data
        assert "error" in data

    def test_summary_status_reflects_model_state(
        self,
        authenticated_client: APIClient,
        repository: Repository,
    ) -> None:
        """GET summary-status 返回的值与模型字段一致。"""
        repository.ai_summary_status = AISummaryStatus.COMPLETED
        repository.ai_summary = "这是一个测试仓库的 AI 描述"
        repository.save(update_fields=["ai_summary_status", "ai_summary"])

        url = f"/api/repositories/{repository.id}/summary-status/"
        response = authenticated_client.get(url)
        data = response.json()
        assert data["status"] == "completed"
        assert data["summary"] == "这是一个测试仓库的 AI 描述"

    def test_summary_status_without_session_returns_empty_logs(
        self,
        authenticated_client: APIClient,
        repository: Repository,
    ) -> None:
        """无 REPO_SUMMARY 会话时 recent_logs 为空列表（不报错）。"""
        url = f"/api/repositories/{repository.id}/summary-status/"
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["recent_logs"] == []

    def test_summary_status_returns_recent_logs_tail(
        self,
        authenticated_client: APIClient,
        repository: Repository,
        user,
    ) -> None:
        """recent_logs 返回最近一次 REPO_SUMMARY 会话日志的尾部 30 条。"""
        from agents.models import AgentSession
        from subagent.models import SubAgentSession

        agent_session = AgentSession.objects.create(
            user=user,
            session_id="main-summary-logs-session",
        )
        # 40 条日志 → 仅返回尾部 30 条（与 _append_runtime_log 的 80 条上限独立）
        logs = [
            {"type": "tool_call", "content": f'Read({{"file_path": "f{i}.py"}})', "ts": i}
            for i in range(40)
        ]
        SubAgentSession.objects.create(
            session_id="reposummary-logs-test",
            main_session=agent_session,
            repo_url=repository.git_url,
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            status=SubAgentSession.Status.RUNNING,
            last_output={"repository_id": str(repository.id), "logs": logs},
        )
        repository.ai_summary_status = AISummaryStatus.RUNNING
        repository.save(update_fields=["ai_summary_status"])

        url = f"/api/repositories/{repository.id}/summary-status/"
        response = authenticated_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        recent = response.json()["recent_logs"]
        assert len(recent) == 30
        assert recent[0]["ts"] == 10
        assert recent[-1]["ts"] == 39
        assert recent[-1]["type"] == "tool_call"
