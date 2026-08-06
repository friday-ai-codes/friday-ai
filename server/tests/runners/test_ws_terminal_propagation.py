"""Runner WS 终态路径的容器链传播回归测试。

复现 2026-08-05 线上事故：蓝图调研容器失败经 **WS** 送达（`task_failed_via_ws`），
WS 路径只翻 SubAgentSession 终态、缺四条容器链的失败/完成传播；后续投递又被
终态守卫拦掉 —— `RepoResearchTask` 永远停在 running、fan-out 屏障永不触发，
收敛会话 waiting_event 卡死在 repo_research。

守三件事：
1. ⭐ WS failed → blueprint_research 的 RepoResearchTask 翻 FAILED + emit failed 事件。
2. ⭐ WS completed → 四条链完成钩子按 HTTP 路径同款 gating 被调用。
3. 任一链钩子异常 swallow，WS 消息处理不被打断。
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from runners.consumers import RunnerConsumer
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


async def _setup(*, source: str = "blueprint_research"):
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://example.com/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session,
        repository=repo,
        status=RepoResearchTaskStatus.RUNNING,
        routed_confidence="high",
    )
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    sub = await SubAgentSession.objects.acreate(
        session_id=f"bp-research-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "source": source,
            "blueprint_session_id": str(session.id),
            "research_task_id": str(task.id),
            "repository_id": str(repo.id),
        },
    )
    return session, repo, task, sub


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


def _enter_common_patches(stack: ExitStack) -> None:
    """隔离通知/续驱/token 等旁路副作用（每个测试各起一套新 patcher）。"""
    stack.enter_context(
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock)
    )
    stack.enter_context(
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock)
    )
    stack.enter_context(
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock)
    )
    stack.enter_context(patch("subagent.api.callbacks._schedule_workflow_resume"))
    stack.enter_context(patch("subagent.api.callbacks._schedule_agent_session_resume"))
    stack.enter_context(patch("access_tokens.services.arevoke_task_tokens", new_callable=AsyncMock))


async def test_ws_failed_marks_blueprint_research_task_failed() -> None:
    """⭐ WS 失败路径 → RepoResearchTask FAILED + blueprint.repo_research.failed 事件。

    与 HTTP `_handle_failed` 的同名断言逐字对齐（test_blueprint_research_callback.py）
    —— 两条送达路径必须行为对称，这正是 2026-08-05 卡死事故缺的那一半。
    """
    from delivery.services.event_taxonomy import EVENT_BLUEPRINT_REPO_RESEARCH_FAILED

    _s, _r, task, sub = await _setup()
    emitted: list[tuple] = []

    async def _spy(self, event, session, payload):  # noqa: ANN001
        emitted.append((event, payload))

    with ExitStack() as stack:
        _enter_common_patches(stack)
        stack.enter_context(
            patch(
                "delivery.services.convergence_session_service.ConvergenceSessionService._emit_event",
                new=_spy,
            )
        )
        await RunnerConsumer()._handle_failed(
            {
                "task_id": sub.session_id,
                "error": "Error during workspace: Explore 模式结束后工作区存在未提交变更",
            },
            _log(),
        )

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "container_failed"
    assert emitted, "WS 失败路径必须 emit 蓝图调研失败事件"
    assert emitted[0][0] == EVENT_BLUEPRINT_REPO_RESEARCH_FAILED

    await sub.arefresh_from_db()
    assert sub.status == SubAgentSession.Status.ERROR


async def test_ws_completed_invokes_completion_handlers_with_gating() -> None:
    """⭐ WS 完成路径按 HTTP 同款 gating 调四条链完成钩子。

    blueprint_research 会话：plan_research / repo_verify 钩子无条件调用（内部自
    gating），blueprint_research 钩子经 `_is_blueprint_research` 命中调用，
    blueprint_repo_plan 钩子经 `_is_blueprint_repo_plan` 未命中不调用。
    """
    _s, _r, _t, sub = await _setup()

    research = AsyncMock()
    verify = AsyncMock()
    bp_research = AsyncMock()
    bp_plan = AsyncMock()

    with ExitStack() as stack:
        _enter_common_patches(stack)
        stack.enter_context(
            patch("subagent.api.callbacks._handle_research_completion", new=research)
        )
        stack.enter_context(
            patch("subagent.api.callbacks._handle_repo_verify_completion", new=verify)
        )
        stack.enter_context(
            patch("subagent.api.callbacks._handle_blueprint_research_completion", new=bp_research)
        )
        stack.enter_context(
            patch("subagent.api.callbacks._handle_blueprint_repo_plan_completion", new=bp_plan)
        )
        await RunnerConsumer()._handle_completed(
            {"task_id": sub.session_id, "result_type": "text", "output": {"text": "done"}},
            _log(),
        )

    research.assert_awaited_once()
    verify.assert_awaited_once()
    bp_research.assert_awaited_once()
    bp_plan.assert_not_awaited()

    await sub.arefresh_from_db()
    assert sub.status == SubAgentSession.Status.COMPLETED


async def test_ws_failed_handler_exception_swallowed() -> None:
    """任一链失败钩子抛异常 → swallow，WS 处理不中断、会话仍翻终态。"""
    _s, _r, _t, sub = await _setup()

    async def _boom(*a, **kw):
        raise RuntimeError("downstream failure")

    with ExitStack() as stack:
        _enter_common_patches(stack)
        stack.enter_context(
            patch("subagent.api.callbacks._handle_blueprint_research_failure", new=_boom)
        )
        await RunnerConsumer()._handle_failed(
            {"task_id": sub.session_id, "error": "boom"},
            _log(),
        )

    await sub.arefresh_from_db()
    assert sub.status == SubAgentSession.Status.ERROR
