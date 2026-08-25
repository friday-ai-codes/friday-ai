"""服务端 repo_summary 回调硬切测试（260818-pt8 D-01/D-02）。

权威结果只认共享 MCP 工厂捕获的 `output.mcp_result`（dict）；仅含 `output.text`
的旧自由文本 / 围栏 JSON 渠道明确拒绝（fail-closed，写 failed 状态，不落库有效树）。
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


def _mcp_payload(mcp_result: dict) -> dict:
    """构造结构化 MCP completed payload（唯一权威渠道）。"""
    return {
        "result_type": "text",
        "output": {
            "task_type": "repo_summary",
            "submit_scenario": "repo_summary",
            "mcp_result": mcp_result,
        },
    }


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
    """_handle_completed repo_summary 分支：只认 mcp_result。"""

    @pytest.mark.asyncio
    async def test_completed_writes_ai_summary_and_status(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """mcp_result 成功 → 写回 ai_summary + status=completed + generated_at。"""
        from subagent.api.callbacks import _handle_completed

        payload = _mcp_payload({"overview": "A cool repo", "tech_stack": ["Python"]})
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
        """mcp_result 写库时序列化为缩进 JSON（tree 剥离后）。"""
        from subagent.api.callbacks import _handle_completed

        payload = _mcp_payload({"overview": "A repo", "tech_stack": ["Python", "Django"]})
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._schedule_workflow_resume"):
                with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                    await _handle_completed(sub_session, payload, log)

        await repository.arefresh_from_db()
        assert '"overview": "A repo"' in repository.ai_summary
        assert "\n" in repository.ai_summary

    @pytest.mark.asyncio
    async def test_completed_rejects_pure_text_output(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """仅含 output.text（旧自由文本/围栏 JSON）→ 明确拒绝，写 failed 状态。"""
        from subagent.api.callbacks import _handle_completed

        payload = {
            "result_type": "text",
            "output": {"text": '{"overview":"free text json should be rejected"}'},
        }
        log = AsyncMock()
        log.info = lambda *a, **kw: None
        log.debug = lambda *a, **kw: None

        with patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock):
            with patch("subagent.api.callbacks._schedule_workflow_resume"):
                with patch("subagent.api.callbacks._schedule_agent_session_resume"):
                    await _handle_completed(sub_session, payload, log)

        await repository.arefresh_from_db()
        assert repository.ai_summary_status == AISummaryStatus.FAILED
        assert "mcp_result_missing" in repository.ai_summary_error
        # 拒绝写入有效摘要正文
        assert "free text json" not in (repository.ai_summary or "")

    @pytest.mark.asyncio
    async def test_completed_truncates_long_summary(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        """mcp_result 序列化超过 8192 字符时截断。"""
        from subagent.api.callbacks import _handle_completed

        payload = _mcp_payload({"overview": "x" * 10000})
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
    """树写入成功后的后台任务必须先补刷事实分面，再做节点向量化与域树归类。"""

    @pytest.mark.asyncio
    async def test_completed_with_tree_schedules_facet_refresh_first(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        from subagent.api.callbacks import _update_repository_on_summary_complete

        payload = _mcp_payload({
            "overview": "A repo",
            "tree": [{"node_id": "root", "title": "root"}],
            "facets": {"服务对象": "C端学生"},
        })

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

        await repository.arefresh_from_db()
        assert repository.facets.get("服务对象") == "C端学生"

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
        from subagent.api.callbacks import _update_repository_on_summary_complete

        payload = _mcp_payload({
            "overview": "A repo",
            "tree": [{"node_id": "root", "title": "root"}],
        })

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
    """_handle_failed repo_summary 分支（失败路径不受 MCP 硬切影响）。"""

    @pytest.mark.asyncio
    async def test_failed_writes_error_status(
        self, sub_session: SubAgentSession, repository: Repository
    ) -> None:
        from subagent.api.callbacks import _handle_failed

        payload = {"error": "Container OOM killed"}
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
