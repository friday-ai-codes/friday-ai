"""plan_research 容器回调 → PartialPlan 落库 + §15 事件 + barrier 测试（Phase 39-04）。

**真实容器 E2E DEFERRED**：全程 mock payload（mirror test_callbacks_cross_repo_relevance），
覆盖结构化/降级 partial 落库 + repo.research.completed / 空结果 mark_failed +
repo.research.failed / 所有终态触发 research_complete / 非 plan_research 不触发 /
回调异常 swallow 返 200。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.models import AgentSession
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


async def _setup(
    last_output_extra: dict | None = None,
    current_stage="research",
    entrypoint=ConvergenceSessionEntrypoint.CHAT,
):
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    plan_session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=entrypoint,
        current_stage=current_stage,
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    task = await RepoResearchTask.objects.acreate(
        session=plan_session, repository=repo, status=RepoResearchTaskStatus.RUNNING
    )
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    last_output = {
        "source": "plan_research",
        "plan_session_id": str(plan_session.id),
        "research_task_id": str(task.id),
        "repository_id": str(repo.id),
    }
    if last_output_extra:
        last_output.update(last_output_extra)
    sub = await SubAgentSession.objects.acreate(
        session_id=f"research-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output=last_output,
    )
    return repo, plan_session, task, sub


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


_PATCHES = (
    patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
    patch("subagent.api.callbacks._schedule_workflow_resume"),
    patch("subagent.api.callbacks._schedule_agent_session_resume"),
)


@pytest.mark.asyncio
async def test_structured_partial_recorded_and_completed_event() -> None:
    """结构化 §7 输出 → PartialPlan 落库 + task done + repo.research.completed + barrier→merging。"""
    repo, plan_session, task, sub = await _setup()
    payload = {
        "result_type": "text",
        "output": {
            "research_summary": "改鉴权",
            "candidate_files": ["auth.py"],
            "api_contracts_exposed": [{"name": "verify"}],
            "proposed_changes": [{"file": "auth.py"}],
        },
    }
    from subagent.api.callbacks import _handle_completed

    emit_spy = AsyncMock()
    with (
        _PATCHES[0], _PATCHES[1], _PATCHES[2],
        patch("delivery.services.ConvergenceSessionService._emit_event", new=emit_spy),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE
    partial = await PartialPlan.objects.aget(research_task=task)
    assert partial.valid is True
    assert partial.content["candidate_files"] == ["auth.py"]
    # repo.research.completed 事件
    completed = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "repo.research.completed"]
    assert len(completed) == 1
    assert completed[0].args[2]["repo_id"] == str(repo.id)
    # barrier：唯一 task done → research_complete → merging
    await plan_session.arefresh_from_db()
    assert plan_session.current_stage == "merge"


@pytest.mark.asyncio
async def test_free_text_degrades_to_partial() -> None:
    """自由文本 → 优雅降级 file 级摘要 partial（不 mark_failed）。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"text": "一段非结构化分析结论"}}
    from subagent.api.callbacks import _handle_completed

    with (_PATCHES[0], _PATCHES[1], _PATCHES[2]):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE
    partial = await PartialPlan.objects.aget(research_task=task)
    assert partial.content["research_summary"] == "一段非结构化分析结论"


@pytest.mark.asyncio
async def test_empty_result_marks_failed_and_failed_event() -> None:
    """空结果 → mark_failed + repo.research.failed + barrier（failed 也终态）。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"result_type": "text", "output": {}}
    from subagent.api.callbacks import _handle_completed

    emit_spy = AsyncMock()
    with (
        _PATCHES[0], _PATCHES[1], _PATCHES[2],
        patch("delivery.services.ConvergenceSessionService._emit_event", new=emit_spy),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "empty_or_unparseable_result"
    failed = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "repo.research.failed"]
    assert len(failed) == 1
    # failed 也是 barrier 终态 → merging
    await plan_session.arefresh_from_db()
    assert plan_session.current_stage == "merge"


@pytest.mark.asyncio
async def test_non_plan_research_does_not_trigger() -> None:
    """非 plan_research（source 不符）→ 不建 partial、不改 task。"""
    repo, plan_session, task, sub = await _setup(last_output_extra={"source": "other"})
    payload = {"result_type": "text", "output": {"research_summary": "x"}}
    from subagent.api.callbacks import _handle_completed

    with (_PATCHES[0], _PATCHES[1], _PATCHES[2]):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.RUNNING
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


@pytest.mark.asyncio
async def test_completion_exception_swallowed_returns_200() -> None:
    """research 完成 helper 异常 → swallow，回调返 200。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"research_summary": "x"}}
    from subagent.api.callbacks import _handle_completed

    async def _boom(*a, **kw):
        raise RuntimeError("downstream failure")

    with (
        _PATCHES[0], _PATCHES[1], _PATCHES[2],
        patch("subagent.api.callbacks._handle_research_completion", new=_boom),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_plan_research_callback_does_not_resume_agent_session() -> None:
    """CR-01：plan_research 容器完成回调**不得**触发 SDKAgentRunner resume 合成 AgentSession，
    只走 _handle_research_completion（research 完成处理）驱动 barrier。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"research_summary": "改鉴权"}}
    from subagent.api.callbacks import _handle_completed

    resume_spy = MagicMock()
    research_spy = AsyncMock()
    with (
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        # 不 patch _schedule_agent_session_resume —— 验证真实短路逻辑
        patch("tasks.agent_tasks.schedule_resume_agent_session", new=resume_spy),
        patch("subagent.api.callbacks._handle_research_completion", new=research_spy),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    # 关键断言：合成 AgentSession 绝不被 resume（否则拉起幽灵 agent 执行）
    resume_spy.assert_not_called()
    # research 完成处理被调用（正确路径）
    research_spy.assert_awaited_once()


@pytest.mark.asyncio
async def test_plan_research_failed_callback_does_not_resume_agent_session() -> None:
    """CR-01：plan_research 容器失败回调同样不得触发 agent resume，只走 research 失败处理。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"error": "容器超时"}
    from subagent.api.callbacks import _handle_failed

    resume_spy = MagicMock()
    research_fail_spy = AsyncMock()
    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("tasks.agent_tasks.schedule_resume_agent_session", new=resume_spy),
        patch("subagent.api.callbacks._handle_research_failure", new=research_fail_spy),
    ):
        resp = await _handle_failed(sub, payload, _log())

    assert resp.status_code == 200
    resume_spy.assert_not_called()
    research_fail_spy.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_callback_marks_task_failed() -> None:
    """plan_research 容器失败回调 → task failed + repo.research.failed + barrier。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"error": "容器超时"}
    from subagent.api.callbacks import _handle_failed

    emit_spy = AsyncMock()
    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
        patch("delivery.services.ConvergenceSessionService._emit_event", new=emit_spy),
    ):
        resp = await _handle_failed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "container_failed"
    failed = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "repo.research.failed"]
    assert len(failed) == 1
    await plan_session.arefresh_from_db()
    assert plan_session.current_stage == "merge"


# === RESUME-01（43-03）：chat 入口续驱 + barrier 回灌闭环 / 回归 / 幂等 / fail-soft / 失败路径 ===


async def _flush_pending() -> None:
    """flush fire-and-forget create_task（含嵌套调度）直到无 pending —— 在断言前等续驱完成。"""
    for _ in range(20):
        pending = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and not t.done()
        ]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _passing_engine() -> Any:
    """构造真实 engine，IO 边界 mock：research.dispatch no-op + merge validator 通过（→done）。

    research.dispatch mock 成 no-op：fire-and-forget 续驱可能在 researching（任务已终态但
    主流程 amaybe_complete_research 尚未把 session 推到 merging）的窗口运行，此时 engine 会
    经 _research 再走一次 amaybe_complete_research（幂等去重）推进——等价生产真实 adapter。
    """
    from types import SimpleNamespace

    from delivery.services import ConvergenceSessionService
    from services.process_runtime import ProcessEngine

    research = AsyncMock()
    research.dispatch = AsyncMock(return_value=None)
    merge = AsyncMock()
    merge.merge = AsyncMock(return_value={"validation_status": "passed"})
    return ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(research=research, merge=merge),
    )


def _failing_engine() -> Any:
    """构造真实 engine，research.dispatch no-op + merge 限次回退耗尽（merging→failed 终态）。"""
    from types import SimpleNamespace

    from delivery.services import ConvergenceSessionService
    from services.process_runtime import ProcessEngine

    research = AsyncMock()
    research.dispatch = AsyncMock(return_value=None)
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "failed", "attempt": 1, "report": {}}
    )
    return ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(research=research, merge=merge),
    )


@pytest.mark.asyncio
async def test_chat_resume_drives_to_done_and_notifies_barrier() -> None:
    """chat 入口唯一调研完成 → 续驱 PlanSession 到 done + barrier task_completed 回灌（D-2 a/b）。"""
    repo, plan_session, task, sub = await _setup()
    payload = {
        "result_type": "text",
        "output": {
            "research_summary": "改鉴权",
            "candidate_files": ["auth.py"],
            "proposed_changes": [{"file": "auth.py"}],
        },
    }
    from subagent.api.callbacks import _handle_completed

    barrier_mock = MagicMock()
    barrier_mock.task_completed = AsyncMock(return_value=True)

    with (
        _PATCHES[0],
        _PATCHES[1],  # 放开 _schedule_agent_session_resume —— 让真实分支委派跑
        patch(
            "services.process_runtime.build_orchestration_engine",
            return_value=_passing_engine(),
        ),
        patch("orchestration.barrier.get_barrier_manager", return_value=barrier_mock),
    ):
        resp = await _handle_completed(sub, payload, _log())
        await _flush_pending()

    assert resp.status_code == 200
    await plan_session.arefresh_from_db()
    assert plan_session.status == ConvergenceSessionStatus.DONE
    # barrier 回灌：task_id 用 str(plan_session.id)（Pitfall 3），success=True
    barrier_mock.task_completed.assert_awaited_once()
    call = barrier_mock.task_completed.await_args
    assert call.args[0] == str(plan_session.id)
    assert call.args[1]["task_id"] == str(plan_session.id)
    assert call.args[1]["task_type"] == "plan_research"
    assert call.args[1]["success"] is True


@pytest.mark.asyncio
async def test_workflow_entry_session_skips_chat_resume() -> None:
    """回归守护：工作流入口（有 node_execution）不走 chat 续驱，仍由 _schedule_workflow_resume 处理。"""
    from projects.models import Space
    from workflows.models import (
        NodeExecution,
        Workflow,
        WorkflowExecution,
        WorkflowNode,
    )

    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    plan_session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    task = await RepoResearchTask.objects.acreate(
        session=plan_session, repository=repo, status=RepoResearchTaskStatus.RUNNING
    )
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    project = await Space.objects.acreate(name=f"proj-{uuid.uuid4().hex[:6]}")
    workflow = await Workflow.objects.acreate(name="编排工作流", space=project)
    wf_node = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="ai_plan_research", name="AI 方案编排"
    )
    wf_exec = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=project, trigger_type="manual"
    )
    node_exec = await NodeExecution.objects.acreate(
        workflow_execution=wf_exec, node=wf_node, status="running"
    )
    sub = await SubAgentSession.objects.acreate(
        session_id=f"research-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        node_execution=node_exec,
        last_output={
            "source": "plan_research",
            "plan_session_id": str(plan_session.id),
            "research_task_id": str(task.id),
            "repository_id": str(repo.id),
        },
    )
    payload = {"result_type": "text", "output": {"research_summary": "x"}}
    from subagent.api.callbacks import _handle_completed

    wf_spy = MagicMock()
    chat_spy = MagicMock()
    with (
        _PATCHES[0],
        patch("subagent.api.callbacks._schedule_workflow_resume", new=wf_spy),
        patch("subagent.api.callbacks._schedule_chat_plan_resume", new=chat_spy),
    ):
        resp = await _handle_completed(sub, payload, _log())
        await _flush_pending()

    assert resp.status_code == 200
    # 工作流入口经 node_execution 顶部短路 → 绝不走 chat 续驱，仍由 workflow resume 接管
    chat_spy.assert_not_called()
    wf_spy.assert_called_once()


@pytest.mark.asyncio
async def test_chat_resume_guards_non_chat_entrypoint() -> None:
    """T-43-TAMPER：守门用服务端权威字段 entrypoint —— 非 chat（workflow）入口绝不续驱。"""
    repo, plan_session, task, sub = await _setup(
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW
    )
    payload = {"result_type": "text", "output": {"research_summary": "改鉴权"}}
    from subagent.api.callbacks import _handle_completed

    barrier_mock = MagicMock()
    barrier_mock.task_completed = AsyncMock(return_value=True)
    engine_spy = MagicMock()
    with (
        _PATCHES[0],
        _PATCHES[1],
        patch("services.process_runtime.build_orchestration_engine", new=engine_spy),
        patch("orchestration.barrier.get_barrier_manager", return_value=barrier_mock),
    ):
        resp = await _handle_completed(sub, payload, _log())
        await _flush_pending()

    assert resp.status_code == 200
    # entrypoint 守门命中 → 绝不构建 engine、绝不 notify barrier（不放大信任面）
    engine_spy.assert_not_called()
    barrier_mock.task_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_resume_idempotent_when_research_in_flight() -> None:
    """幂等：多仓其一仍在途 → 不续驱、不 notify（aall_research_tasks_terminal 短路）。"""
    repo, plan_session, task, sub = await _setup()
    repo2 = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    await RepoResearchTask.objects.acreate(
        session=plan_session, repository=repo2, status=RepoResearchTaskStatus.RUNNING
    )
    payload = {"result_type": "text", "output": {"research_summary": "改鉴权"}}
    from subagent.api.callbacks import _handle_completed

    barrier_mock = MagicMock()
    barrier_mock.task_completed = AsyncMock(return_value=True)
    engine_spy = MagicMock()
    with (
        _PATCHES[0],
        _PATCHES[1],
        patch("services.process_runtime.build_orchestration_engine", new=engine_spy),
        patch("orchestration.barrier.get_barrier_manager", return_value=barrier_mock),
    ):
        resp = await _handle_completed(sub, payload, _log())
        await _flush_pending()

    assert resp.status_code == 200
    # 仍有在途调研 → 短路，不续驱、不 notify；session 留在 researching 等下次回调
    engine_spy.assert_not_called()
    barrier_mock.task_completed.assert_not_awaited()
    await plan_session.arefresh_from_db()
    assert plan_session.current_stage == "research"


@pytest.mark.asyncio
async def test_chat_resume_swallows_internal_error_returns_200() -> None:
    """fail-soft：续驱内部抛异常 → swallow，_handle_completed 仍返 200。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"research_summary": "改鉴权"}}
    from subagent.api.callbacks import _handle_completed

    async def _boom_drive(*a, **kw):
        raise RuntimeError("drive failure")

    with (
        _PATCHES[0],
        _PATCHES[1],
        patch(
            "services.process_runtime.build_orchestration_engine",
            return_value=MagicMock(),
        ),
        patch(
            "services.process_runtime.adrive_convergence_session_to_pause_or_terminal",
            new=_boom_drive,
        ),
    ):
        resp = await _handle_completed(sub, payload, _log())
        await _flush_pending()

    # 续驱协程异常被 _resume 内 try/except swallow，回调主流程不受影响
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chat_resume_failed_research_notifies_barrier_success_false() -> None:
    """失败路径：plan_research 容器 failed → 续驱到 failed 终态 + barrier success=False 不卡死。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"error": "容器超时"}
    from subagent.api.callbacks import _handle_failed

    barrier_mock = MagicMock()
    barrier_mock.task_completed = AsyncMock(return_value=True)
    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch(
            "services.process_runtime.build_orchestration_engine",
            return_value=_failing_engine(),
        ),
        patch("orchestration.barrier.get_barrier_manager", return_value=barrier_mock),
    ):
        resp = await _handle_failed(sub, payload, _log())
        await _flush_pending()

    assert resp.status_code == 200
    # 容器失败 → 调研终态（FAILED）→ 续驱仍触发 barrier 回灌（不卡在 researching/merging）
    barrier_mock.task_completed.assert_awaited_once()
    call = barrier_mock.task_completed.await_args
    assert call.args[0] == str(plan_session.id)
    assert call.args[1]["success"] is False
    await plan_session.arefresh_from_db()
    assert plan_session.status == ConvergenceSessionStatus.FAILED


# === CR-01：续驱调度顺序回归（必须在 research 完成/失败处理之后调度，消除竞态） ===


@pytest.mark.asyncio
async def test_completed_schedules_resume_after_research_completion() -> None:
    """CR-01：_handle_completed 必须在 _handle_research_completion（翻终态 + researching→
    merging）之后才调度续驱。若在其之前调度（旧实现），fire-and-forget 的 _resume() 会在
    task 翻终态前读到非终态而短路 no-op，导致 chat 会话永久卡在 merging、barrier 永不被通知。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"research_summary": "改鉴权"}}
    from subagent.api.callbacks import _handle_completed

    order: list[str] = []

    async def _research(*a: Any, **kw: Any) -> None:
        order.append("research")

    def _resume(*a: Any, **kw: Any) -> None:
        order.append("resume")

    with (
        _PATCHES[0],
        patch("subagent.api.callbacks._schedule_workflow_resume", new=_resume),
        patch("subagent.api.callbacks._schedule_agent_session_resume", new=_resume),
        patch("subagent.api.callbacks._handle_research_completion", new=_research),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    # research 完成处理必须先于两处续驱调度
    assert order == ["research", "resume", "resume"]


@pytest.mark.asyncio
async def test_failed_schedules_resume_after_research_failure() -> None:
    """CR-01（失败路径对称）：_handle_failed 必须在 _handle_research_failure 之后才调度续驱。"""
    repo, plan_session, task, sub = await _setup()
    payload = {"error": "容器超时"}
    from subagent.api.callbacks import _handle_failed

    order: list[str] = []

    async def _research_fail(*a: Any, **kw: Any) -> None:
        order.append("research")

    def _resume(*a: Any, **kw: Any) -> None:
        order.append("resume")

    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume", new=_resume),
        patch("subagent.api.callbacks._schedule_agent_session_resume", new=_resume),
        patch("subagent.api.callbacks._handle_research_failure", new=_research_fail),
    ):
        resp = await _handle_failed(sub, payload, _log())

    assert resp.status_code == 200
    assert order == ["research", "resume", "resume"]


@pytest.mark.asyncio
async def test_chat_resume_drives_to_terminal_with_real_ordering() -> None:
    """CR-01 端到端：不 mock _handle_research_completion，让真实 research 完成处理把 task
    翻终态 + researching→merging 后再调度续驱；续驱必然 adrive 到 done 并 notify barrier
    （即使两条 fire-and-forget 协程都跑，最终也驱动到终态，不卡死）。"""
    repo, plan_session, task, sub = await _setup()
    payload = {
        "result_type": "text",
        "output": {
            "research_summary": "改鉴权",
            "candidate_files": ["auth.py"],
            "proposed_changes": [{"file": "auth.py"}],
        },
    }
    from subagent.api.callbacks import _handle_completed

    barrier_mock = MagicMock()
    barrier_mock.task_completed = AsyncMock(return_value=True)

    with (
        _PATCHES[0],
        _PATCHES[1],
        patch(
            "services.process_runtime.build_orchestration_engine",
            return_value=_passing_engine(),
        ),
        patch("orchestration.barrier.get_barrier_manager", return_value=barrier_mock),
    ):
        resp = await _handle_completed(sub, payload, _log())
        await _flush_pending()

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE
    await plan_session.arefresh_from_db()
    assert plan_session.status == ConvergenceSessionStatus.DONE
    barrier_mock.task_completed.assert_awaited_once()
    call = barrier_mock.task_completed.await_args
    assert call.args[0] == str(plan_session.id)
    assert call.args[1]["success"] is True
