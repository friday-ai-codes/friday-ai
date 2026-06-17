"""SddSpecService.link_implementation_pr 单一写入入口测试（Phase 52-01，LINK-01，D-52-2）。

覆盖 D-52-2 spec→PR 回填收口（INV-6）的 6 类行为：

- SDD 仓回填：(plan_version_id, repository_id) 命中 SddSpec → append {pr_url,
  repository_id, linked_at} 到 implementation_prs。
- 转 implemented：命中 spec 当前 status=approved → 经 mark_implemented 语义流转
  approved→implemented（单一事务内）。
- 非 SDD no-op：(plan_version_id, repository_id) 无 SddSpec → 直接返回（无写入、无异常）。
- 去重幂等：同一 pr_url 重复调用不重复追加、不重复触发状态流转。
- 非 approved 宽容：draft/in_review/implemented/archived → 仅记 PR ref，不强转状态。
- 单一事务 + INV-6：append + 状态流转在同一 transaction.atomic；写入只经本 service。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import (
    PlanVersion,
    SddSpec,
    SddSpecStatus,
    TechnicalPlan,
    TechnicalPlanOrigin,
)
from delivery.services import SddSpecService
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _make_plan_version() -> PlanVersion:
    plan = await TechnicalPlan.objects.acreate(origin=TechnicalPlanOrigin.CHAT)
    return await PlanVersion.objects.acreate(plan=plan, version=1, content={}, content_hash="h")


async def _make_spec(
    *, status: str = SddSpecStatus.APPROVED, repo=None, pv=None
) -> SddSpec:
    repo = repo or await _make_repo()
    pv = pv or await _make_plan_version()
    return await SddSpec.objects.acreate(repository=repo, plan_version=pv, status=status)


async def _reload(spec_id) -> SddSpec:
    return await SddSpec.objects.aget(id=spec_id)


# ---- SDD 仓回填 + 转 implemented ----


async def test_link_appends_pr_and_marks_implemented_when_approved() -> None:
    """approved spec：回填 PR ref + approved→implemented 流转。"""
    repo = await _make_repo()
    pv = await _make_plan_version()
    spec = await _make_spec(status=SddSpecStatus.APPROVED, repo=repo, pv=pv)

    await SddSpecService().link_implementation_pr(
        plan_version_id=str(pv.id),
        repository_id=str(repo.id),
        pr_url="https://github.com/test/repo/pull/1",
    )

    reloaded = await _reload(spec.id)
    assert reloaded.status == SddSpecStatus.IMPLEMENTED
    assert len(reloaded.implementation_prs) == 1
    entry = reloaded.implementation_prs[0]
    assert entry["pr_url"] == "https://github.com/test/repo/pull/1"
    assert entry["repository_id"] == str(repo.id)
    assert entry["linked_at"]  # ISO8601 非空


# ---- 非 SDD no-op ----


async def test_link_no_op_when_no_spec() -> None:
    """无 SddSpec（非 SDD 仓）→ no-op：无写入、无异常、零回归。"""
    repo = await _make_repo()
    pv = await _make_plan_version()
    # 故意不建 SddSpec
    await SddSpecService().link_implementation_pr(
        plan_version_id=str(pv.id),
        repository_id=str(repo.id),
        pr_url="https://github.com/test/repo/pull/9",
    )
    assert await SddSpec.objects.acount() == 0


# ---- 去重幂等 ----


async def test_link_idempotent_same_pr_url() -> None:
    """同一 pr_url 重复回填：不重复追加，不重复触发状态流转。"""
    repo = await _make_repo()
    pv = await _make_plan_version()
    spec = await _make_spec(status=SddSpecStatus.APPROVED, repo=repo, pv=pv)
    service = SddSpecService()
    url = "https://github.com/test/repo/pull/2"

    await service.link_implementation_pr(
        plan_version_id=str(pv.id), repository_id=str(repo.id), pr_url=url
    )
    # 第二次（spec 已 implemented）：宽容不强转、pr_url 去重不重复追加
    await service.link_implementation_pr(
        plan_version_id=str(pv.id), repository_id=str(repo.id), pr_url=url
    )

    reloaded = await _reload(spec.id)
    assert len(reloaded.implementation_prs) == 1
    assert reloaded.status == SddSpecStatus.IMPLEMENTED


async def test_link_distinct_pr_urls_append_both() -> None:
    """不同 pr_url 各自追加（多仓/多 PR 可累计）。"""
    repo = await _make_repo()
    pv = await _make_plan_version()
    spec = await _make_spec(status=SddSpecStatus.APPROVED, repo=repo, pv=pv)
    service = SddSpecService()

    await service.link_implementation_pr(
        plan_version_id=str(pv.id), repository_id=str(repo.id),
        pr_url="https://github.com/test/repo/pull/3",
    )
    await service.link_implementation_pr(
        plan_version_id=str(pv.id), repository_id=str(repo.id),
        pr_url="https://github.com/test/repo/pull/4",
    )

    reloaded = await _reload(spec.id)
    assert {e["pr_url"] for e in reloaded.implementation_prs} == {
        "https://github.com/test/repo/pull/3",
        "https://github.com/test/repo/pull/4",
    }


# ---- 非 approved 宽容 ----


@pytest.mark.parametrize(
    "status",
    [
        SddSpecStatus.DRAFT,
        SddSpecStatus.IN_REVIEW,
        SddSpecStatus.IMPLEMENTED,
        SddSpecStatus.ARCHIVED,
    ],
)
async def test_link_non_approved_records_pr_without_transition(status: str) -> None:
    """非 approved spec：仅记 PR ref，不强转状态，不抛异常（宽容）。"""
    repo = await _make_repo()
    pv = await _make_plan_version()
    spec = await _make_spec(status=status, repo=repo, pv=pv)

    await SddSpecService().link_implementation_pr(
        plan_version_id=str(pv.id),
        repository_id=str(repo.id),
        pr_url="https://github.com/test/repo/pull/5",
    )

    reloaded = await _reload(spec.id)
    # 状态保持不变（不强转）
    assert reloaded.status == status
    # PR ref 仍被记录（宽容保留）
    assert len(reloaded.implementation_prs) == 1
    assert reloaded.implementation_prs[0]["pr_url"] == "https://github.com/test/repo/pull/5"
