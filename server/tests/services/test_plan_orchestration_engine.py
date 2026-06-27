"""PlanOrchestrationEngine 测试（ORCH-01）。

覆盖 advance(decomposing→routing 真实拆分) / 任意 status resume / 注入 mock 被调 /
engine 不直接写 status / 骨架 NotImplementedError 上抛 / 普通异常落 failed。
用真实 PlanSession + PlanSessionService，stage 依赖用 AsyncMock 注入。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from services.plan_orchestration import PlanOrchestrationEngine

ENGINE_PATH = Path(__file__).resolve().parents[2] / "services" / "plan_orchestration" / "engine.py"

# _decompose 内 lazy import agenerate_decomposition_segments，故 patch 源定义点
# （engine 模块命名空间无该名字 → 只能 patch decompose_segments 源模块）。
_DECOMPOSE_GEN = "services.plan_orchestration.decompose_segments.agenerate_decomposition_segments"


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
async def test_decompose_llm_success_structured_segments() -> None:
    """LLM 成功产结构化 segments（list[dict]）→ 写入 decomposition + 推进 ROUTING + 契约键保留。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.DECOMPOSING,
        decomposition={"requirement_text": "把实验组引流到新页", "include_repos": ["r1"]},
    )
    llm_segments = [
        {"title": "登录页改造", "module": "用户中心", "layer": "frontend", "repo_hint": "r1"},
    ]
    engine = PlanOrchestrationEngine()
    with patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=llm_segments)):
        await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.ROUTING
    # LLM 成功 → segments 为结构化 dict 列表（非 splitlines）
    assert reloaded.decomposition["segments"] == llm_segments
    # routing 契约键两路径都保留
    assert reloaded.decomposition["requirement_text"] == "把实验组引流到新页"
    assert reloaded.decomposition["include_repos"] == ["r1"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_decompose_fail_soft_falls_back_to_splitlines() -> None:
    """helper 返回 None（LLM 失败/缺 model）→ 回退 splitlines list[str] + 记回退事件 + 推进 ROUTING（非 FAILED）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.DECOMPOSING,
        decomposition={"requirement_text": "做A\n做B", "include_repos": ["r1"]},
    )
    engine = PlanOrchestrationEngine()
    with (
        patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=None)),
        patch("services.plan_orchestration.engine.logger") as mock_logger,
    ):
        await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    # fail-soft：回退按非空行切分 list[str]，session 推进 ROUTING（绝不落 FAILED）
    assert reloaded.status == PlanSessionStatus.ROUTING
    assert reloaded.decomposition["segments"] == ["做A", "做B"]
    assert reloaded.decomposition["requirement_text"] == "做A\n做B"
    assert reloaded.decomposition["include_repos"] == ["r1"]
    # 记 plan_decompose_fallback_splitlines 回退事件
    events = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
    assert "plan_decompose_fallback_splitlines" in events


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_decompose_no_model_equivalent_fail_soft() -> None:
    """无 default_model 等价 fail-soft（helper 返回 None）→ 回退 splitlines + ROUTING（非 FAILED）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.DECOMPOSING,
        decomposition={"requirement_text": "需求一\n需求二", "include_repos": []},
    )
    engine = PlanOrchestrationEngine()
    with patch(_DECOMPOSE_GEN, new=AsyncMock(return_value=None)):
        await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.ROUTING
    assert reloaded.decomposition["segments"] == ["需求一", "需求二"]
    assert reloaded.decomposition["include_repos"] == []


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
    emitted = [call for call in spy.call_args_list if call.args and call.args[0] == "repo.routing"]
    assert len(emitted) == 1
    assert emitted[0].args[2] == {"candidates": [{"repo_id": "r1", "confidence": "high"}]}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_recall_persists_context_and_emits_event() -> None:
    """_recall 捕获 recall 返回经 transition 落 recall_context 并发 knowledge.recalling 事件。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.RECALLING,
    )
    hits = [{"entity_id": "e1", "kind": "work_item", "title": "t", "score": 0.9}]
    recall = AsyncMock()
    recall.recall = AsyncMock(
        return_value={
            "hits": hits,
            "query": "q",
            "kinds": ["work_item", "tech_plan", "code_change"],
        }
    )
    engine = PlanOrchestrationEngine(recall=recall)
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.CLARIFYING
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
    # Phase 40：merge adapter 返回 {validation_status} 契约；passed → merging→done
    merge.merge = AsyncMock(return_value={"validation_status": "passed", "attempt": 0})
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
async def test_clarify_no_clarification_advances_to_researching() -> None:
    """clarifying + 注入 clarify（不需澄清）→ researching（Phase 41 真实回路）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.CLARIFYING
    )
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    engine = PlanOrchestrationEngine(clarify=clarify)
    await engine.advance(session)
    clarify.clarify.assert_awaited_once()
    assert (await PlanSession.objects.aget(id=session.id)).status == PlanSessionStatus.RESEARCHING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_research_concurrent_barrier_advance_not_overwritten_to_failed() -> None:
    """WR-03：dispatch 后、engine transition 前容器回调 barrier 把 DB 推进 researching→
    merging；engine 的陈旧条件转移被拒（ConcurrentTransitionError）视为良性 no-op，
    绝不把已推进的 merging 覆盖回 failed（无状态损坏）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )

    async def _dispatch_then_barrier_advance(s):
        # 模拟容器回调侧 barrier 抢先把 DB 推进 researching→merging（engine 内存态仍 researching）
        await PlanSession.objects.filter(id=s.id).aupdate(status=PlanSessionStatus.MERGING)
        return {}

    research = AsyncMock()
    research.dispatch = AsyncMock(side_effect=_dispatch_then_barrier_advance)
    engine = PlanOrchestrationEngine(research=research)

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    # 关键：状态保持 barrier 正确推进的 merging，未被错误覆盖为 failed
    assert reloaded.status == PlanSessionStatus.MERGING


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
