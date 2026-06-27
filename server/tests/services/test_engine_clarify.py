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
    ClarificationQuestion,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
)
from delivery.services import ClarificationService
from services.plan_orchestration import ClarifyAdapter, PlanOrchestrationEngine

_LLM_GEN = "services.plan_orchestration.clarify_adapter.agenerate_clarification_questions"


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
    asked = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "clarification.asked"]
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
        await Clarification.objects.filter(session_id=session.id, answered_at__isnull=True).acount()
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


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_real_policy_answered_round_advances_no_second_clarification() -> None:
    """CR-01 回归：真实默认 policy 路径（非注入 always-False）下，policy 持续判「需澄清」
    （routing 无 high/medium，答后信号不变），但一轮澄清答复后必须放行 researching、
    **不再创建第二条 Clarification**（否则无限挂起，违反 §14「全部已答 → researching」）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        # routing 无 high/medium → 默认 policy 恒判需澄清（答后该信号不变）
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
    )
    engine = PlanOrchestrationEngine(clarify=ClarifyAdapter())

    # 第一轮 advance：policy 判需澄清 → 建 pending + 保持 clarifying 挂起
    await engine.advance(session)
    session = await PlanSession.objects.aget(id=session.id)
    assert session.status == PlanSessionStatus.CLARIFYING
    pending = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).afirst()
    assert pending is not None

    # 回答这条 pending Clarification（routing 信号未变）
    await ClarificationService().answer_clarification(pending, "补充：涉及 repoX")

    # 第二轮 advance：尽管 policy 仍会判需澄清，已答轮 → 放行 researching，不再追问
    await engine.advance(session)
    session = await PlanSession.objects.aget(id=session.id)
    assert session.status == PlanSessionStatus.RESEARCHING
    # 关键：未创建第二条 Clarification（仍只有首轮那 1 条）
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


# ── CLARIFY-02：LLM 多题接线 + fail-soft 回退 + pending 升级（90-03） ──────────────


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_wires_llm_multi_questions() -> None:
    """首轮 needs==True → 调 LLM 产多题，经 create_round 落容器 + N 个 ClarificationQuestion。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        decomposition={"requirement_text": "把实验组用户引流到新页"},
    )
    llm_questions = [
        {
            "question": "**实验组用户**口径？",
            "type": "single",
            "options": ["按标签", "按名单"],
            "recommended": "按标签",
        },
        {
            "question": "改动涉及哪些端？",
            "type": "multi",
            "options": ["web", "app"],
            "recommended": ["web"],
        },
    ]
    adapter = ClarifyAdapter(policy=lambda s: (True, "粗问题", []))
    gen = AsyncMock(return_value=llm_questions)
    with patch(_LLM_GEN, new=gen):
        result = await adapter.clarify(session)

    # LLM 生成器被调用（首轮 needs==True 后）
    assert gen.await_count == 1
    assert result["needs_clarification"] is True
    # create_round 落 1 容器 + 2 子题
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1
    children = [
        q
        async for q in ClarificationQuestion.objects.filter(
            clarification__session_id=session.id
        ).order_by("order")
    ]
    assert len(children) == 2
    assert children[0].qtype == "single"
    assert children[1].qtype == "multi"
    assert children[0].options == ["按标签", "按名单"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_fail_soft_empty_falls_back_to_coarse() -> None:
    """LLM 返回 [] → fail-soft 回退现状粗单题（legacy 单题行、无子题）、记回退事件、不抛。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        decomposition={"requirement_text": "需求文本"},
    )
    adapter = ClarifyAdapter(policy=lambda s: (True, "请补充涉及仓库/模块", []))
    with (
        patch(_LLM_GEN, new=AsyncMock(return_value=[])),
        patch("services.plan_orchestration.clarify_adapter.logger") as mock_logger,
    ):
        result = await adapter.clarify(session)

    assert result["needs_clarification"] is True
    # 回退建 1 条 legacy 单题行（无子题）
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1
    assert (
        await ClarificationQuestion.objects.filter(clarification__session_id=session.id).acount()
        == 0
    )
    # 记 clarification_fallback_coarse_question 回退事件
    events = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
    assert "clarification_fallback_coarse_question" in events


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_fail_soft_exception_does_not_fail_session() -> None:
    """生成器内部已吞异常返回 [] → adapter 不抛、engine 不落 failed（仍 clarifying 挂起）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        decomposition={"requirement_text": "需求文本"},
    )
    adapter = ClarifyAdapter(policy=lambda s: (True, "粗问题", []))
    engine = PlanOrchestrationEngine(clarify=adapter)
    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    # engine 未落 failed：fail-soft 回退后保持 clarifying 挂起
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_pending_uses_ahas_pending() -> None:
    """轮内有未答子题 → 再次 clarify 经 ahas_pending 判 pending=True，不重复建轮。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.CLARIFYING,
        decomposition={"requirement_text": "需求文本"},
    )
    # 预置一个结构化多题轮（子题未答 → ahas_pending True）
    await ClarificationService().create_round(
        session,
        [{"question": "Q1", "type": "single", "options": ["a", "b"], "recommended": "a"}],
    )

    adapter = ClarifyAdapter(policy=lambda s: (True, "不应被调用", []))
    gen = AsyncMock(
        return_value=[{"question": "Q2", "type": "single", "options": [], "recommended": ""}]
    )
    with patch(_LLM_GEN, new=gen):
        result = await adapter.clarify(session)

    # pending 短路：返回 pending、未调 LLM、未重复建轮
    assert result == {"needs_clarification": True, "pending": True}
    assert gen.await_count == 0
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1
