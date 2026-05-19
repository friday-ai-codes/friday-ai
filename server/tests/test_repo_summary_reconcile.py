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
 repository.refresh_from_db
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
 repository.refresh_from_db
 assert repository.ai_summary_status == AISummaryStatus.RUNNING
