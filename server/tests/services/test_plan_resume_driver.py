"""adrive_convergence_session_to_pause_or_terminal 共享续驱 helper 单测（RESUME-01 步骤 1）。

覆盖四条路径：
- 终态返回（DONE / advance 一步到 DONE）→ 返回 session，终态不再 advance。
- waiting_event 在途短路 → 立即返回原 session，engine.advance 未被调用。
- waiting_clarification 在途短路（BLOCKER 守护，保护澄清 HITL）→ 立即返回原 session，advance 未被调用。
- step 上限 fail → 超过 max_steps 后经 session_service.transition(session, "fail") 标记失败返回。

pytest-socket 禁网——全部 IO 在 ORM（真实 ConvergenceSession/RepoResearchTask/Clarification）+
engine MagicMock 边界。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from delivery.models import (
    Clarification,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from services.process_runtime import adrive_convergence_session_to_pause_or_terminal

pytestmark = pytest.mark.django_db(transaction=True)


def _engine() -> MagicMock:
    """engine MagicMock：advance / session_service.transition 为 AsyncMock。"""
    engine = MagicMock()
    engine.advance = AsyncMock()
    engine.session_service = MagicMock()
    engine.session_service.transition = AsyncMock()
    return engine


async def _make_session(
    status: ConvergenceSessionStatus, *, current_stage: str = "decompose"
) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=current_stage,
        status=status,
    )


@pytest.mark.asyncio
async def test_terminal_returns_without_advance() -> None:
    """session 已为 DONE → 直接返回，engine.advance 不被调用。"""
    session = await _make_session(ConvergenceSessionStatus.DONE)
    engine = _engine()

    result = await adrive_convergence_session_to_pause_or_terminal(engine, session)

    assert result.id == session.id
    engine.advance.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_advance_one_step_to_done() -> None:
    """advance 一步把 RUNNING → DONE → 返回该 session，advance 仅调用一次。"""
    session = await _make_session(ConvergenceSessionStatus.RUNNING, current_stage="merge")
    engine = _engine()

    async def _advance(_s: ConvergenceSession) -> None:
        await ConvergenceSession.objects.filter(id=session.id).aupdate(
            status=ConvergenceSessionStatus.DONE
        )

    engine.advance.side_effect = _advance

    result = await adrive_convergence_session_to_pause_or_terminal(engine, session)

    assert result.status == ConvergenceSessionStatus.DONE
    assert engine.advance.await_count == 1


@pytest.mark.asyncio
async def test_researching_pending_short_circuit() -> None:
    """waiting_event 且有 RUNNING 调研任务（在途）→ 立即返回，advance 未调用。"""
    repo = await Repository.objects.acreate(
        name="resume-research-repo",
        git_url="https://example.com/resume-research.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    session = await _make_session(
        ConvergenceSessionStatus.WAITING_EVENT, current_stage="research"
    )
    await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.RUNNING
    )
    engine = _engine()

    result = await adrive_convergence_session_to_pause_or_terminal(engine, session)

    assert result.id == session.id
    engine.advance.assert_not_awaited()


@pytest.mark.asyncio
async def test_clarifying_pending_short_circuit() -> None:
    """waiting_clarification 且有未答 Clarification（answered_at 为空）→ 立即返回，advance 未调用（保护 HITL）。"""
    session = await _make_session(
        ConvergenceSessionStatus.WAITING_CLARIFICATION, current_stage="clarify"
    )
    await Clarification.objects.acreate(
        session=session, question="需要澄清范围？", answered_at=None
    )
    engine = _engine()

    result = await adrive_convergence_session_to_pause_or_terminal(engine, session)

    assert result.id == session.id
    engine.advance.assert_not_awaited()


@pytest.mark.asyncio
async def test_step_limit_transitions_to_fail() -> None:
    """advance 永不改变 status（恒非终态、非短路）→ 超过 max_steps 经 transition(fail) 标记失败。"""
    session = await _make_session(ConvergenceSessionStatus.RUNNING, current_stage="route")
    engine = _engine()

    result = await adrive_convergence_session_to_pause_or_terminal(engine, session, max_steps=3)

    # max_steps=3：advance 调用 3 次（steps 1/2/3），第 4 步超限 → fail
    assert engine.advance.await_count == 3
    engine.session_service.transition.assert_awaited_once()
    call = engine.session_service.transition.await_args
    assert call.args[1] == "fail"
    assert call.kwargs["error"]["reason"] == "advance_step_limit"
    assert result.id == session.id
