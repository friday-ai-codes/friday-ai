"""ConversationService.get_conversation_runtime 单元测试。

覆盖 runtime API 的核心场景：
- OrchestrationRun 状态映射到 runtime 返回值
- inactive when completed / interrupted
- task_progress 从 metadata.progress 中提取
- 超过 1 小时的 running run 视为 error
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.utils import timezone

from orchestration.models import OrchestrationRun


class _AsyncIterator:
    """辅助 async iterator，用于 mock Django async queryset。"""

    def __init__(self, items: list[Any]) -> None:
        self._items = iter(items)

    def __aiter__(self) -> _AsyncIterator:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def _mock_orch_run(
    *,
    status: str = "running",
    phase: str = "executing",
    run_id: str = "aaaa-bbbb",
    metadata: dict[str, Any] | None = None,
    created_at: Any = None,
) -> MagicMock:
    """构造 mock OrchestrationRun 实例。"""
    mock = MagicMock(spec=OrchestrationRun)
    mock.status = status
    mock.phase = phase
    mock.run_id = run_id
    mock.metadata = metadata or {}
    mock.created_at = created_at or timezone.now()
    mock.id = 1
    return mock


def _setup_session_mock(mock_sess_cls: MagicMock, sessions: list[Any] | None = None) -> None:
    """为 SubAgentSession mock 配置 async iterator。"""
    mock_sess_cls.TaskType.EXPLORE = "explore"
    mock_sess_cls.Status.PENDING = "pending"
    mock_sess_cls.Status.RUNNING = "running"

    qs = MagicMock()
    qs.order_by.return_value = _AsyncIterator(sessions or [])
    mock_sess_cls.objects.filter.return_value = qs


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runtime_from_orchestration_run() -> None:
    """OrchestrationRun running → active=True, 返回 phase/status/orchestration_run_id。"""
    mock_run = _mock_orch_run(status="running", phase="executing", run_id="run-123")

    with (
        patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
        patch("subagent.models.SubAgentSession") as mock_sess_cls,
    ):
        mock_orch_cls.Status = OrchestrationRun.Status
        mock_orch_cls.Phase = OrchestrationRun.Phase
        mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=mock_run,
        )
        _setup_session_mock(mock_sess_cls)

        from chat.conversation_service import ConversationService
        runtime = await ConversationService.get_conversation_runtime("a7c0e3b1-8d4f-4e2b-9c6d-1f3e5a7b9c0d")

    assert runtime["active"] is True
    assert runtime["status"] == "running"
    assert runtime["phase"] == "executing"
    assert runtime["orchestration_run_id"] == "run-123"
    assert runtime["mode"] == "chat"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runtime_inactive_when_completed() -> None:
    """OrchestrationRun status=completed → active=False。"""
    mock_run = _mock_orch_run(status="completed", phase="completed")

    with (
        patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
        patch("subagent.models.SubAgentSession") as mock_sess_cls,
    ):
        mock_orch_cls.Status = OrchestrationRun.Status
        mock_orch_cls.Phase = OrchestrationRun.Phase
        mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=mock_run,
        )
        _setup_session_mock(mock_sess_cls)

        from chat.conversation_service import ConversationService
        runtime = await ConversationService.get_conversation_runtime("a7c0e3b1-8d4f-4e2b-9c6d-1f3e5a7b9c0d")

    assert runtime["active"] is False
    assert runtime["status"] == "completed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runtime_with_task_progress() -> None:
    """metadata 含 progress → runtime 返回 task_progress。"""
    mock_run = _mock_orch_run(
        status="waiting",
        phase="waiting",
        metadata={"progress": {"completed": 2, "total": 3}},
    )

    with (
        patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
        patch("subagent.models.SubAgentSession") as mock_sess_cls,
    ):
        mock_orch_cls.Status = OrchestrationRun.Status
        mock_orch_cls.Phase = OrchestrationRun.Phase
        mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=mock_run,
        )
        _setup_session_mock(mock_sess_cls)

        from chat.conversation_service import ConversationService
        runtime = await ConversationService.get_conversation_runtime("a7c0e3b1-8d4f-4e2b-9c6d-1f3e5a7b9c0d")

    assert runtime["task_progress"] == {"completed": 2, "total": 3}
    assert runtime["active"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runtime_timeout_window() -> None:
    """超过 1 小时的 running run 视为 error，auto-close。"""
    mock_run = _mock_orch_run(
        status="running",
        phase="executing",
        created_at=timezone.now() - timedelta(hours=2),
    )

    with (
        patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
        patch("subagent.models.SubAgentSession") as mock_sess_cls,
    ):
        mock_orch_cls.Status = OrchestrationRun.Status
        mock_orch_cls.Phase = OrchestrationRun.Phase
        mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=mock_run,
        )
        mock_orch_cls.objects.filter.return_value.aupdate = AsyncMock(return_value=1)
        _setup_session_mock(mock_sess_cls)

        from chat.conversation_service import ConversationService
        runtime = await ConversationService.get_conversation_runtime("a7c0e3b1-8d4f-4e2b-9c6d-1f3e5a7b9c0d")

    assert runtime["active"] is False
    assert runtime["status"] == "error"


# ============================================================================
# ConversationRuntime payload 携带 coding_plan
# ============================================================================


@pytest.fixture
def conversation_for_runtime(db, project):
    """Conversation 真实落库，给 ConversationService 用。"""
    from chat.models import Conversation

    return Conversation.objects.create(space=project, title="work item 测试")


@pytest.fixture
def coding_plan_for_runtime(db, conversation_for_runtime):
    """与 conversation 关联的 CodingPlan。"""
    from chat.models import CodingPlan

    return CodingPlan.objects.create(
        conversation=conversation_for_runtime,
        tech_plan="## 多仓 fan-out 方案",
        affected_files=[],
        title="work item 方案",
    )


@pytest.fixture
def three_repos_for_runtime(db, project):
    """3 个 Repository 全部挂到 conversation 所属 project。"""
    from repositories.models import Repository

    repos = []
    for name in ["alpha", "beta", "gamma"]:
        r = Repository.objects.create(
            name=name,
            git_url=f"https://gitlab.com/test/{name}.git",
            git_platform="gitlab",
            default_branch="main",
        )
        project.repositories.add(r)
        repos.append(r)
    return repos


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConversationRuntimeCodingPlanPayload:
    """work item — runtime payload 含 coding_plan 字段。"""

    async def test_no_plan_returns_none(self, conversation_for_runtime) -> None:
        """对话没有 CodingPlan → coding_plan=None。"""
        from chat.conversation_service import ConversationService

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )
        assert "coding_plan" in runtime
        assert runtime["coding_plan"] is None

    async def test_plan_zero_sessions(
        self, conversation_for_runtime, coding_plan_for_runtime
    ) -> None:
        """有 plan + 0 sessions → coding_plan.sessions=[]。"""
        from chat.conversation_service import ConversationService

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )
        assert runtime["coding_plan"] is not None
        assert runtime["coding_plan"]["plan_id"] == str(coding_plan_for_runtime.id)
        assert runtime["coding_plan"]["title"] == coding_plan_for_runtime.title
        assert runtime["coding_plan"]["sessions"] == []

    async def test_plan_feishu_fields_empty_when_not_exported(
        self, conversation_for_runtime, coding_plan_for_runtime
    ) -> None:
        """未导出 plan → coding_plan.feishu_doc_token / feishu_doc_url 为空字符串。"""
        from chat.conversation_service import ConversationService

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )
        assert runtime["coding_plan"]["feishu_doc_token"] == ""
        assert runtime["coding_plan"]["feishu_doc_url"] == ""

    async def test_plan_feishu_fields_present_when_exported(
        self, conversation_for_runtime
    ) -> None:
        """已导出 plan → runtime.coding_plan 携带非空 feishu_doc_token / feishu_doc_url。"""
        from asgiref.sync import sync_to_async

        from chat.conversation_service import ConversationService
        from chat.models import CodingPlan

        await sync_to_async(CodingPlan.objects.create)(
            conversation=conversation_for_runtime,
            tech_plan="## 已导出方案",
            affected_files=[],
            title="已导出 work item",
            feishu_doc_token="doctoken123",
            feishu_doc_url="https://feishu.cn/docx/doctoken123",
        )

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )
        assert runtime["coding_plan"]["feishu_doc_token"] == "doctoken123"
        assert (
            runtime["coding_plan"]["feishu_doc_url"]
            == "https://feishu.cn/docx/doctoken123"
        )

    async def test_plan_with_three_sessions_various_status(
        self,
        conversation_for_runtime,
        coding_plan_for_runtime,
        three_repos_for_runtime,
    ) -> None:
        """3 个 sessions 各种状态 → 字段齐全 + 状态枚举正确。"""
        from asgiref.sync import sync_to_async

        from chat.conversation_service import ConversationService
        from chat.models import CodingSession

        repo_a, repo_b, repo_c = three_repos_for_runtime
        await sync_to_async(CodingSession.objects.create)(
            conversation=conversation_for_runtime,
            coding_plan=coding_plan_for_runtime,
            repository=repo_a,
            tech_plan="x",
            status=CodingSession.Status.RUNNING,
            branch_name="feat/a",
        )
        await sync_to_async(CodingSession.objects.create)(
            conversation=conversation_for_runtime,
            coding_plan=coding_plan_for_runtime,
            repository=repo_b,
            tech_plan="x",
            status=CodingSession.Status.COMPLETED,
            pr_url="https://gitlab.com/test/beta/-/merge_requests/1",
            branch_name="feat/b",
        )
        await sync_to_async(CodingSession.objects.create)(
            conversation=conversation_for_runtime,
            coding_plan=coding_plan_for_runtime,
            repository=repo_c,
            tech_plan="x",
            status=CodingSession.Status.FAILED,
            error_message="Runner 离线",
            branch_name="feat/c",
        )

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )
        sessions = runtime["coding_plan"]["sessions"]
        assert len(sessions) == 3

        # 8 字段齐全
        required_fields = {
            "session_id",
            "repository_id",
            "repository_name",
            "branch_name",
            "status",
            "pr_url",
            "commit_sha",
            "error_message",
        }
        for s in sessions:
            assert required_fields <= set(s.keys())

        statuses = {s["status"] for s in sessions}
        assert {"running", "completed", "failed"} == statuses

        completed = next(s for s in sessions if s["status"] == "completed")
        assert completed["pr_url"] == "https://gitlab.com/test/beta/-/merge_requests/1"

        failed = next(s for s in sessions if s["status"] == "failed")
        assert failed["error_message"] == "Runner 离线"

    async def test_confirmed_session_is_active_coding_runtime(
        self,
        conversation_for_runtime,
        coding_plan_for_runtime,
        three_repos_for_runtime,
    ) -> None:
        """confirmed 但尚未 running 的编码会话仍应作为 coding runtime 返回。"""
        from asgiref.sync import sync_to_async

        from chat.conversation_service import ConversationService
        from chat.models import CodingSession

        repo = three_repos_for_runtime[0]
        session = await sync_to_async(CodingSession.objects.create)(
            conversation=conversation_for_runtime,
            coding_plan=coding_plan_for_runtime,
            repository=repo,
            tech_plan="x",
            status=CodingSession.Status.CONFIRMED,
            branch_name="feat/confirmed",
        )

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )

        assert runtime["active"] is True
        assert runtime["mode"] == "coding"
        assert runtime["coding_session"]["id"] == str(session.id)
        assert runtime["coding_session"]["status"] == "confirmed"

    async def test_plan_session_with_subagent_without_task_result_does_not_sync_query(
        self,
        conversation_for_runtime,
        coding_plan_for_runtime,
        three_repos_for_runtime,
        project,
    ) -> None:
        """SubAgentSession 尚未写 TaskResult 时，runtime sessions 仍可 async-safe 渲染。"""
        from asgiref.sync import sync_to_async

        from agents.models import AgentSession
        from chat.conversation_service import ConversationService
        from chat.models import CodingSession
        from subagent.models import SubAgentSession

        repo = three_repos_for_runtime[0]
        agent_session = await sync_to_async(AgentSession.objects.create)(
            session_id="agent-runtime-no-result",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await sync_to_async(SubAgentSession.objects.create)(
            session_id="coding-runtime-no-result",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.CODING,
            status=SubAgentSession.Status.PENDING,
            repo_url=repo.git_url,
        )
        await sync_to_async(CodingSession.objects.create)(
            conversation=conversation_for_runtime,
            coding_plan=coding_plan_for_runtime,
            repository=repo,
            subagent_session=sub_session,
            tech_plan="x",
            status=CodingSession.Status.RUNNING,
            branch_name="feat/no-result",
        )

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )

        session = runtime["coding_plan"]["sessions"][0]
        assert session["commit_sha"] == ""
        assert session["status"] == "running"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConversationRuntimeDeepSessions:
    """每个深度分析子会话各自独立的日志（runtime.deep_sessions）。"""

    async def test_multiple_deep_sessions_independent_logs(
        self, conversation_for_runtime, project
    ) -> None:
        """两个并行深度分析 → deep_sessions 两条，logs 各自独立、按 id 升序。"""
        from asgiref.sync import sync_to_async

        from agents.models import AgentSession
        from chat.conversation_service import ConversationService
        from subagent.models import SubAgentSession

        conv_id = str(conversation_for_runtime.id)

        async def _make(sid: str, task: str, logs: list) -> None:
            agent = await sync_to_async(AgentSession.objects.create)(
                session_id=f"agent-{sid}",
                space=project,
                status=AgentSession.Status.COMPLETED,
                metadata={"source": "chat_deep_analysis", "conversation_id": conv_id},
            )
            await sync_to_async(SubAgentSession.objects.create)(
                session_id=sid,
                main_session=agent,
                task_type=SubAgentSession.TaskType.EXPLORE,
                status=SubAgentSession.Status.COMPLETED,
                last_output={
                    "source": "chat_deep_analysis",
                    "task_description": task,
                    "logs": logs,
                },
            )

        await _make("deep-aaa111", "分析 A 仓库", [
            {"type": "tool_call", "content": "Read({\"file_path\": \"a.py\"})", "ts": 1},
        ])
        await _make("deep-bbb222", "分析 B 仓库", [
            {"type": "text", "content": "[思考] 分析 B", "ts": 2},
            {"type": "result", "content": "cost=$0.01", "ts": 3},
        ])

        runtime = await ConversationService.get_conversation_runtime(conv_id)

        deep = runtime["deep_sessions"]
        assert len(deep) == 2
        by_id = {d["session_id"]: d for d in deep}
        assert by_id["deep-aaa111"]["task_description"] == "分析 A 仓库"
        assert len(by_id["deep-aaa111"]["logs"]) == 1
        assert len(by_id["deep-bbb222"]["logs"]) == 2
        # 升序：先创建的（pk 更小）排在前，与工具调用出现顺序一致
        assert deep[0]["session_id"] == "deep-aaa111"
        # 向后兼容字段保留（= 最新一个）
        assert runtime["session_id"] == "deep-bbb222"

    async def test_no_deep_sessions_returns_empty_list(
        self, conversation_for_runtime
    ) -> None:
        """没有任何深度分析子会话 → deep_sessions 为空列表。"""
        from chat.conversation_service import ConversationService

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation_for_runtime.id)
        )
        assert runtime["deep_sessions"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConversationRuntimePendingClarification:
    """waiting_clarification 时 runtime 返回 pending_clarification（刷新可恢复卡片）。"""

    async def _make_run(self, conv, phase, status):
        from asgiref.sync import sync_to_async

        from orchestration.models import OrchestrationRun

        return await sync_to_async(OrchestrationRun.objects.create)(
            conversation=conv,
            thread_id=str(conv.id),
            status=status,
            phase=phase,
        )

    async def _make_trace(self, conv, *, answered: bool):
        from asgiref.sync import sync_to_async
        from django.utils import timezone

        from chat.models import ConversationIntentTrace

        return await sync_to_async(ConversationIntentTrace.objects.create)(
            conversation=conv,
            clarification_id="clar-abc123",
            question="选 A 还是 B？",
            options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            answered_at=timezone.now() if answered else None,
        )

    async def test_waiting_clarification_returns_pending(self, conversation_for_runtime) -> None:
        from chat.conversation_service import ConversationService
        from orchestration.models import OrchestrationRun

        conv = conversation_for_runtime
        await self._make_run(
            conv,
            OrchestrationRun.Phase.WAITING_CLARIFICATION,
            OrchestrationRun.Status.WAITING,
        )
        await self._make_trace(conv, answered=False)

        runtime = await ConversationService.get_conversation_runtime(str(conv.id))
        pc = runtime["pending_clarification"]
        assert pc is not None
        assert pc["clarification_id"] == "clar-abc123"
        assert pc["question"] == "选 A 还是 B？"
        assert len(pc["options"]) == 2
        assert pc["allow_freeform"] is True

    async def test_answered_trace_not_returned(self, conversation_for_runtime) -> None:
        from chat.conversation_service import ConversationService
        from orchestration.models import OrchestrationRun

        conv = conversation_for_runtime
        await self._make_run(
            conv,
            OrchestrationRun.Phase.WAITING_CLARIFICATION,
            OrchestrationRun.Status.WAITING,
        )
        await self._make_trace(conv, answered=True)

        runtime = await ConversationService.get_conversation_runtime(str(conv.id))
        assert runtime["pending_clarification"] is None

    async def test_completed_run_does_not_resurrect_stale_clarification(
        self, conversation_for_runtime
    ) -> None:
        """历史会话：run 已完成但残留未回答 trace（旧版强制澄清被绕过）→ 不复活卡片。"""
        from chat.conversation_service import ConversationService
        from orchestration.models import OrchestrationRun

        conv = conversation_for_runtime
        await self._make_run(
            conv,
            OrchestrationRun.Phase.COMPLETED,
            OrchestrationRun.Status.COMPLETED,
        )
        await self._make_trace(conv, answered=False)

        runtime = await ConversationService.get_conversation_runtime(str(conv.id))
        assert runtime["pending_clarification"] is None


def test_runtime_serializer_includes_deep_sessions() -> None:
    """ConversationRuntimeSerializer 透传 deep_sessions 嵌套字段（含 logs）。"""
    from chat.serializers import ConversationRuntimeSerializer

    payload = {
        "conversation_id": "a7c0e3b1-8d4f-4e2b-9c6d-1f3e5a7b9c0d",
        "active": True,
        "deep_sessions": [
            {
                "session_id": "deep-x",
                "task_description": "分析入口",
                "status": "RUNNING",
                "progress_percent": None,
                "logs": [{"type": "text", "content": "hi", "ts": 1}],
            },
        ],
    }
    out = ConversationRuntimeSerializer(payload).data
    assert "deep_sessions" in out
    assert out["deep_sessions"][0]["session_id"] == "deep-x"
    assert out["deep_sessions"][0]["logs"][0]["content"] == "hi"


@pytest.mark.django_db(transaction=True)
def test_runtime_coding_plan_query_budget_no_n_plus_1(
    conversation_for_runtime,
    coding_plan_for_runtime,
    three_repos_for_runtime,
) -> None:
    """work item — 3 session 时 runtime 总 SQL ≤ 12（防 per-session 单独查 repository）。

    Open Question #4 决议：`CaptureQueriesContext` 在 async 测试函数内嵌
    ``sync_to_async`` 触发 "Single thread executor already being used, would
    deadlock"。改用 ``async_to_sync`` 在同步 fixture 内调度 async service，
    捕获查询数。
    """
    from asgiref.sync import async_to_sync
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from chat.conversation_service import ConversationService
    from chat.models import CodingSession

    for r in three_repos_for_runtime:
        CodingSession.objects.create(
            conversation=conversation_for_runtime,
            coding_plan=coding_plan_for_runtime,
            repository=r,
            tech_plan="x",
            status=CodingSession.Status.RUNNING,
        )

    with CaptureQueriesContext(connection) as ctx:
        async_to_sync(ConversationService.get_conversation_runtime)(
            str(conversation_for_runtime.id)
        )

    total_queries = len(ctx.captured_queries)
    assert total_queries <= 12, f"Query budget 超限: {total_queries} 次 SQL"
