"""ArchitectMergeAdapter 测试（MERGE-01/02/03，Chassis v2 · P2）。

注入 **mock synthesizer**（不依赖真实 LLM），真实 ConvergenceSession/RepoResearchTask/
PartialPlan 直建数据。覆盖 pass / fail / 降级 / INV-2(work_item=None) 路径
+ engine↔adapter 端到端集成（ProcessEngine + stage graph）。

pass 分支经 ``ArtifactService`` 落 ``technical_plan`` ArtifactVersion（取代旧
TechnicalPlan/PlanVersion）。adapter **不再自写** session.current_artifact_version 指针——
该指针由 ``ProcessEngine`` 经 transition 在 merge 返回后落库；故 adapter-only 用例验证
``result["artifact_version_id"]`` 与 ArchitectMerge，engine-e2e 用例才验证 session 指针。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ArchitectMerge,
    ArchitectMergeStatus,
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from services.process_runtime import ArchitectMergeAdapter

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
    """schema 非法但跨仓语义可过：execution_plan 某项缺 repository_id（CR-01 破口场景）。"""
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


def _make_session_with_partials(*, work_item=None, valid: bool = True) -> ConvergenceSession:
    """建 merge stage 的 session + 1 个 valid PartialPlan（经 ORM 直建）。"""
    session = ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
        work_item=work_item,
        stage_state={"decomposition": {"requirement_text": "做登录"}},
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


def _engine(adapter: ArchitectMergeAdapter, **extra_deps):
    from types import SimpleNamespace

    from delivery.services import ConvergenceSessionService
    from services.process_runtime import ProcessEngine

    deps = SimpleNamespace(merge=adapter, **extra_deps)
    return ProcessEngine(session_service=ConvergenceSessionService(), deps=deps)


@pytest.mark.asyncio
async def test_merge_pass_path() -> None:
    """pass：合法 MergedPlan → technical_plan ArtifactVersion + ArchitectMerge(passed)
    + technical_plan.merge.started/completed 事件。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_valid_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    assert result["artifact_version_id"]
    av = await ArtifactVersion.objects.aget(id=result["artifact_version_id"])
    assert av.content["title"] == "跨仓登录改造"
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.PASSED
    assert merge_row.merged_artifact_version is not None
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "technical_plan.merge.started" in events
    assert "technical_plan.merge.completed" in events


@pytest.mark.asyncio
async def test_merge_fail_path() -> None:
    """fail：不合法 MergedPlan（成环）→ 无 artifact、ArchitectMerge(failed) + report
    + technical_plan.validation.failed 事件。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    assert "back_target" in result
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.merged_artifact_version is None
    assert merge_row.validation_report
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "technical_plan.validation.failed" in events


@pytest.mark.asyncio
async def test_merge_schema_invalid_handled_as_failure() -> None:
    """CR-01：schema 非法 MergedPlan 被 §7 schema 闸口拦为验证失败（failed report +
    technical_plan.validation.failed 事件 + 无 artifact），而非崩 terminal。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_schema_invalid_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    assert "back_target" in result
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.merged_artifact_version is None
    checks = [e.get("check") for e in merge_row.validation_report.get("errors", [])]
    assert "schema" in checks
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "technical_plan.validation.failed" in events


@pytest.mark.asyncio
async def test_merge_create_artifact_schema_drift_degraded() -> None:
    """CR-01 防御补强：即便产物过 §7 闸口 + 跨仓校验，ArtifactService.create 内若漂移再抛
    ArtifactContentInvalid，也转为验证失败（不崩 terminal、不留 artifact）。"""
    from delivery.services import ArtifactContentInvalid

    session = await _amake_session_with_partials()
    artifact_service = AsyncMock()
    artifact_service.create = AsyncMock(side_effect=ArtifactContentInvalid("schema drift"))
    adapter = ArchitectMergeAdapter(
        synthesizer=_synth(_valid_merged_plan()), artifact_service=artifact_service
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED
    assert merge_row.merged_artifact_version is None


@pytest.mark.asyncio
async def test_e2e_engine_merge_schema_invalid_back_transition() -> None:
    """CR-01 端到端：engine.advance(merge) → schema 非法 → session 回退 clarify（§14），
    **绝不**崩 terminal failed；ArchitectMerge(failed) + 无 artifact 指针。"""
    from delivery.models import ConvergenceSessionStatus

    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_schema_invalid_merged_plan()))
    engine = _engine(adapter)

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.status != ConvergenceSessionStatus.FAILED
    assert reloaded.current_artifact_version_id is None
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
    assert merge_row.merged_artifact_version is None


@pytest.mark.asyncio
async def test_merge_inv2_work_item_none() -> None:
    """INV-2：session.work_item=None（chat）→ pass 路径 artifact.work_item is None。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_valid_merged_plan()))

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    av = await ArtifactVersion.objects.select_related("artifact").aget(
        id=result["artifact_version_id"]
    )
    assert av.artifact.work_item_id is None


@pytest.mark.asyncio
async def test_e2e_engine_merge_pass() -> None:
    """端到端：engine.advance(merge) → adapter pass → session done + current_artifact_version。"""
    from delivery.models import ConvergenceSessionStatus

    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_valid_merged_plan()))
    engine = _engine(adapter)

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.status == ConvergenceSessionStatus.DONE
    assert reloaded.current_artifact_version_id is not None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.PASSED


@pytest.mark.asyncio
async def test_e2e_engine_merge_fail_reclarify() -> None:
    """端到端：engine.advance → adapter fail（成环，attempt 0）→ session 回退
    clarify + ArchitectMerge(failed) + 无 artifact 指针。"""
    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    engine = _engine(adapter)

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.current_artifact_version_id is None
    merge_row = await ArchitectMerge.objects.aget(session_id=session.id)
    assert merge_row.validation_status == ArchitectMergeStatus.FAILED


@pytest.mark.asyncio
async def test_merge_fail_reclarify_creates_clarification() -> None:
    """WR-02：merge 校验失败回退 clarify（attempt 0）→ 主动建一条描述校验失败的 pending
    澄清轮 + emit clarification.asked，使回退落到真实 HITL 澄清（非空操作）。"""
    from delivery.models import Clarification, ClarificationQuestion

    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    result = await adapter.merge(session)

    assert result["validation_status"] == "failed"
    assert result["back_target"] == "clarify"
    assert result["attempt"] == 0
    clar = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).afirst()
    assert clar is not None
    q = await ClarificationQuestion.objects.filter(clarification_id=clar.id).afirst()
    assert q is not None
    assert "校验" in q.question
    events = [c.args[0] for c in spy.call_args_list if c.args]
    assert "clarification.asked" in events


@pytest.mark.asyncio
async def test_merge_fail_reclarify_bounded_when_attempt_exhausted() -> None:
    """WR-02 有界：attempt 已达上限时不建回退澄清轮（engine 将直接落 failed 终态）。"""
    from delivery.models import Clarification

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
    assert await Clarification.objects.filter(session_id=session.id).acount() == 0


@pytest.mark.asyncio
async def test_merge_reclarify_meaningful_with_one_round_guard() -> None:
    """WR-02 × CR-01：merge 失败回退 clarify 建 pending → 真实 ClarifyAdapter 据 pending
    保持挂起；答复后单轮 guard 放行 research（不再追问）——回退真正驱动一轮 HITL 而非空转。"""
    from unittest.mock import patch

    from delivery.models import (
        Clarification,
        ClarificationQuestion,
        ConvergenceSessionStatus,
    )
    from delivery.services import ClarificationService
    from services.process_runtime import ClarifyAdapter

    session = await _amake_session_with_partials()
    adapter = ArchitectMergeAdapter(synthesizer=_synth(_cyclic_merged_plan()))
    engine = _engine(adapter, clarify=ClarifyAdapter())

    _GEN = "services.process_runtime.clarify_adapter.agenerate_clarification_questions"
    with patch(_GEN, new=AsyncMock(return_value=[])):
        # merge → 校验失败 → 回退 clarify（WR-02 建 pending），engine 推进 current_stage=clarify
        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)
        assert session.current_stage == "clarify"
        pending = await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).afirst()
        assert pending is not None

        # 再 advance：clarify stage 据 pending 保持挂起（waiting_clarification）
        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)
        assert session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION

        # 答复回退澄清 → 单轮 guard 放行 research，不新建第二条澄清
        q = await ClarificationQuestion.objects.filter(clarification_id=pending.id).afirst()
        await ClarificationService().answer_round(
            pending, [{"question_id": q.id, "selected": None, "freeform_text": "复用既有契约 X"}]
        )
        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)

    assert session.current_stage == "research"
    assert await Clarification.objects.filter(session_id=session.id).acount() == 1


# ---- async fixtures (ORM 建数据经 sync_to_async 桥接) ----

from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _amake_session_with_partials_sync(work_item=None, valid: bool = True) -> ConvergenceSession:
    return _make_session_with_partials(work_item=work_item, valid=valid)


async def _amake_session_with_partials(*, work_item=None, valid: bool = True) -> ConvergenceSession:
    return await _amake_session_with_partials_sync(work_item, valid)
