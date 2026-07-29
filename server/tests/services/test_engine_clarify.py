"""clarify stage 接真实 ClarifyAdapter 测试（CLARIFY-01，Chassis v2 · P2）。

覆盖：需澄清 → 建 pending 澄清轮 + emit clarification.asked + 保持 clarify 挂起
（waiting_clarification）/ 已答（无 pending）+ 不需澄清 → research / 无澄清 pass-through →
research / resume 已有 pending → 不重复建。用真实 ConvergenceSession/ConvergenceSessionService +
真实 ClarifyAdapter（注入 policy 控制判定），LLM 生成器 patch 为 [] 保确定性。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from delivery.models import (
    Clarification,
    ClarificationQuestion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ClarificationService, ConvergenceSessionService
from services.process_runtime import ClarifyAdapter, ProcessEngine
from services.process_runtime.clarify_adapter import default_needs_clarification

_LLM_GEN = "services.process_runtime.clarify_adapter.agenerate_clarification_questions"


async def _clarify_session(
    *, routing: dict | None = None, decomposition: dict | None = None,
    entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
) -> ConvergenceSession:
    stage_state: dict = {}
    if routing is not None:
        stage_state["routing"] = routing
    if decomposition is not None:
        stage_state["decomposition"] = decomposition
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=entrypoint,
        current_stage="clarify",
        status=ConvergenceSessionStatus.RUNNING,
        stage_state=stage_state,
    )


def _engine(adapter: ClarifyAdapter) -> ProcessEngine:
    return ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(clarify=adapter)
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_needs_clarification_suspends_and_emits_asked() -> None:
    """需澄清 → 仍 clarify（waiting_clarification）+ DB 有 pending Clarification + emit clarification.asked。"""
    session = await _clarify_session()
    adapter = ClarifyAdapter(policy=lambda s: (True, "请补充涉及仓库/模块", []))
    engine = _engine(adapter)

    emit_spy = AsyncMock()
    with (
        patch(_LLM_GEN, new=AsyncMock(return_value=[])),
        patch("delivery.services.ConvergenceSessionService._emit_event", new=emit_spy),
    ):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
    pending = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).acount()
    assert pending == 1
    asked = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "clarification.asked"]
    assert len(asked) == 1
    assert asked[0].args[2]["question"] == "请补充涉及仓库/模块"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_already_answered_advances_to_researching() -> None:
    """已答澄清轮（无 pending）+ policy 不需澄清 → research（clarified 转移）。"""
    session = await _clarify_session()
    await _answered_round(session)

    adapter = ClarifyAdapter(policy=lambda s: (False, "", []))
    engine = _engine(adapter)
    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "research"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_no_clarification_pass_through_to_researching() -> None:
    """policy 不需澄清 + 无 pending → research（pass-through 行为保留）。"""
    session = await _clarify_session(entrypoint=ConvergenceSessionEntrypoint.CHAT)
    adapter = ClarifyAdapter(policy=lambda s: (False, "", []))
    engine = _engine(adapter)
    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "research"
    assert await Clarification.objects.filter(session_id=session.id).acount() == 0


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_existing_pending_not_duplicated_on_resume() -> None:
    """resume：已有 pending 澄清轮 → 保持挂起、不重复建（幂等）。"""
    session = await _clarify_session()
    # 预置一条 pending 结构化轮
    await ClarificationService().create_round(
        session, [{"question": "已挂起的问题", "type": "single", "options": [], "recommended": []}]
    )

    adapter = ClarifyAdapter(policy=lambda s: (True, "另一个问题", []))
    engine = _engine(adapter)
    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
    assert (
        await Clarification.objects.filter(session_id=session.id, answered_at__isnull=True).acount()
        == 1
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_default_policy_no_high_medium_candidate_needs_clarification() -> None:
    """默认 policy：routing 无 high/medium 候选 → 需澄清（挂起）。"""
    session = await _clarify_session(
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
        decomposition={"requirement_text": "需求文本"},
    )
    engine = _engine(ClarifyAdapter())
    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_default_policy_high_candidate_no_clarification() -> None:
    """默认 policy：routing 有 high 候选 + 无 ambiguous → 不需澄清 → research。"""
    session = await _clarify_session(
        routing={"candidates": [{"repo_id": "r1", "confidence": "high"}]},
    )
    engine = _engine(ClarifyAdapter())
    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "research"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_real_policy_answered_round_advances_no_second_clarification() -> None:
    """CR-01 回归：真实默认 policy（routing 无 high/medium 恒判需澄清），一轮澄清答复后必须
    放行 research、**不再创建第二条 Clarification**（否则无限挂起）。"""
    session = await _clarify_session(
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
        decomposition={"requirement_text": "需求文本"},
    )
    engine = _engine(ClarifyAdapter())

    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        # 第一轮 advance：policy 判需澄清 → 建 pending + 保持挂起
        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)
        assert session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
        pending = await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).afirst()
        assert pending is not None

        # 回答这条 pending 轮
        q = await ClarificationQuestion.objects.filter(clarification_id=pending.id).afirst()
        await ClarificationService().answer_round(
            pending, [{"question_id": q.id, "selected": None, "freeform_text": "涉及 repoX"}]
        )

        # 第二轮 advance：已答轮 → 放行 research，不再追问
        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)

    assert session.current_stage == "research"
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


# ── CLARIFY-02：LLM 多题接线 + fail-soft 回退 + pending 升级 ──────────────


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_wires_llm_multi_questions() -> None:
    """首轮 needs==True → 调 LLM 产多题，经 create_round 落容器 + N 个 ClarificationQuestion。"""
    session = await _clarify_session(decomposition={"requirement_text": "把实验组用户引流到新页"})
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

    assert gen.await_count == 1
    assert result["needs_clarification"] is True
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
    """LLM 返回 [] → fail-soft 回退现状粗单题（容器 + 1 子题）、记回退事件、不抛。"""
    session = await _clarify_session(decomposition={"requirement_text": "需求文本"})
    adapter = ClarifyAdapter(policy=lambda s: (True, "请补充涉及仓库/模块", []))
    with (
        patch(_LLM_GEN, new=AsyncMock(return_value=[])),
        patch("services.process_runtime.clarify_adapter.logger") as mock_logger,
    ):
        result = await adapter.clarify(session)

    assert result["needs_clarification"] is True
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1
    # 回退 create_round 建 1 子题（粗单题）
    assert (
        await ClarificationQuestion.objects.filter(clarification__session_id=session.id).acount()
        == 1
    )
    events = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
    assert "clarification_fallback_coarse_question" in events


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_fail_soft_exception_does_not_fail_session() -> None:
    """生成器内部已吞异常返回 [] → adapter 不抛、engine 不落 failed（仍 clarify 挂起）。"""
    session = await _clarify_session(decomposition={"requirement_text": "需求文本"})
    adapter = ClarifyAdapter(policy=lambda s: (True, "粗问题", []))
    engine = _engine(adapter)
    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.status != ConvergenceSessionStatus.FAILED
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


# ── CLARIFY-07：放开多轮 + round_no 上界 + 带答案重判 ──────────────────


async def _answered_round(session: ConvergenceSession, question: str = "Q") -> None:
    """建一个结构化单题轮并作答（无 pending），供多轮测试铺垫已答轮。"""
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [{"question": question, "type": "single", "options": ["a", "b"], "recommended": "a"}],
    )
    assert clar is not None
    q = await ClarificationQuestion.objects.aget(clarification_id=clar.id)
    await svc.answer_round(clar, [{"question_id": str(q.id), "selected": "a", "freeform_text": ""}])


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_multi_round_reclarifies_when_still_insufficient() -> None:
    """已答 1 轮 + policy 仍判需澄清 + 重判生成器返回非空 → 再发一轮（round_no 递增）。"""
    session = await _clarify_session(
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
        decomposition={"requirement_text": "需求文本"},
    )
    await _answered_round(session)

    adapter = ClarifyAdapter()
    gen = AsyncMock(
        return_value=[{"question": "Q2", "type": "single", "options": ["x", "y"], "recommended": "x"}]
    )
    with patch(_LLM_GEN, new=gen):
        result = await adapter.clarify(session)

    assert result["needs_clarification"] is True
    assert "clarification_id" in result
    assert await Clarification.objects.filter(session_id=session.id).acount() == 2
    new_clar = await Clarification.objects.aget(id=result["clarification_id"])
    assert new_clar.round_no == 2


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_multi_round_advances_when_rejudge_sufficient() -> None:
    """已答 1 轮 + 重判生成器返回 [] → 视为信息足够，放行 research，不再发轮。"""
    session = await _clarify_session(
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
        decomposition={"requirement_text": "需求文本"},
    )
    await _answered_round(session)

    adapter = ClarifyAdapter()
    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        result = await adapter.clarify(session)

    assert result == {"needs_clarification": False}
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_round_cap_reached_continues_without_new_round() -> None:
    """已答轮数达上界（_MAX_CLARIFY_ROUNDS=6）→ 带现有信息继续，不再发轮 + log 触顶。"""
    session = await _clarify_session(
        routing={"candidates": [{"repo_id": "r1", "confidence": "low"}]},
        decomposition={"requirement_text": "需求文本"},
    )
    for i in range(6):
        await _answered_round(session, question=f"Q{i}")

    adapter = ClarifyAdapter()
    gen = AsyncMock(return_value=[{"question": "不该被调", "type": "single", "options": [], "recommended": ""}])
    with (
        patch(_LLM_GEN, new=gen),
        patch("services.process_runtime.clarify_adapter.logger") as mock_logger,
    ):
        result = await adapter.clarify(session)

    assert result == {"needs_clarification": False}
    assert await Clarification.objects.filter(session_id=session.id).acount() == 6
    assert gen.await_count == 0
    events = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
    assert "clarification_round_cap_reached" in events


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_pending_uses_ahas_pending() -> None:
    """轮内有未答子题 → 再次 clarify 经 ahas_pending 判 pending=True，不重复建轮。"""
    session = await _clarify_session(decomposition={"requirement_text": "需求文本"})
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

    assert result == {"needs_clarification": True, "pending": True}
    assert gen.await_count == 0
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


# ── 105-03 RELY-04：降级路由（Stage 1 失联）的 clarify policy 行为回归 ──────
#
# 生产事故链（会话 ccd817d9）：Stage 1 失联 → confidence 恒 low → 无差别澄清/
# 强制确认 → 编排卡死。confidence 语义修复（确定性 margin 推导）后，policy 代码
# 零改动自动解锁——以下用例在 policy / adapter 层锁定该行为（RESEARCH Pitfall 1：
# 只测 router 单元不足以证明编排推进）。


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_default_policy_degraded_routing_high_margin_no_clarification() -> None:
    """RELY-04：Stage 1 失联降级但 margin 达标（首位确定性 high，router_version=
    v2_stage0_only）→ default policy 判定无需澄清，编排自动推进。"""
    session = await _clarify_session(
        routing={
            "candidates": [
                {"repo_id": "r1", "confidence": "high", "repository_name": "R1"},
                {"repo_id": "r2", "confidence": "low", "repository_name": "R2"},
            ],
            "router_version": "v2_stage0_only",
            "auto_selected": True,
        },
    )
    needs, _question, _affected = default_needs_clarification(session)
    assert needs is False


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_default_policy_degraded_routing_all_low_still_clarifies() -> None:
    """RELY-04 边界：降级产物全 low（margin 不达标）→ 仍需澄清——语义未被放松，
    修复只解锁「margin 达标却被恒 low 卡死」的情形。"""
    session = await _clarify_session(
        routing={
            "candidates": [
                {"repo_id": "r1", "confidence": "low", "repository_name": "R1"},
                {"repo_id": "r2", "confidence": "low", "repository_name": "R2"},
            ],
            "router_version": "v2_stage0_only",
            "auto_selected": False,
        },
    )
    needs, question, _affected = default_needs_clarification(session)
    assert needs is True
    assert question


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_adapter_degraded_routing_high_conf_no_forced_confirmation() -> None:
    """success criterion 1 回归：确定性 confidence=high 时强制确认不再无差别触发。

    非 feature_list 会话（stage_state 无 classification、question_builder 不产题）+
    routing 首位 confidence="high" → ClarifyAdapter.clarify 返回
    needs_clarification=False：不建澄清轮（create_round 未被调用）、不 emit
    clarification.asked——编排自动推进。

    注：feature_list 入口的 build_feature_confirm_questions 强制确认是独立产品约束
    （「哪怕路由十分确定也必须确认一次」），不属于「无差别触发」范围，本修复不改
    其行为——本用例用默认 ClarifyAdapter（question_builder=None）。
    """
    session = await _clarify_session(
        routing={
            "candidates": [
                {"repo_id": "r1", "confidence": "high", "repository_name": "R1"},
            ],
            "router_version": "v2_stage0_only",
            "auto_selected": True,
        },
        decomposition={"requirement_text": "需求文本"},
    )
    adapter = ClarifyAdapter()
    gen = AsyncMock(return_value=[])
    create_spy = AsyncMock()
    emit_spy = AsyncMock()
    with (
        patch(_LLM_GEN, new=gen),
        patch("delivery.services.ClarificationService.create_round", new=create_spy),
        patch("delivery.services.ConvergenceSessionService._emit_event", new=emit_spy),
    ):
        result = await adapter.clarify(session)

    assert result == {"needs_clarification": False}
    assert create_spy.await_count == 0  # 不建澄清轮
    asked = [c for c in emit_spy.call_args_list if c.args and c.args[0] == "clarification.asked"]
    assert asked == []  # 不 emit clarification.asked
    assert gen.await_count == 0  # LLM 生成器也未被触发
