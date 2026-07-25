"""AI 描述状态唯一真相派生 + 读时自愈测试（架构根治）。

验证：Repository.ai_summary_status 降级为「可自愈缓存」，展示读取一律从最新
REPO_SUMMARY SubAgentSession 派生——杜绝「幻影 running」（仓库缓存停在生成中、
实际无 session 在跑）。
"""

import pytest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync

from repositories.models import AISummaryStatus, Repository
from repositories.summary_service import aresolve_summary_status, derive_summary_status
from subagent.models import SubAgentSession, TaskResult


def _make_session(
    repository: Repository,
    agent_session,
    *,
    status: str,
    failure_reason: str = "",
    session_suffix: str = "",
) -> SubAgentSession:
    return SubAgentSession.objects.create(
        session_id=f"reposummary-derive-{repository.pk}-{status}{session_suffix}",
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

    return AgentSession.objects.create(user=user, session_id="main-derive-session")


class TestDeriveSummaryStatus:
    @pytest.mark.parametrize(
        "session_status,expected",
        [
            (SubAgentSession.Status.COMPLETED, AISummaryStatus.COMPLETED),
            (SubAgentSession.Status.ERROR, AISummaryStatus.FAILED),
            (SubAgentSession.Status.TIMEOUT, AISummaryStatus.FAILED),
            (SubAgentSession.Status.CANCELLED, AISummaryStatus.FAILED),
            (SubAgentSession.Status.RUNNING, AISummaryStatus.RUNNING),
            (SubAgentSession.Status.PENDING, AISummaryStatus.PENDING),
        ],
    )
    def test_mapping(self, session_status: str, expected: str) -> None:
        assert derive_summary_status(session_status) == expected

    def test_unknown_returns_none(self) -> None:
        assert derive_summary_status("weird_state") is None


@pytest.mark.django_db
class TestResolveSummaryStatus:
    def test_phantom_running_healed_to_failed(
        self, repository: Repository, agent_session
    ) -> None:
        """核心场景：仓库缓存停在 running，最新 session 已 timeout → 读时纠正为 failed。"""
        repository.ai_summary_status = AISummaryStatus.RUNNING
        repository.save(update_fields=["ai_summary_status"])
        _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.TIMEOUT,
            failure_reason="容器僵死",
        )

        result = async_to_sync(aresolve_summary_status)(repository)
        repository.refresh_from_db()

        assert result == AISummaryStatus.FAILED
        assert repository.ai_summary_status == AISummaryStatus.FAILED
        assert "容器僵死" in repository.ai_summary_error

    def test_stale_pending_healed_to_completed_with_content(
        self, repository: Repository, agent_session
    ) -> None:
        """仓库缓存停在 pending，最新 session 已 completed → 回填内容 + 置 completed。"""
        repository.ai_summary_status = AISummaryStatus.PENDING
        repository.ai_summary = ""
        repository.save(update_fields=["ai_summary_status", "ai_summary"])
        session = _make_session(
            repository, agent_session, status=SubAgentSession.Status.COMPLETED
        )
        TaskResult.objects.create(
            session=session,
            result_type="text",
            text_output='{"overview": "一个测试仓库"}',
            raw_output={"text": '{"overview": "一个测试仓库"}'},
        )

        result = async_to_sync(aresolve_summary_status)(repository)
        repository.refresh_from_db()

        assert result == AISummaryStatus.COMPLETED
        assert repository.ai_summary_status == AISummaryStatus.COMPLETED
        assert "测试仓库" in (repository.ai_summary or "")

    def test_no_session_returns_stored(self, repository: Repository) -> None:
        repository.ai_summary_status = AISummaryStatus.NOT_STARTED
        repository.save(update_fields=["ai_summary_status"])

        result = async_to_sync(aresolve_summary_status)(repository)

        assert result == AISummaryStatus.NOT_STARTED

    def test_consistent_status_unchanged(
        self, repository: Repository, agent_session
    ) -> None:
        """缓存与 session 一致（running==running）时返回原值，不误改。"""
        repository.ai_summary_status = AISummaryStatus.RUNNING
        repository.save(update_fields=["ai_summary_status"])
        _make_session(repository, agent_session, status=SubAgentSession.Status.RUNNING)

        result = async_to_sync(aresolve_summary_status)(repository)
        repository.refresh_from_db()

        assert result == AISummaryStatus.RUNNING
        assert repository.ai_summary_status == AISummaryStatus.RUNNING


@pytest.mark.django_db
class TestActiveSummaryRows:
    """任务中心「建立知识」在途枚举（``system.tasks_views._active_summary_rows``）。

    该 helper 原名 ``_active_summary_tasks`` 且直接产出 ``(count, items)``；重构后
    只负责"哪些仓库真的有在途 session"这一层事实，产出
    ``{repository_id: session_status}``，仓库名与展示态由 ``ActiveTasksView``
    用 ``derive_summary_status`` 二次加工。幻影过滤与按仓去重仍在本 helper 内，
    故守护点不变。
    """

    def test_phantom_not_listed(self, repository: Repository, agent_session) -> None:
        """任务中心列表只反映存活 session：缓存=running 但 session 终态的幻影不出现。"""
        from system.tasks_views import _active_summary_rows

        repository.ai_summary_status = AISummaryStatus.RUNNING
        repository.save(update_fields=["ai_summary_status"])
        _make_session(repository, agent_session, status=SubAgentSession.Status.TIMEOUT)

        assert _active_summary_rows(None) == {}

    def test_live_session_listed(self, repository: Repository, agent_session) -> None:
        from system.tasks_views import _active_summary_rows

        _make_session(repository, agent_session, status=SubAgentSession.Status.RUNNING)

        rows = _active_summary_rows(None)

        assert list(rows) == [str(repository.pk)]
        assert derive_summary_status(rows[str(repository.pk)]) == AISummaryStatus.RUNNING

    def test_dedup_multiple_sessions_per_repo(
        self, repository: Repository, agent_session
    ) -> None:
        from system.tasks_views import _active_summary_rows

        _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.PENDING,
            session_suffix="-a",
        )
        _make_session(
            repository,
            agent_session,
            status=SubAgentSession.Status.RUNNING,
            session_suffix="-b",
        )

        assert len(_active_summary_rows(None)) == 1


@pytest.mark.django_db(transaction=True)
class TestDispatchEmptyRepoFailFast:
    """空仓 fail-fast：零分支空仓不派发容器、不烧 token，直接标失败并给明确文案。"""

    @pytest.mark.asyncio
    async def test_empty_repo_marked_failed_without_dispatch(
        self, repository: Repository
    ) -> None:
        from repositories.summary_service import dispatch_repo_summary

        with (
            patch(
                "repositories.summary_service._is_empty_remote",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("repositories.summary_service.get_dispatcher") as get_disp,
        ):
            dispatcher = AsyncMock()
            get_disp.return_value = dispatcher

            session_id = await dispatch_repo_summary(repository)

        assert session_id == ""
        dispatcher.dispatch.assert_not_called()
        await repository.arefresh_from_db()
        assert repository.ai_summary_status == AISummaryStatus.FAILED
        assert "仓库为空" in repository.ai_summary_error
        exists = await SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            last_output__repository_id=str(repository.pk),
        ).aexists()
        assert exists is False


@pytest.mark.asyncio
async def test_aremote_branch_count_unparseable_returns_minus_one() -> None:
    """ls-remote 失败（不可判定）返回 -1，调用方据此放行而非误判空仓。"""
    from services.git_credentials import aremote_branch_count

    result = await aremote_branch_count("https://invalid.invalid/nope.git")
    assert result == -1
