"""engine._clarify 接真实 ClarifyAdapter 测试（CLARIFY-01，41-02 Task 3）。

覆盖：需澄清 → 建 pending Clarification + emit clarification.asked + 保持 clarifying 挂起
（不转 researching）/ 已答（无 pending）+ 不需澄清 → researching / 无澄清 pass-through →
researching / resume 已有 pending → 不重复建。用真实 PlanSession/PlanSessionService +
真实 ClarifyAdapter（注入 policy 控制判定）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from delivery.models import (
    Clarification,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
)
from delivery.services import ClarificationService
from services.plan_orchestration import ClarifyAdapter, PlanOrchestrationEngine


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_needs_clarification_suspends_and_emits_asked() -> None:
    """需澄清 → status 仍 clarifying + DB 有 pending Clarification + emit clarification.asked。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    adapter = ClarifyAdapter(policy=lambda s: (True, "请补充涉及仓库/模块", []))
    engine = PlanOrchestrationEngine(clarify=adapter)

    emit_spy = AsyncMock()
    with patch("delivery.services.PlanSessionService._emit_event", new=emit_spy):
        await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    # 保持 clarifying 挂起（未转 researching）
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    # DB 有 pending Clarification
    pending = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).acount()
    assert pending == 1
    # emit clarification.asked
    asked = [
        c for c in emit_spy.call_args_list if c.args and c.args[0] == "clarification.asked"
    ]
    assert len(asked) == 1
    assert asked[0].args[2]["question"] == "请补充涉及仓库/模块"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_already_answered_advances_to_researching() -> None:
    """已答 Clarification（无 pending）+ policy 不需澄清 → researching（clarified 转移）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    # 先建一条已答 Clarification（无 pending）
    clar = await ClarificationService().create_clarification(session, "Q", [])
    await ClarificationService().answer_clarification(clar, "已答复")

    adapter = ClarifyAdapter(policy=lambda s: (False, "", []))
    engine = PlanOrchestrationEngine(clarify=adapter)
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.RESEARCHING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_no_clarification_pass_through_to_researching() -> None:
    """policy 不需澄清 + 无 pending → researching（pass-through 行为保留）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.CLARIFYING
    )
    adapter = ClarifyAdapter(policy=lambda s: (False, "", []))
    engine = PlanOrchestrationEngine(clarify=adapter)
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.RESEARCHING
    # 不需澄清不建 Clarification
    assert await Clarification.objects.filter(session_id=session.id).acount() == 0


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_existing_pending_not_duplicated_on_resume() -> None:
    """resume：已有 pending Clarification → 保持挂起、不重复建（幂等）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    # 预置一条 pending Clarification
    await ClarificationService().create_clarification(session, "已挂起的问题", [])

    # policy 即便判需澄清也不应重复建（已有 pending 优先短路）
    adapter = ClarifyAdapter(policy=lambda s: (True, "另一个问题", []))
    engine = PlanOrchestrationEngine(clarify=adapter)
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    # 仍只有 1 条 pending（未重复建）
    assert (
        await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).acount()
        == 1
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_default_policy_no_high_medium_candidate_needs_clarification() -> None:
    """默认 policy：routing 无 high/medium 候选 → 需澄清（挂起）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
    )
    engine = PlanOrchestrationEngine(clarify=ClarifyAdapter())
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_default_policy_high_candidate_no_clarification() -> None:
    """默认 policy：routing 有 high 候选 + 无 ambiguous → 不需澄清 → researching。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        routing={"candidates": [{"repo_id": "r1", "confidence": "high"}]},
    )
    engine = PlanOrchestrationEngine(clarify=ClarifyAdapter())
    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.RESEARCHING
