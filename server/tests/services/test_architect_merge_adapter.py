"""ArchitectMergeAdapter 测试（Phase 40-02 Task 1/3，MERGE-01/02/03）。

注入 **mock synthesizer**（不依赖真实 LLM），真实 PlanSession/RepoResearchTask/
PartialPlan 直建数据。覆盖 pass / fail / 降级 / INV-2(work_item=None) 路径
+ engine↔adapter 端到端集成（Task 3）。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ArchitectMerge,
    ArchitectMergeStatus,
    PartialPlan,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
    TechnicalPlan,
)
from repositories.models import Repository
from services.plan_orchestration import ArchitectMergeAdapter, PlanOrchestrationEngine

# transaction=True：本文件 async 用例经 sync_to_async 桥接在独立线程连接建数据
# （含 indexed Repository），普通 @pytest.mark.django_db（rollback）无法回滚跨线程连接
# 的提交，会泄漏 indexed Repository 行污染后续全仓计数用例。TransactionTestCase
# 在 teardown TRUNCATE 全表，确保跨连接提交也被清理。
pytestmark = pytest.mark.django_db(transaction=True)


def _valid_merged_plan() -> dict[str, Any]:
    return {
        "title": "跨仓登录改造",
        "summary": "后端加鉴权接口，前端接入",
        "api_contracts": [{"name": "POST /login", "repo": "backend"}],
        "dependency_dag": {"frontend": ["backend"], "backend": []},
        "data_migrations": [{"repository_id": "backend"}],
        "compat_risks": [],
        "release_order": ["backend", "frontend"],
        "rollback_plan": {"backend": "回滚迁移", "frontend": "回滚发布"},
        "execution_plan": [
            {
                "id": "t-backend",
                "name": "后端鉴权接口",
                "repository_id": "backend",
                "repository_name": "backend-repo",
                "branch_strategy": "feature",
                "coding_instruction": "实现 POST /login",
                "dependencies": [],
                "api_contracts_exposed": ["POST /login"],
            },
            {
                "id": "t-frontend",
                "name": "前端登录页",
                "repository_id": "frontend",
                "repository_name": "frontend-repo",
                "branch_strategy": "feature",
                "coding_instruction": "接入 POST /login",
                "dependencies": ["t-backend"],
                "dependencies_on_other_repos": ["POST /login"],
            },
        ],
    }


def _cyclic_merged_plan() -> dict[str, Any]:
    """成环 dependency_dag → PlanValidator 不合法。"""
    content = _valid_merged_plan()
    content["dependency_dag"] = {"a": ["b"], "b": ["a"]}
    return content


def _schema_invalid_merged_plan() -> dict[str, Any]:
    """schema 非法但跨仓语义可过：execution_plan 某项缺 repository_id（CR-01 破口场景）。

    缺 repository_id 不触发 validate_plan 的任何跨仓 error（契约/回滚均不把该项计入），
    但 validate_merged_plan → validate_technical_plan schema 必填校验会拒——必须被 §7
    schema 闸口拦下走优雅降级，而非冲到 create_from 抛 PlanContentInvalid 崩 terminal。
    """
    content = _valid_merged_plan()
    del content["execution_plan"][0]["repository_id"]
    return content


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_session_with_partials(*, work_item=None, valid: bool = True) -> PlanSession:
    """建 merging 态 session + 1 个 valid PartialPlan（经 ORM 直建）。"""
    session = PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.MERGING,
        work_item=work_item,
    )
    repo = _make_repo()
    task = RepoResearchTask.objects.create(
        session=session, repository=repo, status=RepoResearchTaskStatus.DONE
    )
    PartialPlan.objects.create(
        research_task=task,
        content={"repository_id": "backend", "research_summary": "x"},
        valid=valid,
    )
    return session


def _synth(return_value: dict | None = None, side_effect=None):
    synth = AsyncMock()
    synth.synthesize = AsyncMock(return_value=return_value, side_effect=side_effect)
    return synth


@pytest.mark.asyncio
async def test_merge_pass_path() -> None:
    """pass：合法 MergedPlan → canonical(origin=orchestration) + current_plan_version
    + ArchitectMerge(passed) + plan.merge.started/completed 事件。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_valid_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    assert result["plan_version_id"]
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is not None
    # 经 session.current_plan_version 定位 canonical（session-scoped，避免 async 跨测泄漏干扰）
    plan = await TechnicalPlan.objects.aget(current_version_id=reloaded.current_plan_version)
    assert plan.origin == "orchestration"
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.PASSED
    assert merge_row.merged_plan_version is not None
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "plan.merge.started" in events
    assert "plan.merge.completed" in events


@pytest.mark.asyncio
async def test_merge_fail_path() -> None:
    """fail：不合法 MergedPlan（成环）→ 无 canonical、ArchitectMerge(failed) + report、
    current_plan_version 仍 None、plan.validation.failed 事件。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    assert "back_target" in result
    # 不落 canonical（session-scoped）：current_plan_version 仍 None + ArchitectMerge 无版本
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.merged_plan_version is None
    assert merge_row.validation_report
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "plan.validation.failed" in events


@pytest.mark.asyncio
async def test_merge_schema_invalid_handled_as_failure() -> None:
    """CR-01：schema 非法 MergedPlan（execution_plan 项缺 repository_id）被 §7 schema 闸口
    拦为验证失败（failed report + plan.validation.failed 事件 + 无 canonical），而非冲到
    create_from 抛 PlanContentInvalid 崩 terminal。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_schema_invalid_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    assert "back_target" in result
    # 不落 canonical：current_plan_version 仍 None + ArchitectMerge(failed)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.merged_plan_version is None
    # report 标记 schema check
    checks = [e.get("check") for e in merge_row.validation_report.get("errors", [])]
    assert "schema" in checks
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "plan.validation.failed" in events


@pytest.mark.asyncio
async def test_merge_create_from_schema_drift_degraded() -> None:
    """CR-01 防御补强：即便产物过 §7 闸口 + 跨仓校验，create_from 内 validate_technical_plan
    若漂移再抛 PlanContentInvalid，也转为验证失败（不崩 terminal、不留 canonical）。"""
    from delivery.services.technical_plan_service import PlanContentInvalid

    session = await _amake_session_with_partials()
    plan_service = AsyncMock()
    plan_service.create_from = AsyncMock(side_effect=PlanContentInvalid("schema drift"))
    adapter = ArchitectMergeAdapter(
        synthesizer=_synth(_valid_merged_plan()), plan_service=plan_service
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.merged_plan_version is None


@pytest.mark.asyncio
async def test_e2e_engine_merge_schema_invalid_back_transition() -> None:
    """CR-01 端到端：engine.advance(merging) → schema 非法 → session 回退 clarifying（§14），
    **绝不**崩 terminal failed；ArchitectMerge(failed) + 无 canonical。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_schema_invalid_merged_plan()))
    engine = PlanOrchestrationEngine(merge=adapter)

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    assert reloaded.status != PlanSessionStatus.FAILED
    assert reloaded.current_plan_version is None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED


@pytest.mark.asyncio
async def test_merge_synthesis_failure_degraded() -> None:
    """降级：synthesizer 抛异常 → 不崩、ArchitectMerge(failed, reason=synthesis_failed)。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(
        synthesizer=_synth(side_effect=RuntimeError("llm down"))
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.validation_report.get("reason") == "synthesis_failed"
    assert merge_row.merged_plan_version is None
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is None


@pytest.mark.asyncio
async def test_merge_inv2_work_item_none() -> None:
    """INV-2：session.work_item=None（chat）→ pass 路径 canonical.work_item is None。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_valid_merged_plan()))

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    reloaded = await PlanSession.objects.aget(id=session.id)
    plan = await TechnicalPlan.objects.aget(current_version_id=reloaded.current_plan_version)
    assert plan.work_item_id is None


@pytest.mark.asyncio
async def test_e2e_engine_merge_pass() -> None:
    """端到端（Task 3）：engine.advance(merging) → adapter pass → session done + canonical。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_valid_merged_plan()))
    engine = PlanOrchestrationEngine(merge=adapter)

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.DONE
    assert reloaded.current_plan_version is not None
    plan = await TechnicalPlan.objects.aget(current_version_id=reloaded.current_plan_version)
    assert plan.origin == "orchestration"
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.PASSED


@pytest.mark.asyncio
async def test_e2e_engine_merge_fail_reclarify() -> None:
    """端到端（Task 3）：engine.advance → adapter fail（成环，attempt 0）→ session 回退
    clarifying + ArchitectMerge(failed) + 无 canonical。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    engine = PlanOrchestrationEngine(merge=adapter)

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    assert reloaded.current_plan_version is None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED


@pytest.mark.asyncio
async def test_merge_fail_reclarify_creates_clarification() -> None:
    """WR-02：merge 校验失败回退 clarifying（attempt 0）→ 主动建一条描述校验失败的 pending
    Clarification + emit clarification.asked，使回退落到真实 HITL 澄清（非空操作）。"""
    from delivery.models import Clarification

    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    assert result["back_target"] == "clarifying"
    assert result["attempt"] == 0
    clar = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).afirst()
    assert clar is not None
    assert "校验" in clar.question
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "clarification.asked" in events


@pytest.mark.asyncio
async def test_merge_fail_reclarify_bounded_when_attempt_exhausted() -> None:
    """WR-02 有界：attempt 已达上限时不建回退 Clarification（engine 将直接落 failed 终态，
    不应留孤儿 pending）——防无限循环。"""
    from delivery.models import ArchitectMerge, ArchitectMergeStatus, Clarification

    session = await _amake_session_with_partials()
    # 预置一条 ArchitectMerge → 本次 merge 的 attempt = MAX_MERGE_RETRIES
    await ArchitectMerge.objects.acreate(
        session=session,
        validation_status=ArchitectMergeStatus.FAILED,
        validation_report={},
        attempt=0,
    )
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))

    result = await adapter.merge(session)

    assert result["attempt"] == ArchitectMergeAdapter.MAX_MERGE_RETRIES
    # 未建回退 Clarification（有界，避免无限澄清循环）
    assert await Clarification.objects.filter(session_id=session.id).acount() == 0


@pytest.mark.asyncio
async def test_merge_reclarify_meaningful_with_one_round_guard() -> None:
    """WR-02 × CR-01：merge 失败回退 clarifying 建 pending → 真实 ClarifyAdapter 据 pending
    保持 clarifying 挂起；答复后单轮 guard 放行 researching（不再追问）——回退真正驱动一轮
    HITL 而非空转，且有界（不二次澄清）。"""
    from delivery.models import Clarification
    from delivery.services import ClarificationService
    from services.plan_orchestration import ClarifyAdapter

    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    engine = PlanOrchestrationEngine(merge=adapter, clarify=ClarifyAdapter())

    # merging → 校验失败 → 回退 clarifying（WR-02 建 pending）
    await engine.advance(session)
    session = await PlanSession.objects.aget(id=session.id)
    assert session.status == PlanSessionStatus.CLARIFYING
    pending = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).afirst()
    assert pending is not None

    # 答复回退澄清 → 再 advance：单轮 guard 放行 researching，且不新建第二条澄清
    await ClarificationService().answer_clarification(pending, "补充：复用既有契约 X")
    await engine.advance(session)
    session = await PlanSession.objects.aget(id=session.id)
    assert session.status == PlanSessionStatus.RESEARCHING
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


# ---- async fixtures (ORM 建数据经 sync_to_async 桥接) ----

from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _amake_session_with_partials_sync(work_item=None, valid: bool = True) -> PlanSession:
    return _make_session_with_partials(work_item=work_item, valid=valid)


async def _amake_session_with_partials(*, work_item=None, valid: bool = True) -> PlanSession:
    return await _amake_session_with_partials_sync(work_item, valid)
