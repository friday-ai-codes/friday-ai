"""plan_research 容器回调 → PartialPlan 落库 + §15 事件 + barrier 测试（Phase 39-04）。

**真实容器 E2E DEFERRED**：全程 mock payload（mirror test_callbacks_cross_repo_relevance），
覆盖结构化/降级 partial 落库 + repo.research.completed / 空结果 mark_failed +
repo.research.failed / 所有终态触发 research_complete / 非 plan_research 不触发 /
回调异常 swallow 返 200。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from delivery.models import (
    PartialPlan,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


async def _setup(last_output_extra: dict | None = None, status=PlanSessionStatus.RESEARCHING):
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    plan_session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=status
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
        patch("delivery.services.PlanSessionService._emit_event", new=emit_spy),
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
    assert plan_session.status == PlanSessionStatus.MERGING


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
        patch("delivery.services.PlanSessionService._emit_event", new=emit_spy),
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
    assert plan_session.status == PlanSessionStatus.MERGING


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
        patch("delivery.services.PlanSessionService._emit_event", new=emit_spy),
    ):
        resp = await _handle_failed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "container_failed"
    failed = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "repo.research.failed"]
    assert len(failed) == 1
    await plan_session.arefresh_from_db()
    assert plan_session.status == PlanSessionStatus.MERGING
