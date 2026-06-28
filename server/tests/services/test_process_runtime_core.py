"""ProcessEngine / ConvergenceSessionService 核心单测（Chassis v2 · P2）。

覆盖 P2 验收点：
- echo process_type 走通不同 stage graph（draft → __done__，产 echo ArtifactVersion）——
  证明同一 ``ProcessEngine`` 可跑完全异构的 stage 图（泛化）。
- ``ConvergenceSessionService.transition`` CAS + stage 转移（合法/非法/并发拒绝）。
- 终态 fail 幂等 no-op。
"""

from __future__ import annotations

import pytest

from delivery.models import (
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ConcurrentTransitionError, ConvergenceSessionService
from services.process_runtime import ProcessEngine

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_echo_process_runs_through_distinct_stage_graph() -> None:
    """echo process（draft → __done__）跑通并产 echo ArtifactVersion（stage graph 可泛化）。"""
    svc = ConvergenceSessionService()
    session = await svc.create_session(
        "echo",
        ConvergenceSessionEntrypoint.TOOL_INVOKE,
        stage_state={"echo_input": {"message": "hello chassis"}},
    )
    assert session.process_type == "echo"
    assert session.current_stage == "draft"
    assert session.status == ConvergenceSessionStatus.CREATED

    engine = ProcessEngine(session_service=svc, deps=None)
    await engine.advance(session)
    session = await ConvergenceSession.objects.aget(id=session.id)

    assert session.status == ConvergenceSessionStatus.DONE
    assert session.current_artifact_version_id is not None
    av = await ArtifactVersion.objects.select_related("artifact").aget(
        id=session.current_artifact_version_id
    )
    assert av.content == {"message": "hello chassis"}
    assert av.artifact.artifact_type == "echo"


@pytest.mark.asyncio
async def test_transition_illegal_event_raises_and_keeps_state() -> None:
    """非法 event（不在当前 stage transitions）→ ValueError，stage/status 不变。"""
    svc = ConvergenceSessionService()
    session = await svc.create_session("echo", ConvergenceSessionEntrypoint.TOOL_INVOKE)
    with pytest.raises(ValueError):
        await svc.transition(session, "nonexistent_event")
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "draft"
    assert fresh.status == ConvergenceSessionStatus.CREATED


@pytest.mark.asyncio
async def test_transition_cas_rejects_stale_from_stage() -> None:
    """CAS：内存态 current_stage 与 DB 不一致（被并发推进）→ ConcurrentTransitionError。"""
    svc = ConvergenceSessionService()
    # 用 technical_plan：decompose --decomposed--> route 合法转移。
    session = await svc.create_session(
        "technical_plan",
        ConvergenceSessionEntrypoint.WORKFLOW,
        stage_state={"decomposition": {"requirement_text": "x", "include_repos": []}},
    )
    # 模拟并发：DB 行已被推进到 route，但内存 session 仍认为在 decompose。
    await ConvergenceSession.objects.filter(id=session.id).aupdate(current_stage="route")
    # 内存 session.current_stage 仍是 decompose → CAS filter(current_stage="decompose") 命中 0 行。
    with pytest.raises(ConcurrentTransitionError):
        await svc.transition(session, "decomposed")


@pytest.mark.asyncio
async def test_fail_is_idempotent_noop_on_terminal() -> None:
    """已 done 的会话再 fail 为幂等 no-op（保留终态，不回落 failed）。"""
    svc = ConvergenceSessionService()
    session = await svc.create_session("echo", ConvergenceSessionEntrypoint.TOOL_INVOKE)
    engine = ProcessEngine(session_service=svc, deps=None)
    await engine.advance(session)
    session = await ConvergenceSession.objects.aget(id=session.id)
    assert session.status == ConvergenceSessionStatus.DONE

    await svc.transition(session, "fail", error={"reason": "should_be_ignored"})
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.DONE
    assert fresh.error == {}


@pytest.mark.asyncio
async def test_forward_transition_sets_running_and_advances_stage() -> None:
    """合法 forward 转移：current_stage 推进 + status=running。"""
    svc = ConvergenceSessionService()
    session = await svc.create_session(
        "technical_plan",
        ConvergenceSessionEntrypoint.WORKFLOW,
        stage_state={"decomposition": {"requirement_text": "x", "include_repos": []}},
    )
    await svc.transition(session, "decomposed", stage_state={"decomposition": {"segments": []}})
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "route"
    assert fresh.status == ConvergenceSessionStatus.RUNNING
