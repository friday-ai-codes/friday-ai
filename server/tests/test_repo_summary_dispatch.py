"""implementation Task 2: dispatch_repo_summary 服务测试。

测试 dispatch 服务创建 AgentSession/SubAgentSession、构建 DispatchTask metadata、
渲染 prompt 和更新 repository 状态。
"""

from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from repositories.models import AISummaryStatus, Repository
from subagent.models import SubAgentSession


@pytest.mark.django_db(transaction=True)
class TestDispatchRepoSummary:
    """Test 5-8: dispatch_repo_summary 服务函数。"""

    @pytest.fixture
    def mock_dispatcher(self):
        """Mock get_dispatcher().dispatch() 避免真实分发。"""
        mock = AsyncMock()
        with patch("repositories.summary_service.get_dispatcher") as get_disp:
            dispatcher_instance = AsyncMock()
            dispatcher_instance.dispatch = mock
            get_disp.return_value = dispatcher_instance
            yield mock

    @pytest.fixture
    def mock_render_prompt(self):
        """Mock render_prompt 返回测试 prompt。"""
        with patch("repositories.summary_service.render_prompt", new_callable=AsyncMock) as mock:
            mock.return_value = "你是一个仓库分析助手..."
            yield mock

    @pytest.mark.asyncio
    async def test_creates_agent_and_sub_session(
        self,
        repository: Repository,
        mock_dispatcher,
        mock_render_prompt,
    ) -> None:
        """dispatch_repo_summary 创建 AgentSession(project=None) + SubAgentSession(task_type=REPO_SUMMARY)。"""
        from repositories.summary_service import dispatch_repo_summary

        session_id = await dispatch_repo_summary(repository)

        assert session_id is not None
        assert session_id.startswith("reposummary-")

        # 验证 AgentSession 创建
        agent_session = await AgentSession.objects.filter(
            session_id__startswith="agent-reposummary-",
        ).afirst()
        assert agent_session is not None
        assert agent_session.project is None
        assert agent_session.status == AgentSession.Status.RUNNING

        # 验证 SubAgentSession 创建
        sub_session = await SubAgentSession.objects.filter(
            session_id=session_id,
        ).afirst()
        assert sub_session is not None
        assert sub_session.task_type == SubAgentSession.TaskType.REPO_SUMMARY
        assert sub_session.status == SubAgentSession.Status.PENDING

    @pytest.mark.asyncio
    async def test_dispatch_task_metadata_contains_task_mode(
        self,
        repository: Repository,
        mock_dispatcher,
        mock_render_prompt,
    ) -> None:
        """dispatch_repo_summary 构建的 DispatchTask.metadata 包含 env_FRIDAY_TASK_MODE: repo_summary。"""
        from repositories.summary_service import dispatch_repo_summary

        await dispatch_repo_summary(repository)

        # 验证 dispatch 被调用
        mock_dispatcher.assert_called_once()
        dispatch_task = mock_dispatcher.call_args[0][0]
        assert dispatch_task.metadata["env_FRIDAY_TASK_MODE"] == "repo_summary"

    @pytest.mark.asyncio
    async def test_renders_prompt_with_correct_slug(
        self,
        repository: Repository,
        mock_dispatcher,
        mock_render_prompt,
    ) -> None:
        """dispatch_repo_summary 调用 render_prompt(PromptSlugs.REPO_SUMMARY_GENERATOR, ...)。"""
        from prompts.keys import PromptSlugs
        from repositories.summary_service import dispatch_repo_summary

        await dispatch_repo_summary(repository)

        mock_render_prompt.assert_called_once()
        call_args = mock_render_prompt.call_args
        assert call_args[0][0] == PromptSlugs.REPO_SUMMARY_GENERATOR

    @pytest.mark.asyncio
    async def test_updates_repository_status_to_pending(
        self,
        repository: Repository,
        mock_dispatcher,
        mock_render_prompt,
    ) -> None:
        """dispatch_repo_summary 成功后 repository.ai_summary_status 变为 pending。"""
        from repositories.summary_service import dispatch_repo_summary

        await dispatch_repo_summary(repository)

        await repository.arefresh_from_db()
        assert repository.ai_summary_status == AISummaryStatus.PENDING
