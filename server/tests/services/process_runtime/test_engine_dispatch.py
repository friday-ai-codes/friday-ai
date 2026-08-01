"""engine 与 driver 按 process_type 分派 + 两个方向的 LOUD 守卫（Phase 116-01 Task 2）。

守七件事：

1. **正向分派**：两个 ``process_type`` 各自拿到对的 deps **与对的 driver**（driver 用 ``is``
   断言身份，⛔ 不断言函数名字符串）。
2. **未知 process_type 回落 + 事件**：不抛、按旧链返回、落一条
   ``engine_dispatch_unknown_process_type``。
3. **⛔ 不透传旧链开关**：蓝图分支收到 ``skip_clarification`` / ``force_confirm`` 不抛
   TypeError、engine 的 deps 上没有 ``clarify``，并落一条 ``blueprint_engine_ignored_legacy_flag``。
4. ⭐ **变异 A（错工厂 · repo_research）**：出边是 ``needs_clarification`` **且**有一条
   ``blueprint_stage_wrong_adapter``（白名单判据 c）+ ``ArtifactVersion`` 计数不变（判据 b）。
5. ⭐ **变异 B（错工厂 · merge，最坏形态）**：``ArtifactVersion`` 计数不变、全库无
   ``schema_version != "blueprint/v1"`` 的新版本、事件 ``stage == "merge"``。
6. ⭐ **变异 C（错 driver）**：no-op —— ``status`` / ``current_stage`` 逐字未变、有一条
   ``wrong_driver_for_blueprint_session``、``error`` 里没有 ``advance_step_limit``。
7. **反向对照（守卫不误伤）**：旧 driver 驱 ``technical_plan`` 会话仍正常 advance；蓝图
   driver 驱 ``technical_plan`` 会话仍走既有 ``blueprint_resume_wrong_process_type`` no-op。

⚠️ 变异 A/B/C 的期望值按 **Wave 0 探针实测**校准（错工厂 + 对的 driver，从 ``intake`` 驱一条
蓝图会话，实测终局 ``current_stage='reroute'`` / ``status='failed'`` /
``error={'stage': 'reroute', 'exception': 'AttributeError', 'message': "'ResearchDispatchAdapter'
object has no attribute 'aadvance_reroute'"}``）—— 与 RESEARCH §A.3 的推演逐字吻合。⛔ 全部
判据都是**正向白名单**（终局三元组 / 计数相等 / 出边 + 事件），⛔ 不写「未到 DONE」这类否定式
（正确实现下会话停在 spec_gate 等澄清也不是 DONE ⇒ 恒绿、变异不敏感，P-3）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from delivery.models import (
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ArtifactService, ConvergenceSessionService
from services.process_runtime import blueprint_resume
from services.process_runtime import builtin_processes as bp
from services.process_runtime import resume as legacy_resume
from services.process_runtime.entrypoint import (
    build_blueprint_engine,
    build_engine_for_session,
    build_orchestration_engine,
)
from services.process_runtime.registry import get_process_definition
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)


def _stage1_blueprint() -> dict[str, Any]:
    return make_blueprint(
        current_state_analysis=[],
        implementation_overview={
            "requirement_narrative": [
                {"block_id": "blk_narr", "type": "paragraph", "text": "阶段 1 尚未产出。"}
            ],
            "items": [],
        },
        api_contracts=[],
        interaction_flows=[],
        repo_associations=[],
    )


async def _make_artifact():
    return await ArtifactService().create(
        "technical_plan", _stage1_blueprint(), created_by_user_id="tester"
    )


async def _make_session(
    stage: str,
    *,
    process_type: str = "technical_blueprint",
    artifact: Any = None,
    status: str = ConvergenceSessionStatus.RUNNING,
):
    return await ConvergenceSession.objects.acreate(
        process_type=process_type,
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=stage,
        status=status,
        stage_state={},
        current_artifact_version_id=getattr(artifact, "current_version_id", None),
    )


def _events(logs: list[dict], name: str) -> list[dict]:
    return [entry for entry in logs if entry.get("event") == name]


# ═══════════════════════════════════════════════════════════════════════════
# 1-3. 分派契约
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_blueprint_session_gets_blueprint_engine_and_blueprint_driver() -> None:
    session = await _make_session("intake")

    engine, adrive = build_engine_for_session(session)

    assert type(engine.deps.research).__name__ == "BlueprintResearchAdapter"
    assert type(engine.deps.merge).__name__ == "BlueprintMergeAdapter"
    assert adrive is blueprint_resume.adrive_blueprint_session_to_pause_or_terminal


@pytest.mark.asyncio
async def test_technical_plan_session_gets_legacy_engine_and_legacy_driver() -> None:
    session = await _make_session("route", process_type="technical_plan")

    engine, adrive = build_engine_for_session(session)

    assert type(engine.deps.research).__name__ == "ResearchDispatchAdapter"
    assert type(engine.deps.merge).__name__ == "ArchitectMergeAdapter"
    assert adrive is legacy_resume.adrive_convergence_session_to_pause_or_terminal


def test_dispatcher_is_a_plain_sync_function() -> None:
    """⛔ 不写成 async：两个工厂皆同步、``process_type`` 是已加载字段、零 ORM 访问。"""
    import inspect

    assert not inspect.iscoroutinefunction(build_engine_for_session)


@pytest.mark.asyncio
async def test_unknown_process_type_falls_back_to_legacy_and_is_loud() -> None:
    """⛔ 不抛：将来注册第五个 process 时抛异常会让整条链直接崩。"""
    session = SimpleNamespace(id=uuid.uuid4(), process_type="whatever")

    with capture_logs() as logs:
        engine, adrive = build_engine_for_session(session)

    assert adrive is legacy_resume.adrive_convergence_session_to_pause_or_terminal
    assert type(engine.deps.merge).__name__ == "ArchitectMergeAdapter"
    hits = _events(logs, "engine_dispatch_unknown_process_type")
    assert len(hits) == 1
    assert hits[0]["process_type"] == "whatever"
    assert hits[0]["category"] == "caller" and hits[0]["component"] == "process_runtime"


@pytest.mark.asyncio
async def test_legacy_flags_are_never_forwarded_into_the_blueprint_factory() -> None:
    """``build_blueprint_engine`` 只接两个形参、蓝图链根本没有 ``clarify`` dep。"""
    session = await _make_session("intake")

    with capture_logs() as logs:
        engine, _adrive = build_engine_for_session(
            session, skip_clarification=True, force_confirm=True
        )

    assert getattr(engine.deps, "clarify", None) is None
    flags = {entry["flag"] for entry in _events(logs, "blueprint_engine_ignored_legacy_flag")}
    assert flags == {"skip_clarification", "force_confirm"}


# ═══════════════════════════════════════════════════════════════════════════
# 4-6. 三条变异用例（期望值按 Wave 0 探针实测校准）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mutation_a_wrong_factory_at_repo_research_is_rejected() -> None:
    """⭐ 变异 A：错工厂在 ``repo_research`` 拿到 ``ResearchDispatchAdapter`` ⇒ 当场拒。

    删掉 ``_h_bp_repo_research`` 的自检 ⇒ 会一路穿到 ``reroute`` 撞 ``AttributeError``
    落 FAILED（Wave 0 探针实测），本用例转红。
    """
    artifact = await _make_artifact()
    session = await _make_session("repo_research", artifact=artifact)
    wrong_engine = build_orchestration_engine()  # ⚠️ 错工厂（唯一被改的变量）
    before = await ArtifactVersion.objects.acount()

    with capture_logs() as logs:
        outcome = await bp._h_bp_repo_research(session, wrong_engine)

    # (c) 出边是 needs_clarification **且** 有一条 blueprint_stage_wrong_adapter
    assert outcome.event == "needs_clarification"
    stages = get_process_definition("technical_blueprint").stages
    assert outcome.event in stages["repo_research"].transitions, (
        "未登记的 event 会让 transition 直接 raise ValueError 打穿续驱器"
    )
    hits = _events(logs, "blueprint_stage_wrong_adapter")
    assert len(hits) == 1
    assert hits[0]["stage"] == "repo_research"
    assert hits[0]["got"] == "ResearchDispatchAdapter"
    # (b) ArtifactVersion 计数与调用前相等
    assert await ArtifactVersion.objects.acount() == before

    # 出边可被 engine 真正落库（不抛、不落终态）
    await wrong_engine.advance(session)
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "repo_research"
    assert fresh.status == ConvergenceSessionStatus.WAITING_EVENT
    assert await ArtifactVersion.objects.acount() == before


@pytest.mark.asyncio
async def test_mutation_b_wrong_factory_at_merge_never_writes_a_v0_version() -> None:
    """⭐ 变异 B（最坏形态）：``ArchitectMergeAdapter`` 绝不能往蓝图会话落 v0 content。

    删掉 ``_h_bp_merge`` 的自检 ⇒ ``_handle_pass`` 经 ``ArtifactService.create`` 落一份
    ``schema_version != "blueprint/v1"`` 的版本、并把会话产物指针钉过去，本用例转红。
    """
    artifact = await _make_artifact()
    session = await _make_session("merge", artifact=artifact)
    wrong_engine = build_orchestration_engine()  # ⚠️ 错工厂
    before = await ArtifactVersion.objects.acount()

    with capture_logs() as logs:
        outcome = await bp._h_bp_merge(session, wrong_engine)

    assert outcome.event == "needs_clarification"
    assert outcome.current_artifact_version is None, "⛔ 产物指针绝不被旧链版本钉走"
    hits = _events(logs, "blueprint_stage_wrong_adapter")
    assert len(hits) == 1
    assert hits[0]["stage"] == "merge"
    assert hits[0]["got"] == "ArchitectMergeAdapter"
    # (b) 计数不变，且全库不存在任何非 blueprint/v1 的版本
    assert await ArtifactVersion.objects.acount() == before
    schema_versions = {
        str((content or {}).get("schema_version") or "")
        async for content in ArtifactVersion.objects.values_list("content", flat=True)
    }
    assert schema_versions == {"blueprint/v1"}


@pytest.mark.asyncio
async def test_mutation_c_wrong_driver_is_a_no_op_not_a_failure() -> None:
    """⭐ 变异 C：旧 driver 驱蓝图会话 ⇒ no-op。

    删掉 ``resume.py`` 的对称守卫 ⇒ ``ahas_pending`` 对蓝图恒 False、三个 pausable stage
    一个都短路不了，会话被推到 ``max_steps`` 落 ``advance_step_limit`` FAILED，本用例转红。
    """
    artifact = await _make_artifact()
    session = await _make_session("spec_gate", artifact=artifact)
    before_status = session.status
    before_stage = session.current_stage

    with capture_logs() as logs:
        result = await legacy_resume.adrive_convergence_session_to_pause_or_terminal(
            build_blueprint_engine(), session
        )

    hits = _events(logs, "wrong_driver_for_blueprint_session")
    assert len(hits) == 1
    assert hits[0]["process_type"] == "technical_blueprint"
    assert hits[0]["category"] == "caller" and hits[0]["component"] == "process_runtime"

    fresh = await ConvergenceSession.objects.aget(id=result.id)
    assert (fresh.status, fresh.current_stage) == (before_status, before_stage)
    assert str((fresh.error or {}).get("reason") or "") != "advance_step_limit"


# ═══════════════════════════════════════════════════════════════════════════
# 7. 反向对照（证明第 6 条的断言不是恒真、守卫只挡蓝图）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_legacy_driver_still_advances_a_technical_plan_session() -> None:
    """⛔ 只挡蓝图会话：``plan_deepen`` 等非蓝图调用方也走这条 driver。"""
    session = await _make_session("route", process_type="technical_plan")
    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    await legacy_resume.adrive_convergence_session_to_pause_or_terminal(
        engine, session, max_steps=1
    )

    assert advance.await_count >= 1, "非蓝图会话必须照常推进（证明守卫非恒真）"


@pytest.mark.asyncio
async def test_blueprint_driver_still_refuses_a_technical_plan_session() -> None:
    """既有反方向守卫零回归（``blueprint_resume.py:132-143``）。"""
    session = await _make_session("route", process_type="technical_plan")
    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    with capture_logs() as logs:
        result = await blueprint_resume.adrive_blueprint_session_to_pause_or_terminal(
            engine, session, max_steps=1
        )

    assert advance.await_count == 0
    assert _events(logs, "blueprint_resume_wrong_process_type")
    fresh = await ConvergenceSession.objects.aget(id=result.id)
    assert fresh.status == ConvergenceSessionStatus.RUNNING


@pytest.mark.asyncio
async def test_technical_plan_entry_used_buckets_by_entry_key_not_entrypoint() -> None:
    """⭐ 退役观察事件按**独立的** ``entry_key`` 分桶。

    MCP 入口给 ``start_orchestration`` 传的 ``entrypoint`` 实测是 ``"workflow"``
    （``orchestration_delegate.py:171-178`` 的既有约定）⇒ 按 ``entrypoint`` 聚合会把 MCP
    记进 workflow 桶，**静默且永不报错**。
    """
    from services.process_runtime.entrypoint import start_orchestration

    with capture_logs() as logs:
        session = await start_orchestration(
            "workflow", "把飞书需求跑成 PR", entry_key="mcp", initiated_by_user_id="u-1"
        )

    hits = _events(logs, "technical_plan_entry_used")
    assert len(hits) == 1
    assert hits[0]["entry_key"] == "mcp"
    assert hits[0]["entrypoint"] == "workflow", "entrypoint 的既有取值一字不改"
    assert hits[0]["session_id"] == str(session.id)
    assert hits[0]["initiated_by_user_id"] == "u-1"


@pytest.mark.asyncio
async def test_entry_key_defaults_to_unknown_before_116_03_wires_the_callers() -> None:
    from services.process_runtime.entrypoint import start_orchestration

    with capture_logs() as logs:
        await start_orchestration("chat", "自然语言需求")

    hits = _events(logs, "technical_plan_entry_used")
    assert len(hits) == 1
    assert hits[0]["entry_key"] == "unknown"
