"""agenerate_specs_for_plan + LLMSddSpecSynthesizer 测试（Phase 49-03 Task 3）。

mock synthesizer（不依赖真实 LLM），真实 PlanSession/PlanVersion/Repository/WorkItem
直建数据。覆盖 D-49-4：

- SDD 仓产 spec 全链路（SddSpec(draft) + Document(sdd_spec) + DocumentVersion + 关联 + emit）。
- 非 SDD 仓零产（no-op，mock synthesizer 未被调用）。
- 无 SDD 仓 no-op（返回 []）。
- 逐仓 try/except 隔离（仓 A 抛异常、仓 B 正常 → 仅仓 B 产 spec）。
- emit spec.drafted（PlanSessionEvent 落库 + payload 含 spec_id/repository_id/plan_version_id）。
- 幂等（连调两次不翻倍、不新增 Document/DocumentVersion）。

异步 + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    Document,
    DocumentType,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionEvent,
    PlanSessionStatus,
    PlanVersion,
    SddSpec,
    SddSpecStatus,
    TechnicalPlan,
    TechnicalPlanOrigin,
    WorkItem,
    WorkItemOrigin,
)
from repositories.models import Repository
from services.plan_orchestration import agenerate_specs_for_plan

pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo(*, sdd: bool) -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
        facets={"methodology": "SDD"} if sdd else {},
    )


def _merged_plan(repo_ids: list[str]) -> dict[str, Any]:
    return {
        "title": "跨仓改造",
        "summary": "x",
        "execution_plan": [
            {
                "id": f"t-{i}",
                "name": f"task-{i}",
                "repository_id": rid,
                "repository_name": rid,
                "branch_strategy": "feature",
            }
            for i, rid in enumerate(repo_ids)
        ],
    }


def _make_session_with_plan(
    *, repo_ids: list[str], work_item: WorkItem | None = None
) -> tuple[PlanSession, str]:
    """建 canonical PlanVersion(content=MergedPlan) + PlanSession(current_plan_version=pv)。"""
    plan = TechnicalPlan.objects.create(origin=TechnicalPlanOrigin.ORCHESTRATION)
    pv = PlanVersion.objects.create(
        plan=plan, version=1, content=_merged_plan(repo_ids), content_hash="h"
    )
    session = PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.MERGING,
        work_item=work_item,
        current_plan_version=pv.id,
        decomposition={"requirement_text": "做个登录"},
    )
    return session, str(pv.id)


from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _amake_repo(*, sdd: bool) -> Repository:
    return _make_repo(sdd=sdd)


@sync_to_async
def _amake_work_item() -> WorkItem:
    return WorkItem.objects.create(
        feishu_project_key="622c10eb5daaee81db915189",
        work_item_type="story",
        work_item_id=7010225564,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


@sync_to_async
def _amake_session_with_plan(
    *, repo_ids: list[str], work_item: WorkItem | None = None
) -> tuple[PlanSession, str]:
    return _make_session_with_plan(repo_ids=repo_ids, work_item=work_item)


def _mock_synth(return_value: str = "## Why\nspec\n", side_effect=None) -> AsyncMock:
    synth = AsyncMock()
    synth.synthesize = AsyncMock(return_value=return_value, side_effect=side_effect)
    return synth


async def test_sdd_repo_produces_spec_full_chain() -> None:
    """SDD 仓 → 产 1 个 SddSpec(draft) + Document(sdd_spec) + 关联 + emit spec.drafted。"""
    repo = await _amake_repo(sdd=True)
    work_item = await _amake_work_item()
    session, pv_id = await _amake_session_with_plan(
        repo_ids=[str(repo.id)], work_item=work_item
    )
    synth = _mock_synth()

    produced = await agenerate_specs_for_plan(pv_id, synthesizer=synth)

    assert len(produced) == 1
    assert await SddSpec.objects.acount() == 1
    spec = await SddSpec.objects.aget(id=produced[0])
    assert spec.status == SddSpecStatus.DRAFT
    assert spec.repository_id == repo.id
    assert str(spec.plan_version_id) == pv_id
    assert spec.work_item_id == work_item.id
    doc = await Document.objects.aget(pk=spec.document_id)
    assert doc.document_type == DocumentType.SDD_SPEC
    # emit spec.drafted 落 PlanSessionEvent + payload
    ev = await PlanSessionEvent.objects.filter(session_id=session.id, event="spec.drafted").afirst()
    assert ev is not None
    assert ev.payload["spec_id"] == str(spec.id)
    assert ev.payload["repository_id"] == str(repo.id)
    assert ev.payload["plan_version_id"] == pv_id


async def test_non_sdd_repo_produces_nothing() -> None:
    """非 SDD 仓 → no-op，SddSpec 计数 0，synthesizer 未被调用。"""
    repo = await _amake_repo(sdd=False)
    _session, pv_id = await _amake_session_with_plan(repo_ids=[str(repo.id)])
    synth = _mock_synth()

    produced = await agenerate_specs_for_plan(pv_id, synthesizer=synth)

    assert produced == []
    assert await SddSpec.objects.acount() == 0
    assert synth.synthesize.await_count == 0


async def test_no_matching_repo_is_noop() -> None:
    """execution_plan repo_id 无匹配 Repository → 返回 []。"""
    _session, pv_id = await _amake_session_with_plan(repo_ids=[str(uuid.uuid4())])
    synth = _mock_synth()

    produced = await agenerate_specs_for_plan(pv_id, synthesizer=synth)

    assert produced == []
    assert await SddSpec.objects.acount() == 0


async def test_per_repo_isolation_one_fails_other_succeeds() -> None:
    """两 SDD 仓：仓 A synthesize 抛异常、仓 B 正常 → 仅仓 B 产 spec，仓 A 吞为 warning。"""
    repo_a = await _amake_repo(sdd=True)
    repo_b = await _amake_repo(sdd=True)
    _session, pv_id = await _amake_session_with_plan(
        repo_ids=[str(repo_a.id), str(repo_b.id)]
    )

    async def _side_effect(*, requirement, merged_plan, repository):
        if repository.id == repo_a.id:
            raise RuntimeError("llm down for A")
        return "## Why\nspec B\n"

    synth = AsyncMock()
    synth.synthesize = AsyncMock(side_effect=_side_effect)

    produced = await agenerate_specs_for_plan(pv_id, synthesizer=synth)

    assert len(produced) == 1
    assert await SddSpec.objects.acount() == 1
    spec = await SddSpec.objects.aget(id=produced[0])
    assert spec.repository_id == repo_b.id


async def test_idempotent_rerun_no_duplicate() -> None:
    """同 pv 连调两次 → SddSpec 总数为 SDD 仓数（不翻倍），Document/DocumentVersion 不新增。"""
    repo = await _amake_repo(sdd=True)
    _session, pv_id = await _amake_session_with_plan(repo_ids=[str(repo.id)])
    synth = _mock_synth()

    await agenerate_specs_for_plan(pv_id, synthesizer=synth)
    await agenerate_specs_for_plan(pv_id, synthesizer=synth)

    assert await SddSpec.objects.acount() == 1
    assert await Document.objects.filter(document_type=DocumentType.SDD_SPEC).acount() == 1


async def test_missing_plan_version_returns_empty() -> None:
    """plan_version_id 不存在 → 返回 []（防御）。"""
    synth = _mock_synth()
    produced = await agenerate_specs_for_plan(str(uuid.uuid4()), synthesizer=synth)
    assert produced == []
