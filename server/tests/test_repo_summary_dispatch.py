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

    @pytest.fixture(autouse=True)
    def stub_empty_repo_check(self):
        """默认非空仓，避免 dispatch 前的空仓 fail-fast 触发真实 git ls-remote。"""
        with patch(
            "repositories.summary_service._is_empty_remote",
            new_callable=AsyncMock,
            return_value=False,
        ):
            yield

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
        """dispatch_repo_summary 创建 AgentSession(space=None) + SubAgentSession(task_type=REPO_SUMMARY)。"""
        from repositories.summary_service import dispatch_repo_summary

        session_id = await dispatch_repo_summary(repository)

        assert session_id is not None
        assert session_id.startswith("reposummary-")

        # 验证 AgentSession 创建
        agent_session = await AgentSession.objects.filter(
            session_id__startswith="agent-reposummary-",
        ).afirst()
        assert agent_session is not None
        assert agent_session.space is None
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
    async def test_dispatch_uses_claude_code_runtime_config(
        self,
        repository: Repository,
        mock_dispatcher,
        mock_render_prompt,
    ) -> None:
        """repo_summary 容器凭证统一走 Claude Code 运行时配置（CC 配置优先，内部回退 legacy）。"""
        from repositories.summary_service import dispatch_repo_summary

        with patch(
            "services.provider_config.aget_claude_code_runtime_config",
            new_callable=AsyncMock,
            return_value={
                "api_key": "sk-cc-test",
                "base_url": "https://proxy.example.com/anthropic",
                "opus_model": "model-opus",
                "sonnet_model": "model-sonnet",
                "haiku_model": "model-haiku",
                "default_model": "model-sonnet",
            },
        ):
            await dispatch_repo_summary(repository)

        meta = mock_dispatcher.call_args[0][0].metadata
        assert meta["env_FRIDAY_TASK_CLAUDE_API_KEY"] == "sk-cc-test"
        assert meta["env_FRIDAY_TASK_CLAUDE_BASE_URL"] == "https://proxy.example.com/anthropic"
        assert meta["env_FRIDAY_TASK_CLAUDE_MODEL"] == "model-sonnet"
        assert meta["env_FRIDAY_TASK_CLAUDE_SMALL_MODEL"] == "model-haiku"

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


@pytest.mark.django_db(transaction=True)
class TestBuildFacetVocabSection:
    """语义分面打标 prompt 注入段。

    回归保护：历史上无词表时返回空串 → prompt 不含打标要求 → 语义分面
    （业务线/产品线、服务对象、技术形态）永远为空，知识树分面视角全是"未分类"。
    """

    @pytest.mark.asyncio
    async def test_without_vocab_falls_back_to_freeform_tagging(self) -> None:
        """无词表时降级为自由打标：固定维度必须全部出现在注入段中。"""
        from repositories.summary_service import (
            SEMANTIC_FACET_DIMENSIONS,
            _build_facet_vocab_section,
        )

        section = await _build_facet_vocab_section()

        assert section != ""
        assert "facets" in section
        for dim in SEMANTIC_FACET_DIMENSIONS:
            assert dim in section

    @pytest.mark.asyncio
    async def test_with_vocab_uses_controlled_values(self) -> None:
        """有词表时维持受控行为：注入段列出词表取值。"""
        from repositories.models import FacetVocabulary
        from repositories.summary_service import _build_facet_vocab_section

        await FacetVocabulary.objects.acreate(
            dimension="服务对象",
            values=["C端学生", "B端学校"],
            is_active=True,
        )

        section = await _build_facet_vocab_section()

        assert "受控" in section
        assert "服务对象" in section
        assert "C端学生" in section
        assert "B端学校" in section

    @pytest.mark.asyncio
    async def test_inactive_vocab_is_ignored(self) -> None:
        """停用的词表不参与注入，行为退回自由打标。"""
        from repositories.models import FacetVocabulary
        from repositories.summary_service import _build_facet_vocab_section

        await FacetVocabulary.objects.acreate(
            dimension="服务对象",
            values=["停用词表专用取值"],
            is_active=False,
        )

        section = await _build_facet_vocab_section()

        assert "受控" not in section
        assert "停用词表专用取值" not in section
