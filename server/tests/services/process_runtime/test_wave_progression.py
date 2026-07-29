"""wave 推进 helper 行为测试（Phase 44-04，WAVE-02）。

覆盖 <behavior>：
- test_wave_gate：RUNNING 在途 → waiting；回填 done 后 → dispatch 下一 wave。
- test_failure_isolation：同 wave 兄弟互不影响（一仓 done 一仓 failed）。
- test_downstream_blocked：单跳上游 failed → 下游 blocked + all_terminal。
- test_downstream_blocked_transitive_2hop：2 跳链 A→B→C，A failed → B、C 同次全 blocked
  且 all_terminal（liveness 守护，防死锁）。
- test_idempotent：重复 aadvance no-op（mark_done 只生效一次，不重复翻转）。
- test_all_terminal：全 done/failed → all_terminal。
"""

from __future__ import annotations

import uuid

import pytest

from agents.models import AgentSession
from delivery.models import (
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    RepoCodingTaskStatus,
)
from delivery.services import RepoCodingTaskService
from repositories.models import Repository
from services.process_runtime import aadvance_coding_waves
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _make_plan_version() -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={"a": 1}, content_hash="h"
    )
    artifact.current_version = av
    await artifact.asave(update_fields=["current_version", "updated_at"])
    return av


async def _make_subagent(status: str) -> SubAgentSession:
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    return await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url="https://github.com/test/x.git",
        task_type=SubAgentSession.TaskType.CODING,
        status=status,
    )


@pytest.mark.asyncio
async def test_wave_gate() -> None:
    """wave0 running 在途 → waiting；其 SubAgentSession 置 done 回填后 → dispatch wave1。"""
    plan_version = await _make_plan_version()
    repo_b, repo_a = await _make_repo(), await _make_repo()
    rid_b, rid_a = str(repo_b.id), str(repo_a.id)
    # b 在 wave0，a 在 wave1 依赖 b。
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid_b: 0, rid_a: 1}, {rid_a: [rid_b]})
    # wave0 task_b 标 running 并挂 SubAgentSession（status=running 在途）。
    sub_b = await _make_subagent(SubAgentSession.Status.RUNNING)
    await svc.mark_running(tasks[rid_b], sub_b)

    # RUNNING 在途 → waiting（不因 wave1 pending 抢先 dispatch，也不死锁）。
    result = await aadvance_coding_waves(plan_version.id, service=svc)
    assert result == {"waiting": True}

    # SubAgentSession 置 completed → 回填 done、无 RUNNING、wave1 depends_on 全 done → dispatch。
    sub_b.status = SubAgentSession.Status.COMPLETED
    await sub_b.asave(update_fields=["status"])
    result2 = await aadvance_coding_waves(plan_version.id, service=svc)
    assert result2.get("wave") == 1
    dispatch_ids = {str(t.id) for t in result2.get("dispatch", [])}
    assert dispatch_ids == {str(tasks[rid_a].id)}
    # 回填生效：task_b done。
    reread_b = await RepoCodingTask.objects.aget(id=tasks[rid_b].id)
    assert reread_b.status == RepoCodingTaskStatus.DONE


@pytest.mark.asyncio
async def test_failure_isolation() -> None:
    """同 wave repoA done、repoB failed → 互不影响；依赖 A 的可派发、依赖 B 的被 blocked。"""
    plan_version = await _make_plan_version()
    repo_a, repo_b = await _make_repo(), await _make_repo()
    repo_c, repo_d = await _make_repo(), await _make_repo()
    rid_a, rid_b = str(repo_a.id), str(repo_b.id)
    rid_c, rid_d = str(repo_c.id), str(repo_d.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(
        plan_version,
        {rid_a: 0, rid_b: 0, rid_c: 1, rid_d: 1},
        {rid_c: [rid_a], rid_d: [rid_b]},
    )
    # repoA done（running→done），repoB failed；均无 running 在途。
    await svc.mark_running(tasks[rid_a], None)
    await svc.mark_done(tasks[rid_a])
    await svc.mark_failed(tasks[rid_b], "boom")

    result = await aadvance_coding_waves(plan_version.id, service=svc)

    # 同 wave 兄弟互不影响。
    assert (await RepoCodingTask.objects.aget(id=tasks[rid_a].id)).status == (
        RepoCodingTaskStatus.DONE
    )
    assert (await RepoCodingTask.objects.aget(id=tasks[rid_b].id)).status == (
        RepoCodingTaskStatus.FAILED
    )
    # 依赖 A（done）的 repoC 可派发；依赖 B（failed）的 repoD 被 blocked。
    assert result.get("wave") == 1
    dispatch_ids = {str(t.id) for t in result.get("dispatch", [])}
    assert dispatch_ids == {str(tasks[rid_c].id)}
    reread_d = await RepoCodingTask.objects.aget(id=tasks[rid_d].id)
    assert reread_d.status == RepoCodingTaskStatus.FAILED
    assert reread_d.error["reason"] == "upstream_failed"


@pytest.mark.asyncio
async def test_downstream_blocked() -> None:
    """repoC(wave1) depends_on repoB(wave0)；repoB failed → repoC blocked + all_terminal。"""
    plan_version = await _make_plan_version()
    repo_b, repo_c = await _make_repo(), await _make_repo()
    rid_b, rid_c = str(repo_b.id), str(repo_c.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid_b: 0, rid_c: 1}, {rid_c: [rid_b]})
    await svc.mark_failed(tasks[rid_b], "boom")

    result = await aadvance_coding_waves(plan_version.id, service=svc)

    reread_c = await RepoCodingTask.objects.aget(id=tasks[rid_c].id)
    assert reread_c.status == RepoCodingTaskStatus.FAILED
    assert reread_c.error["reason"] == "upstream_failed"
    # 不出现在 dispatch；无 pending 无 running → all_terminal。
    assert result == {"all_terminal": True}


@pytest.mark.asyncio
async def test_downstream_blocked_transitive_2hop() -> None:
    """链 A→B→C：A failed → 单次 aadvance 内 B、C 均 blocked 且 all_terminal（防死锁）。"""
    plan_version = await _make_plan_version()
    repo_a, repo_b, repo_c = await _make_repo(), await _make_repo(), await _make_repo()
    rid_a, rid_b, rid_c = str(repo_a.id), str(repo_b.id), str(repo_c.id)
    svc = RepoCodingTaskService()
    # B depends_on A（wave1），C depends_on B（wave2）。
    tasks = await svc.create_tasks_for_plan(
        plan_version,
        {rid_a: 0, rid_b: 1, rid_c: 2},
        {rid_b: [rid_a], rid_c: [rid_b]},
    )
    await svc.mark_failed(tasks[rid_a], "boom")

    result = await aadvance_coding_waves(plan_version.id, service=svc)

    # B 与 C 在单次 aadvance 内均被标 blocked（传递闭包 2 跳）。
    reread_b = await RepoCodingTask.objects.aget(id=tasks[rid_b].id)
    reread_c = await RepoCodingTask.objects.aget(id=tasks[rid_c].id)
    assert reread_b.status == RepoCodingTaskStatus.FAILED
    assert reread_b.error["reason"] == "upstream_failed"
    assert reread_c.status == RepoCodingTaskStatus.FAILED
    assert reread_c.error["reason"] == "upstream_failed"
    # C 不残留 pending、不出现在任何 dispatch；收尾可达。
    assert result == {"all_terminal": True}


@pytest.mark.asyncio
async def test_idempotent() -> None:
    """连续两次 aadvance（模拟重复 callback）→ 第二次 no-op，task 状态不重复翻转。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    sub = await _make_subagent(SubAgentSession.Status.COMPLETED)
    await svc.mark_running(tasks[rid], sub)

    first = await aadvance_coding_waves(plan_version.id, service=svc)
    assert first == {"all_terminal": True}
    reread1 = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread1.status == RepoCodingTaskStatus.DONE
    ts1 = reread1.updated_at

    # 第二次 aadvance：task 已 done（非 running）→ 回填跳过，不重复翻转。
    second = await aadvance_coding_waves(plan_version.id, service=svc)
    assert second == {"all_terminal": True}
    reread2 = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread2.status == RepoCodingTaskStatus.DONE
    # updated_at 未变 → mark_done 条件更新只生效一次（no-op）。
    assert reread2.updated_at == ts1


@pytest.mark.asyncio
async def test_all_terminal() -> None:
    """全 task done/failed（无 running 无 pending）→ all_terminal。"""
    plan_version = await _make_plan_version()
    repo_a, repo_b = await _make_repo(), await _make_repo()
    rid_a, rid_b = str(repo_a.id), str(repo_b.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid_a: 0, rid_b: 0}, {})
    await svc.mark_running(tasks[rid_a], None)
    await svc.mark_done(tasks[rid_a])
    await svc.mark_failed(tasks[rid_b], "boom")

    result = await aadvance_coding_waves(plan_version.id, service=svc)
    assert result == {"all_terminal": True}
