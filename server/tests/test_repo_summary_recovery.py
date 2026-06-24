"""recover_stranded_summaries 测试。

durable 兜底安全网：修复 summary 派发走进程内存队列、server/runner 重启即丢、
SubAgentSession 永卡 pending 的缺口。重点验证：
- 搁浅（updated_at 陈旧）的 pending/running 会被重派，旧会话收敛为 TIMEOUT；
- 关键：判定**只看 updated_at 陈旧度、不看 runner_id**，因此「已分配但容器从未执行」
  （runner_id 已设、历史 reconcile 救不到）的孤儿也能被恢复；
- 刚派发（未陈旧）的不被误判；已完成/失败的仓库不被无限重试；仓库已删则收尾会话。
"""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from repositories.models import AISummaryStatus, Repository
from repositories.summary_service import recover_stranded_summaries
from subagent.models import SubAgentSession


@pytest.fixture
def agent_session(db, user):
    from agents.models import AgentSession

    return AgentSession.objects.create(user=user, session_id="main-recover-session")


def _make_session(
    repository: Repository,
    agent_session,
    *,
    status: str,
    age_minutes: float,
) -> SubAgentSession:
    session = SubAgentSession.objects.create(
        session_id=f"reposummary-recover-{repository.pk}-{status}-{age_minutes}",
        main_session=agent_session,
        repo_url=repository.git_url,
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=status,
        last_output={"repository_id": str(repository.pk)},
    )
    # updated_at 是 auto_now，直接 update 回拨模拟「无进展」时长。
    SubAgentSession.objects.filter(pk=session.pk).update(
        updated_at=timezone.now() - timedelta(minutes=age_minutes)
    )
    session.refresh_from_db()
    return session


@pytest.mark.django_db
class TestRecoverStrandedSummaries:
    def test_stranded_pending_is_redispatched_and_old_session_timed_out(
        self, repository: Repository, agent_session
    ) -> None:
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        stale = _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
            age_minutes=20,
        )

        with patch(
            "repositories.summary_service.dispatch_repo_summary",
            new=AsyncMock(return_value="reposummary-new"),
        ) as dispatch:
            recovered = async_to_sync(recover_stranded_summaries)()

        assert recovered == 1
        dispatch.assert_awaited_once()
        stale.refresh_from_db()
        assert stale.status == SubAgentSession.Status.TIMEOUT

    def test_running_orphan_recovered_regardless_of_runner_id(
        self, repository: Repository, agent_session
    ) -> None:
        """running + 陈旧也算搁浅；判定不依赖 runner_id（历史 reconcile 的盲区）。"""
        repository.ai_summary_status = AISummaryStatus.RUNNING
        repository.save(update_fields=["ai_summary_status"])
        _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.RUNNING,
            age_minutes=30,
        )

        with patch(
            "repositories.summary_service.dispatch_repo_summary",
            new=AsyncMock(return_value="reposummary-new"),
        ) as dispatch:
            recovered = async_to_sync(recover_stranded_summaries)()

        assert recovered == 1
        dispatch.assert_awaited_once()

    def test_fresh_pending_not_touched(
        self, repository: Repository, agent_session
    ) -> None:
        """刚派发（未达搁浅阈值）的 pending 不被误重派。"""
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        fresh = _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
            age_minutes=1,
        )

        with patch(
            "repositories.summary_service.dispatch_repo_summary",
            new=AsyncMock(),
        ) as dispatch:
            recovered = async_to_sync(recover_stranded_summaries)()

        assert recovered == 0
        dispatch.assert_not_awaited()
        fresh.refresh_from_db()
        assert fresh.status == SubAgentSession.Status.PENDING

    def test_completed_repo_not_recovered(
        self, repository: Repository, agent_session
    ) -> None:
        """仓库 summary 已完成 → 即便残留陈旧会话也不重派（避免无意义重跑）。"""
        repository.ai_summary_status = AISummaryStatus.COMPLETED
        repository.save(update_fields=["ai_summary_status"])
        _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
            age_minutes=20,
        )

        with patch(
            "repositories.summary_service.dispatch_repo_summary",
            new=AsyncMock(),
        ) as dispatch:
            recovered = async_to_sync(recover_stranded_summaries)()

        assert recovered == 0
        dispatch.assert_not_awaited()

    def test_deleted_repo_session_cleaned_not_redispatched(
        self, repository: Repository, agent_session
    ) -> None:
        """仓库已删 → 收尾搁浅会话为 TIMEOUT，且不重派。"""
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        stale = _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
            age_minutes=20,
        )
        Repository.objects.filter(pk=repository.pk).update(is_deleted=True)

        with patch(
            "repositories.summary_service.dispatch_repo_summary",
            new=AsyncMock(),
        ) as dispatch:
            recovered = async_to_sync(recover_stranded_summaries)()

        assert recovered == 0
        dispatch.assert_not_awaited()
        stale.refresh_from_db()
        assert stale.status == SubAgentSession.Status.TIMEOUT

    def test_limit_caps_redispatch_per_sweep(
        self, repository: Repository, agent_session
    ) -> None:
        """limit 上限生效：单轮最多重派 limit 个仓库（逐步 ramp 不打爆）。"""
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.save(update_fields=["ai_summary_status"])
        repos = [repository]
        for i in range(2):
            repos.append(
                Repository.objects.create(
                    name=f"recover/extra-{i}",
                    git_url=f"https://gitlab.example.com/recover/extra-{i}.git",
                    ai_summary_status=AISummaryStatus.PENDING,
                )
            )
        for r in repos:
            _make_session(
                r,
                agent_session,
                status=SubAgentSession.Status.PENDING,
                age_minutes=20,
            )

        with patch(
            "repositories.summary_service.dispatch_repo_summary",
            new=AsyncMock(return_value="x"),
        ) as dispatch:
            recovered = async_to_sync(recover_stranded_summaries)(limit=2)

        assert recovered == 2
        assert dispatch.await_count == 2
