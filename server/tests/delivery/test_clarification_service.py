"""ClarificationService 单一写入入口 + affected_partials stale 重跑测试（CLARIFY-01，41-02 Task 2）。

覆盖：create_clarification 建 pending + affected M2M / answer 写字段 + 仅 affected task stale
（非 affected 复用不变）/ 无 affected 纯解除挂起 / 重复答幂等 no-op / INV-6 grep 守护。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from delivery.models import (
    Clarification,
    PartialPlan,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ClarificationService
from repositories.models import Repository

_SERVER_ROOT = Path(__file__).resolve().parents[2]

# transaction=True：本文件 async 用例经 acreate 在独立线程连接写库，普通
# @pytest.mark.django_db（rollback）无法回滚跨线程连接的提交，会泄漏 indexed
# Repository 行污染后续全仓计数用例（backfill / rebuild / list / all_repositories）。
# TransactionTestCase 在 teardown TRUNCATE 全表，确保跨连接提交也被清理。
pytestmark = pytest.mark.django_db(transaction=True)


async def _make_task(session, status=RepoResearchTaskStatus.DONE) -> RepoResearchTask:
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=status
    )
    await PartialPlan.objects.acreate(
        research_task=task, content={"repository_id": str(repo.id)}, valid=True
    )
    return task


@pytest.mark.asyncio
async def test_create_clarification_pending_with_affected() -> None:
    """create_clarification → pending Clarification（answered_at None）+ affected_partials 关联。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    task = await _make_task(session)
    svc = ClarificationService()
    clar = await svc.create_clarification(session, "涉及哪些仓？", [task.id])

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.answered_at is None
    assert reloaded.question == "涉及哪些仓？"
    affected = [t async for t in reloaded.affected_partials.all()]
    assert [t.id for t in affected] == [task.id]


@pytest.mark.asyncio
async def test_answer_clarification_stales_only_affected() -> None:
    """answer → 写字段 + 仅 affected task stale + 其 partial 失效；非 affected 不变。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    affected = await _make_task(session)
    other = await _make_task(session)
    svc = ClarificationService()
    clar = await svc.create_clarification(session, "Q", [affected.id])

    await svc.answer_clarification(clar, "用 repo A")

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.answer == "用 repo A"
    assert reloaded.answered_at is not None

    # affected task → stale + 其 valid partial 失效
    await affected.arefresh_from_db()
    assert affected.status == RepoResearchTaskStatus.STALE
    affected_partial = await PartialPlan.objects.aget(research_task=affected)
    assert affected_partial.valid is False
    assert affected_partial.invalidated_reason == "clarification"

    # 非 affected task/partial 复用不变
    await other.arefresh_from_db()
    assert other.status == RepoResearchTaskStatus.DONE
    other_partial = await PartialPlan.objects.aget(research_task=other)
    assert other_partial.valid is True


@pytest.mark.asyncio
async def test_answer_without_affected_touches_no_task() -> None:
    """无 affected_partials → answer 仅写字段、不触任何 task。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    task = await _make_task(session)
    svc = ClarificationService()
    clar = await svc.create_clarification(session, "Q", [])

    await svc.answer_clarification(clar, "无需改动")

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.answer == "无需改动"
    # task 不变
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE
    partial = await PartialPlan.objects.aget(research_task=task)
    assert partial.valid is True


@pytest.mark.asyncio
async def test_answer_idempotent_noop_on_double_answer() -> None:
    """重复答幂等 no-op：第二次不二次覆盖首答、不重复 stale。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )
    affected = await _make_task(session)
    svc = ClarificationService()
    clar = await svc.create_clarification(session, "Q", [affected.id])

    await svc.answer_clarification(clar, "首答")
    # 重置 affected partial 为 valid 以验证第二次答不再 stale
    await PartialPlan.objects.filter(research_task=affected).aupdate(
        valid=True, invalidated_reason=""
    )
    fresh = await Clarification.objects.aget(id=clar.id)
    await svc.answer_clarification(fresh, "二答")

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.answer == "首答"  # 首答未被覆盖
    # 二答未重复 stale → partial 仍 valid
    partial = await PartialPlan.objects.aget(research_task=affected)
    assert partial.valid is True


def test_inv6_clarification_single_write_entry() -> None:
    """INV-6 grep 守护：Clarification.objects.create 仅出现在 clarification_service.py。"""
    _SKIP_DIRS = (".venv", "node_modules", ".git", "__pycache__", "site-packages")
    offenders: list[str] = []
    for path in _SERVER_ROOT.rglob("*.py"):
        rel = path.relative_to(_SERVER_ROOT).as_posix()
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if rel.startswith("tests/") or "/migrations/" in rel:
            continue
        if path.name == "clarification_service.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "Clarification.objects.create" in line:
                offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, f"Clarification 旁路写入（应只经 ClarificationService）：{offenders}"
