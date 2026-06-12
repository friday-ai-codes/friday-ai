"""implementation Task 1: 服务端回调处理扩展测试。

测试 _handle_completed 和 _handle_failed 中 repo_summary 分支，
确认结果正确写回 Repository.ai_summary 和 ai_summary_error 字段。
"""

from unittest.mock import AsyncMock, patch

import pytest

from repositories.models import AISummaryStatus, Repository
from subagent.models import SubAgentSession


def _make_session_with_repo(repository: Repository, agent_session) -> SubAgentSession:
    """创建一个 task_type=REPO_SUMMARY 的 SubAgentSession，last_output 含 repository_id。"""
    return SubAgentSession.objects.create(
        session_id=f"reposummary-test-{repository.pk}",
        main_session=agent_session,
        repo_url=repository.git_url,
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=SubAgentSession.Status.RUNNING,
        last_output={"repository_id": str(repository.pk)},
    )


@pytest.fixture
def agent_session(db, user):
    """创建一个 AgentSession 供 SubAgentSession 关联。"""
    from agents.models import AgentSession

    return AgentSession.objects.create(
        user=user,
        session_id="main-test-session",
    )


@pytest.fixture
def sub_session(db, repository, agent_session):
    """创建 repo_summary 类型的 SubAgentSession。"""
    return _make_session_with_repo(repository, agent_session)


@pytest.mark.django_db(transaction=True)
class TestHandleCompletedRepoSummary:
    """Test 1-4: _handle_completed repo_summary 分支。"""

    @pytest.mark.asyncio
    async def test_completed_writes_ai_summary_and_status(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """Test 1: _handle_completed 当 task_type=REPO_SUMMARY 时写回 ai_summary + status=completed + generated_at。"""
        from subagent.api.callbacks import _handle_completed

        payload = {
            "result_type": "text",
            "output": {"text": '{"overview": "A cool repo"}'},
        }
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._schedule_workflow_resume"):
                with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                    resp = await _handle_completed(sub_session, payload, log)

        assert resp.status_code == 200

        await repository.arefresh_from_db()
        assert repository.ai_summary_status == AISummaryStatus.COMPLETED
        assert repository.ai_summary is not None
        assert repository.ai_summary_generated_at is not None
        assert repository.ai_summary_error == ""

    @pytest.mark.asyncio
    async def test_completed_stores_formatted_json(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """Test 2: payload output.text 是合法 JSON 时，ai_summary 存储格式化的 JSON。"""
        from subagent.api.callbacks import _handle_completed

        raw_json = '{"overview":"A repo","tech_stack":["Python","Django"]}'
        payload = {
            "result_type": "text",
            "output": {"text": raw_json},
        }
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._schedule_workflow_resume"):
                with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                    await _handle_completed(sub_session, payload, log)

        await repository.arefresh_from_db()
        # 应格式化为缩进 JSON
        assert '"overview": "A repo"' in repository.ai_summary
        assert "\n" in repository.ai_summary  # 含换行（缩进格式）

    @pytest.mark.asyncio
    async def test_completed_stores_raw_text_on_invalid_json(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """Test 3: payload output.text 不是合法 JSON 时，ai_summary 存储原始文本。"""
        from subagent.api.callbacks import _handle_completed

        raw_markdown = "# Summary\n\nThis is a **markdown** summary."
        payload = {
            "result_type": "text",
            "output": {"text": raw_markdown},
        }
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._schedule_workflow_resume"):
                with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                    await _handle_completed(sub_session, payload, log)

        await repository.arefresh_from_db()
        assert repository.ai_summary == raw_markdown

    @pytest.mark.asyncio
    async def test_completed_truncates_long_summary(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """Test 4: ai_summary 长度超过 8192 字符时截断。"""
        from subagent.api.callbacks import _handle_completed

        long_text = "x" * 10000
        payload = {
            "result_type": "text",
            "output": {"text": long_text},
        }
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._schedule_workflow_resume"):
                with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                    await _handle_completed(sub_session, payload, log)

        await repository.arefresh_from_db()
        assert len(repository.ai_summary) == 8192


@pytest.mark.django_db(transaction=True)
class TestPostTreeTasksFacetRefresh:
    """树写入成功后的后台任务必须先补刷事实分面，再做节点向量化与域树归类。

    回归保护：索引完成时 ai_summary_tree 往往尚未回写（summary 任务异步），
    索引侧的 _refresh_tree_facts 会被跳过；若回调侧不补刷，事实分面
    （团队归属/技术栈/活跃度）永远为空，知识树兜底分组全部落"未分组"。
    """

    @pytest.mark.asyncio
    async def test_completed_with_tree_schedules_facet_refresh_first(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        import json

        from subagent.api.callbacks import _update_repository_on_summary_complete

        payload = {
            "result_type": "text",
            "output": {
                "text": json.dumps({
                    "overview": "A repo",
                    "tree": [{"node_id": "root", "title": "root"}],
                    "facets": {"服务对象": "C端学生"},
                })
            },
        }

        captured: dict = {}

        def fake_run_in_background(fn, name=""):
            captured["fn"] = fn

        with patch(
            "repositories.tree_schema.validate_and_assemble_tree",
            new=AsyncMock(return_value=[{"node_id": "root", "title": "root"}]),
        ):
            with patch(
                "services.background_runner.run_in_background",
                side_effect=fake_run_in_background,
            ):
                await _update_repository_on_summary_complete(sub_session, payload)

        # 语义分面已随回调写回
        await repository.arefresh_from_db()
        assert repository.facets.get("服务对象") == "C端学生"

        # 后台任务被调度，且执行顺序为：事实分面刷新 → 节点向量化 → 域树归类
        assert "fn" in captured
        call_order: list[str] = []
        with patch(
            "repositories.facet_service.FacetService.refresh_fact_facets",
            new=AsyncMock(side_effect=lambda rid: call_order.append("facets")),
        ):
            with patch(
                "codegraph.services.repo_index_tree.RepoIndexTreeBuilder.build",
                new=AsyncMock(side_effect=lambda rid: call_order.append("build")),
            ):
                with patch(
                    "codegraph.services.corpus_tree.CorpusTreeService.assign_repository",
                    new=AsyncMock(side_effect=lambda rid: call_order.append("assign")),
                ):
                    await captured["fn"]()

        assert call_order == ["facets", "build", "assign"]

    @pytest.mark.asyncio
    async def test_facet_refresh_failure_does_not_block_node_indexing(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        import json

        from subagent.api.callbacks import _update_repository_on_summary_complete

        payload = {
            "result_type": "text",
            "output": {
                "text": json.dumps({
                    "overview": "A repo",
                    "tree": [{"node_id": "root", "title": "root"}],
                })
            },
        }

        captured: dict = {}

        with patch(
            "repositories.tree_schema.validate_and_assemble_tree",
            new=AsyncMock(return_value=[{"node_id": "root", "title": "root"}]),
        ):
            with patch(
                "services.background_runner.run_in_background",
                side_effect=lambda fn, name="": captured.update(fn=fn),
            ):
                await _update_repository_on_summary_complete(sub_session, payload)

        call_order: list[str] = []
        with patch(
            "repositories.facet_service.FacetService.refresh_fact_facets",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            with patch(
                "codegraph.services.repo_index_tree.RepoIndexTreeBuilder.build",
                new=AsyncMock(side_effect=lambda rid: call_order.append("build")),
            ):
                with patch(
                    "codegraph.services.corpus_tree.CorpusTreeService.assign_repository",
                    new=AsyncMock(side_effect=lambda rid: call_order.append("assign")),
                ):
                    await captured["fn"]()

        assert call_order == ["build", "assign"]


@pytest.mark.django_db(transaction=True)
class TestHandleFailedRepoSummary:
    """Test 5: _handle_failed repo_summary 分支。"""

    @pytest.mark.asyncio
    async def test_failed_writes_error_status(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """Test 5: _handle_failed 当 task_type=REPO_SUMMARY 时写回 status=failed + ai_summary_error。"""
        from subagent.api.callbacks import _handle_failed

        payload = {
            "error": "Container OOM killed",
        }
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock):
                with patch("subagent.api.callbacks._schedule_workflow_resume"):
                    with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                        resp = await _handle_failed(sub_session, payload, log)

        assert resp.status_code == 200

        await repository.arefresh_from_db()
        assert repository.ai_summary_status == AISummaryStatus.FAILED
        assert "Container OOM killed" in repository.ai_summary_error
