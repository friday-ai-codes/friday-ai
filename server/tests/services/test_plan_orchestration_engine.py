"""ProcessEngine 数据化 stage graph 推进测试（ORCH-01，泛化自 PlanOrchestrationEngine）。

覆盖 advance(decompose→route 真实拆分) / 任意 stage resume / 注入 deps 被调 /
engine 不直接写 status / NotImplementedError 上抛 / 普通异常落 failed。
用真实 ConvergenceSession + ConvergenceSessionService，stage 依赖经 ``deps`` namespace 注入。
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ConvergenceSessionService
from services.process_runtime import ProcessEngine

ENGINE_PATH = Path(__file__).resolve().parents[2] / "services" / "process_runtime" / "engine.py"

# _h_decompose 内 lazy import agenerate_decomposition_segments，故 patch 源定义点。
_DECOMPOSE_GEN = "services.process_runtime.decompose_segments.agenerate_decomposition_segments"


async def _make_session(
    current_stage: str, *, stage_state: dict | None = None
) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=current_stage,
        stage_state=stage_state or {},
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_advance_from_decomposing_real_decompose() -> None:
    """decompose → _h_decompose 真实执行（拆分结构）→ current_stage=route（经 transition）。"""
    session = await _make_session(
        "decompose",
        stage_state={"decomposition": {"requirement_text": "做A\n做B", "include_repos": ["r1"]}},
    )
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=None)
    with patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=None)):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "route"
    assert reloaded.decomposition["segments"] == ["做A", "做B"]
    assert reloaded.decomposition["include_repos"] == ["r1"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_decompose_llm_success_structured_segments() -> None:
    """LLM 成功产结构化 segments（list[dict]）→ 写入 decomposition + 推进 route + 契约键保留。"""
    session = await _make_session(
        "decompose",
        stage_state={"decomposition": {"requirement_text": "把实验组引流到新页", "include_repos": ["r1"]}},
    )
    llm_segments = [
        {"title": "登录页改造", "module": "用户中心", "layer": "frontend", "repo_hint": "r1"},
    ]
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=None)
    with patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=llm_segments)):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "route"
    assert reloaded.decomposition["segments"] == llm_segments
    assert reloaded.decomposition["requirement_text"] == "把实验组引流到新页"
    assert reloaded.decomposition["include_repos"] == ["r1"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_decompose_fail_soft_falls_back_to_splitlines() -> None:
    """helper 返回 None（LLM 失败/缺 model）→ 回退 splitlines list[str] + 记回退事件 + 推进 route。"""
    session = await _make_session(
        "decompose",
        stage_state={"decomposition": {"requirement_text": "做A\n做B", "include_repos": ["r1"]}},
    )
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=None)
    with (
        patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=None)),
        patch("services.process_runtime.builtin_processes.logger") as mock_logger,
    ):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "route"
    assert reloaded.decomposition["segments"] == ["做A", "做B"]
    assert reloaded.decomposition["requirement_text"] == "做A\n做B"
    assert reloaded.decomposition["include_repos"] == ["r1"]
    events = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
    assert "plan_decompose_fallback_splitlines" in events


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_decompose_no_model_equivalent_fail_soft() -> None:
    """无 default_model 等价 fail-soft（helper 返回 None）→ 回退 splitlines + route。"""
    session = await _make_session(
        "decompose",
        stage_state={"decomposition": {"requirement_text": "需求一\n需求二", "include_repos": []}},
    )
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=None)
    with patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=None)):
        await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "route"
    assert reloaded.decomposition["segments"] == ["需求一", "需求二"]
    assert reloaded.decomposition["include_repos"] == []


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resume_from_arbitrary_status() -> None:
    """从持久化 current_stage=route resume：注入 router 被调一次 → current_stage=recall。"""
    session = await _make_session("route")
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": []})
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(router=router)
    )
    await engine.advance(session)

    router.route.assert_awaited_once()
    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "recall"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_route_persists_routing_and_emits_event() -> None:
    """_h_route 捕获 router 返回经 transition 落 routing 并发 repo.routing 事件。"""
    session = await _make_session("route")
    routing = {
        "candidates": [{"repo_id": "r1", "confidence": "high", "repository_name": "N"}],
        "router_version": "v2",
        "auto_selected": True,
    }
    router = AsyncMock()
    router.route = AsyncMock(return_value=routing)
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(router=router)
    )
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "recall"
    assert reloaded.routing == routing
    emitted = [call for call in spy.call_args_list if call.args and call.args[0] == "repo.routing"]
    assert len(emitted) == 1
    assert emitted[0].args[2] == {
        "candidates": [{"repo_id": "r1", "confidence": "high"}],
        "router_version": "v2",
        "degraded": False,
        "degrade_reason": "",
    }


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_route_minimal_payload_carries_degrade_facts() -> None:
    """RELY-03：无 stage0 快照的 v1_fallback 也必须把降级三键发出去。

    这是「降级徽标在真降级时反而不显示」那个洞的回归锚：``_h_route`` 的快照分支
    要求 ``snapshot["stage0"]`` 非空，而 v1_fallback 的 snapshot 只有 stage1，
    于是它落到精简分支。精简分支一旦不带 ``degraded``，前端严格判等就恒为假。
    """
    session = await _make_session("route")
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={
            "candidates": [{"repo_id": "r1", "confidence": "low"}],
            "router_version": "v1_fallback",
            "degraded": True,
            "degrade_reason": "upstream_error",
            # stage0 缺席 ⇒ 走精简分支（与 repo_router_v2 的 v1_fallback 出参同形）
            "snapshot": {"stage1": {"skipped_reason": "v1_fallback"}},
        }
    )
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(router=router)
    )
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    emitted = [call for call in spy.call_args_list if call.args and call.args[0] == "repo.routing"]
    assert len(emitted) == 1
    payload = emitted[0].args[2]
    assert payload["degraded"] is True
    assert payload["degrade_reason"] == "upstream_error"
    assert payload["router_version"] == "v1_fallback"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_route_snapshot_payload_carries_degrade_reason() -> None:
    """RELY-03：快照分支同样带 ``degrade_reason``，解释句才说得出「为什么」。"""
    session = await _make_session("route")
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={
            "candidates": [{"repo_id": "r1", "confidence": "medium"}],
            "router_version": "v2_stage0_only",
            "degraded": True,
            "degrade_reason": "timeout",
            "snapshot": {
                "stage0": {"query": "q"},
                "candidates": [{"repo_id": "r1", "score": 0.8, "breakdown": {"text": 0.8}}],
            },
        }
    )
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(router=router)
    )
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    payload = [c for c in spy.call_args_list if c.args and c.args[0] == "repo.routing"][0].args[2]
    assert payload["degraded"] is True
    assert payload["degrade_reason"] == "timeout"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_recall_persists_context_and_emits_event() -> None:
    """_h_recall 捕获 recall 返回经 transition 落 recall_context 并发 knowledge.recalling 事件。"""
    session = await _make_session("recall")
    hits = [{"entity_id": "e1", "kind": "work_item", "title": "t", "score": 0.9}]
    recall = AsyncMock()
    recall.recall = AsyncMock(
        return_value={
            "hits": hits,
            "query": "q",
            "kinds": ["work_item", "tech_plan", "code_change"],
        }
    )
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(recall=recall)
    )
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    # recall 之后进 classify（feature list 分类扩展点）；非 feature_list 会话在该 stage
    # pass-through 到 clarify。
    assert reloaded.current_stage == "classify"
    assert reloaded.recall_context == hits
    emitted = [
        call for call in spy.call_args_list if call.args and call.args[0] == "knowledge.recalling"
    ]
    assert len(emitted) == 1
    assert emitted[0].args[2] == {
        "query": "q",
        "kinds": ["work_item", "tech_plan", "code_change"],
        "hits": 1,
    }


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_injected_protocol_mocks_called() -> None:
    """各 stage 注入对应 AsyncMock，advance 调用注入依赖并推进。"""
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})
    merge = AsyncMock()
    # merge adapter 返回 {validation_status} 契约；passed → merge→__done__
    merge.merge = AsyncMock(return_value={"validation_status": "passed", "attempt": 0})
    deps = SimpleNamespace(recall=recall, research=research, merge=merge)
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=deps)

    # recall → recall.recall → classify
    s_recall = await _make_session("recall")
    await engine.advance(s_recall)
    recall.recall.assert_awaited_once()
    assert (await ConvergenceSession.objects.aget(id=s_recall.id)).current_stage == "classify"

    # classify → pass-through → clarify。deps 未注入 classify（本例即是）时 stage 必须
    # 零副作用穿过，不得报错——保证既有入口不受 feature list 扩展影响。
    s_classify = await _make_session("classify")
    await engine.advance(s_classify)
    reloaded_classify = await ConvergenceSession.objects.aget(id=s_classify.id)
    assert reloaded_classify.current_stage == "clarify"
    assert "classification" not in (reloaded_classify.stage_state or {})

    # research → research.dispatch → merge（无在途调研 → research_complete）
    s_research = await _make_session("research")
    await engine.advance(s_research)
    research.dispatch.assert_awaited_once()
    assert (await ConvergenceSession.objects.aget(id=s_research.id)).current_stage == "merge"

    # merge → merge.merge → __done__
    s_merge = await _make_session("merge")
    await engine.advance(s_merge)
    merge.merge.assert_awaited_once()
    assert (await ConvergenceSession.objects.aget(id=s_merge.id)).status == ConvergenceSessionStatus.DONE


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clarify_no_clarification_advances_to_researching() -> None:
    """clarify + 注入 clarify（不需澄清）→ research（clarified 转移）。"""
    session = await _make_session("clarify")
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(clarify=clarify)
    )
    await engine.advance(session)
    clarify.clarify.assert_awaited_once()
    assert (await ConvergenceSession.objects.aget(id=session.id)).current_stage == "research"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_research_concurrent_barrier_advance_not_overwritten_to_failed() -> None:
    """WR-03：dispatch 后、engine transition 前回调 barrier 把 DB 推进 research→merge；
    engine 的陈旧条件转移被拒（ConcurrentTransitionError）视为良性 no-op，绝不覆盖回 failed。"""
    session = await _make_session("research")

    async def _dispatch_then_barrier_advance(s):
        # 模拟回调侧 barrier 抢先把 DB 推进 research→merge（engine 内存态仍 research）
        await ConvergenceSession.objects.filter(id=s.id).aupdate(current_stage="merge")
        return {}

    research = AsyncMock()
    research.dispatch = AsyncMock(side_effect=_dispatch_then_barrier_advance)
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(research=research)
    )

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    # 关键：状态保持 barrier 正确推进的 merge，未被错误覆盖为 failed
    assert reloaded.current_stage == "merge"


def test_engine_does_not_write_status_directly() -> None:
    """源码守护：engine.py 不含直接 .status= 赋值（只经 transition 驱动）。"""
    text = ENGINE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\.status\s*=", text), (
        "engine 不应直接写 session.status，应只经 ConvergenceSessionService.transition"
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_not_implemented_reraised() -> None:
    """stage handler 抛 NotImplementedError → engine 原样上抛，不被吞成 failed。"""
    session = await _make_session("route")
    router = AsyncMock()
    router.route = AsyncMock(side_effect=NotImplementedError("not wired"))
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(router=router)
    )
    with pytest.raises(NotImplementedError):
        await engine.advance(session)
    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "route"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_unrecoverable_exception_falls_to_failed() -> None:
    """注入 router 抛普通 Exception → advance 落 failed + error 含 stage 信息。"""
    router = AsyncMock()
    router.route = AsyncMock(side_effect=RuntimeError("boom"))
    session = await _make_session("route")
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(router=router)
    )
    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.status == ConvergenceSessionStatus.FAILED
    assert reloaded.error.get("stage") == "route"
    assert reloaded.error.get("exception") == "RuntimeError"
