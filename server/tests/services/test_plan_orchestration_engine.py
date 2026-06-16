"""PlanOrchestrationEngine 测试（ORCH-01）。

覆盖 advance(decomposing→routing 真实拆分) / 任意 status resume / 注入 mock 被调 /
engine 不直接写 status / 骨架 NotImplementedError 上抛 / 普通异常落 failed。
用真实 PlanSession + PlanSessionService，stage 依赖用 AsyncMock 注入。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from services.plan_orchestration import PlanOrchestrationEngine

ENGINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "plan_orchestration"
    / "engine.py"
)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_advance_from_decomposing_real_decompose() -> None:
    """decomposing → _decompose 真实执行（拆分结构）→ status=routing（经 transition）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.DECOMPOSING,
        decomposition={"requirement_text": "做A\n做B", "include_repos": ["r1"]},
    )
    engine = PlanOrchestrationEngine()
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.ROUTING
    assert reloaded.decomposition["segments"] == ["做A", "做B"]
    assert reloaded.decomposition["include_repos"] == ["r1"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resume_from_arbitrary_status() -> None:
    """从持久化 status=routing resume：注入 router 被调一次 → status=recalling。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.ROUTING,
    )
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": []})
    engine = PlanOrchestrationEngine(router=router)
    await engine.advance(session)

    router.route.assert_awaited_once()
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.RECALLING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_route_persists_routing_and_emits_event() -> None:
    """_route 捕获 router 返回经 transition 落 PlanSession.routing 并发 repo.routing 事件。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.ROUTING,
    )
    routing = {
        "candidates": [{"repo_id": "r1", "confidence": "high", "repository_name": "N"}],
        "router_version": "v2",
        "auto_selected": True,
    }
    router = AsyncMock()
    router.route = AsyncMock(return_value=routing)
    engine = PlanOrchestrationEngine(router=router)
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.RECALLING
    assert reloaded.routing == routing
    # transition 内部以 §14 event "routed" 调 _emit_event，此处用 any 匹配 repo.routing
    emitted = [
        call
        for call in spy.call_args_list
        if call.args and call.args[0] == "repo.routing"
    ]
    assert len(emitted) == 1
    assert emitted[0].args[2] == {"candidates": [{"repo_id": "r1", "confidence": "high"}]}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_injected_protocol_mocks_called() -> None:
    """各 stage 注入对应 AsyncMock，advance 调用注入依赖并推进。"""
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})
    merge = AsyncMock()
    merge.merge = AsyncMock(return_value={})
    engine = PlanOrchestrationEngine(recall=recall, research=research, merge=merge)

    # recalling → recall.recall → clarifying
    s_recall = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RECALLING
    )
    await engine.advance(s_recall)
    recall.recall.assert_awaited_once()
    assert (await PlanSession.objects.aget(id=s_recall.id)).status == PlanSessionStatus.CLARIFYING

    # researching → research.dispatch → merging
    s_research = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    await engine.advance(s_research)
    research.dispatch.assert_awaited_once()
    assert (await PlanSession.objects.aget(id=s_research.id)).status == PlanSessionStatus.MERGING

    # merging → merge.merge → done
    s_merge = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.MERGING
    )
    await engine.advance(s_merge)
    merge.merge.assert_awaited_once()
    assert (await PlanSession.objects.aget(id=s_merge.id)).status == PlanSessionStatus.DONE


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_pass_through() -> None:
    """clarifying 骨架 pass-through → researching（Phase 41 真实回路前）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.CLARIFYING
    )
    engine = PlanOrchestrationEngine()
    await engine.advance(session)
    assert (await PlanSession.objects.aget(id=session.id)).status == PlanSessionStatus.RESEARCHING


def test_engine_does_not_write_status_directly() -> None:
    """源码守护：engine.py 不含直接 .status= 赋值（只经 transition 驱动）。"""
    text = ENGINE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\.status\s*=", text), (
        "engine 不应直接写 session.status，应只经 PlanSessionService.transition"
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_skeleton_not_implemented_reraised() -> None:
    """默认骨架（不注入）在 routing 抛 NotImplementedError，不被吞成 failed。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.ROUTING
    )
    engine = PlanOrchestrationEngine()
    with pytest.raises(NotImplementedError):
        await engine.advance(session)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.ROUTING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_unrecoverable_exception_falls_to_failed() -> None:
    """注入 router 抛普通 Exception → advance 落 failed + error 含 stage 信息。"""
    router = AsyncMock()
    router.route = AsyncMock(side_effect=RuntimeError("boom"))
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.ROUTING
    )
    engine = PlanOrchestrationEngine(router=router)
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.FAILED
    assert reloaded.error.get("stage") == PlanSessionStatus.ROUTING
    assert reloaded.error.get("exception") == "RuntimeError"
