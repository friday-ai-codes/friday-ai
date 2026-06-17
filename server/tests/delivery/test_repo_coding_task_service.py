"""RepoCodingTaskService 行为测试（Phase 44-03，DOMAIN §6/§14，WAVE-01/02）。

覆盖 <behavior>：create_tasks_for_plan 幂等（get_or_create + wave + depends_on 边）/
mark_done 幂等（仅 running→done，重复 no-op）/ mark_done guard（非 running no-op）/
mark_blocked 下游阻断 error 结构 / mark_failed 非 dict 包装。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    PlanVersion,
    RepoCodingTask,
    RepoCodingTaskStatus,
    TechnicalPlan,
    TechnicalPlanOrigin,
)
from delivery.services import RepoCodingTaskService
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_repo(facets: dict | None = None) -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
        facets=facets or {},
    )


async def _make_plan_version() -> PlanVersion:
    plan = await TechnicalPlan.objects.acreate(origin=TechnicalPlanOrigin.ORCHESTRATION)
    return await PlanVersion.objects.acreate(plan=plan, version=1, content={"a": 1})


@sync_to_async
def _depends_on_ids(task: RepoCodingTask) -> list:
    return sorted(str(t.id) for t in task.depends_on.all())


@pytest.mark.asyncio
async def test_create_idempotent() -> None:
    """同 plan_version 两次 create → 同一批 task（get_or_create 幂等），wave + 边正确。"""
    plan_version = await _make_plan_version()
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    rid_a, rid_b = str(repo_a.id), str(repo_b.id)
    # repo_a 依赖 repo_b：b 在 wave 0，a 在 wave 1。
    repo_waves = {rid_b: 0, rid_a: 1}
    repo_dep_edges = {rid_a: [rid_b]}

    svc = RepoCodingTaskService()
    first = await svc.create_tasks_for_plan(plan_version, repo_waves, repo_dep_edges)
    second = await svc.create_tasks_for_plan(plan_version, repo_waves, repo_dep_edges)

    assert set(first) == {rid_a, rid_b}
    assert first[rid_a].id == second[rid_a].id
    assert first[rid_b].id == second[rid_b].id
    # 幂等：两次调用不重复建行。
    count = await RepoCodingTask.objects.filter(plan_version=plan_version).acount()
    assert count == 2
    # wave 正确。
    assert first[rid_a].wave == 1
    assert first[rid_b].wave == 0
    # depends_on 仓级 DAG 边：a → b。
    dep_ids = await _depends_on_ids(first[rid_a])
    assert dep_ids == [str(first[rid_b].id)]
    # 反向无边。
    assert await _depends_on_ids(first[rid_b]) == []


@pytest.mark.asyncio
async def test_follow_openspec_sdd_repo() -> None:
    """SDD 仓（facets.methodology==SDD）建任务 → follow_openspec=True（D-51-1 首次消费）。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo(facets={"methodology": "SDD"})
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    reread = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread.follow_openspec is True


@pytest.mark.asyncio
async def test_follow_openspec_non_sdd_repo() -> None:
    """非 SDD 仓（facets 缺失 / methodology!=SDD）→ follow_openspec=False（零回归）。"""
    plan_version = await _make_plan_version()
    repo_empty = await _make_repo()  # facets={}
    repo_other = await _make_repo(facets={"methodology": "TDD"})
    rid_empty, rid_other = str(repo_empty.id), str(repo_other.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid_empty: 0, rid_other: 0}, {})
    assert (await RepoCodingTask.objects.aget(id=tasks[rid_empty].id)).follow_openspec is False
    assert (await RepoCodingTask.objects.aget(id=tasks[rid_other].id)).follow_openspec is False


@pytest.mark.asyncio
async def test_follow_openspec_drift_backfill() -> None:
    """已存在 task 的 follow_openspec 与当前 facets 推导值漂移 → 回填，重复调用幂等不重复写。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()  # 初始非 SDD
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    assert (await RepoCodingTask.objects.aget(id=tasks[rid].id)).follow_openspec is False

    # 后打 SDD 标 → 再次建任务应回填 follow_openspec=True（漂移回填）。
    repo.facets = {"methodology": "SDD"}
    await repo.asave(update_fields=["facets"])
    await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    reread = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread.follow_openspec is True
    # 行未重建（幂等）。
    assert await RepoCodingTask.objects.filter(plan_version=plan_version).acount() == 1

    # 重复调用（值相等）→ updated_at 不变（相等不写）。
    before = reread.updated_at
    await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    reread2 = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread2.updated_at == before


@pytest.mark.asyncio
async def test_mark_done_idempotent() -> None:
    """running→done 第一次成功；对已 done task 再 mark_done → no-op 不报错、仍 done。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]
    await svc.mark_running(task, None)

    await svc.mark_done(task)
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.DONE

    # 重复 mark_done → no-op，不抛、status 仍 done。
    await svc.mark_done(task)
    reread2 = await RepoCodingTask.objects.aget(id=task.id)
    assert reread2.status == RepoCodingTaskStatus.DONE


@pytest.mark.asyncio
async def test_mark_done_guard() -> None:
    """对 pending（非 running）task mark_done → 条件更新影响 0 行，status 仍 pending。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]

    await svc.mark_done(task)
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.PENDING


@pytest.mark.asyncio
async def test_mark_blocked() -> None:
    """pending task mark_blocked(["u1","u2"]) → failed + error upstream_failed 结构。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]

    await svc.mark_blocked(task, ["u1", "u2"])
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.FAILED
    assert reread.error == {"reason": "upstream_failed", "upstream": ["u1", "u2"]}


@pytest.mark.asyncio
async def test_mark_blocked_guard_running() -> None:
    """已运行 task mark_blocked → no-op（仅 pending 可阻断），不强翻在途。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]
    await svc.mark_running(task, None)

    await svc.mark_blocked(task, ["u1"])
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_record_produced_artifacts() -> None:
    """done task 写 produced_artifacts 成功（aget 重读相等）；重复写同产物幂等（值不变）。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]
    await svc.mark_running(task, None)
    await svc.mark_done(task)

    artifacts = {
        "repository_id": rid,
        "repository_name": "backend",
        "available": True,
        "branch": "feat/x",
        "modified_files": ["api/openapi.yaml"],
        "openapi": ["api/openapi.yaml"],
        "diff_summary": {"files_changed": 1},
    }
    # done 状态（非 RUNNING）也能写入——无 status guard。
    await svc.record_produced_artifacts(task, artifacts)
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.DONE
    assert reread.produced_artifacts == artifacts

    # 重复写同产物 → 覆盖式幂等，值不变。
    await svc.record_produced_artifacts(task, artifacts)
    reread2 = await RepoCodingTask.objects.aget(id=task.id)
    assert reread2.produced_artifacts == artifacts


@pytest.mark.asyncio
async def test_mark_gate_blocked_pending() -> None:
    """pending task mark_gate_blocked → failed + error={reason, spec_status}（D-51-3）。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]

    affected = await svc.mark_gate_blocked(task, "spec_not_approved", "draft")
    assert affected == 1
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.FAILED
    assert reread.error == {"reason": "spec_not_approved", "spec_status": "draft"}


@pytest.mark.asyncio
async def test_mark_gate_blocked_guard_running() -> None:
    """已运行 task mark_gate_blocked → no-op（仅 pending 生效），不强翻在途。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]
    await svc.mark_running(task, None)

    affected = await svc.mark_gate_blocked(task, "spec_not_approved", "missing")
    assert affected == 0
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_mark_gate_blocked_idempotent() -> None:
    """重复 mark_gate_blocked 同一已 blocked task → 影响 0 行（status 已 failed 不匹配 pending）。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]

    first = await svc.mark_gate_blocked(task, "spec_not_approved", "missing")
    assert first == 1
    second = await svc.mark_gate_blocked(task, "spec_not_approved", "missing")
    assert second == 0
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.error == {"reason": "spec_not_approved", "spec_status": "missing"}


@pytest.mark.asyncio
async def test_mark_failed_wraps() -> None:
    """mark_failed(task, "boom") → error={"message":"boom"}（非 dict 包装）。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]

    await svc.mark_failed(task, "boom")
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.FAILED
    assert reread.error == {"message": "boom"}
