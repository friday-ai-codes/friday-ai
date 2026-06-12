"""repo_summary 状态 reconcile 测试 — 修复 pending 与 SubAgentSession 终态不一致。"""

import pytest
from asgiref.sync import async_to_sync

from repositories.models import AISummaryStatus, Repository
from repositories.summary_service import reconcile_ai_summary_status
from subagent.models import SubAgentSession


def _make_repo_summary_session(
    repository: Repository,
    agent_session,
    *,
    status: str,
    failure_reason: str = "",
) -> SubAgentSession:
    return SubAgentSession.objects.create(
        session_id=f"reposummary-reconcile-{repository.pk}-{status}",
        main_session=agent_session,
        repo_url=repository.git_url,
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=status,
        failure_reason=failure_reason,
        last_output={"repository_id": str(repository.pk)},
    )


@pytest.fixture
def agent_session(db, user):
    from agents.models import AgentSession

    return AgentSession.objects.create(
        user=user,
        session_id="main-reconcile-session",
    )


@pytest.mark.django_db
class TestReconcileAiSummaryStatus:
    def test_reconcile_pending_to_failed_when_session_error(
        self,
        repository: Repository,
        agent_session,
    ) -> None:
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        _make_repo_summary_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.ERROR,
            failure_reason="exited with code 1",
        )

        async_to_sync(reconcile_ai_summary_status)(repository)
        repository.refresh_from_db()

        assert repository.ai_summary_status == AISummaryStatus.FAILED
        assert "exited with code 1" in repository.ai_summary_error

    def test_reconcile_pending_to_running_when_session_running(
        self,
        repository: Repository,
        agent_session,
    ) -> None:
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        _make_repo_summary_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.RUNNING,
        )

        async_to_sync(reconcile_ai_summary_status)(repository)
        repository.refresh_from_db()

        assert repository.ai_summary_status == AISummaryStatus.RUNNING

    def test_reconcile_stale_pending_without_runner_to_failed(
        self,
        repository: Repository,
        agent_session,
    ) -> None:
        """PENDING + 无 Runner 接收 + 超过阈值 → 判定派发丢失，收敛为失败终态。"""
        from datetime import timedelta

        from django.utils import timezone

        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        session = _make_repo_summary_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
        )
        # created_at 是 auto_now_add，直接 update 回拨 11 分钟
        SubAgentSession.objects.filter(pk=session.pk).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )

        async_to_sync(reconcile_ai_summary_status)(repository)
        repository.refresh_from_db()
        session.refresh_from_db()

        assert repository.ai_summary_status == AISummaryStatus.FAILED
        assert "未被 Runner 接收" in repository.ai_summary_error
        assert session.status == SubAgentSession.Status.TIMEOUT

    def test_reconcile_fresh_pending_stays_pending(
        self,
        repository: Repository,
        agent_session,
    ) -> None:
        """刚派发的 PENDING（未超阈值）不被误判，保持排队状态。"""
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        session = _make_repo_summary_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
        )

        async_to_sync(reconcile_ai_summary_status)(repository)
        repository.refresh_from_db()
        session.refresh_from_db()

        assert repository.ai_summary_status == AISummaryStatus.PENDING
        assert session.status == SubAgentSession.Status.PENDING
