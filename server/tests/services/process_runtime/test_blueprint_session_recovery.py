"""僵尸蓝图会话周期恢复扫描（116 事故修复）。

事故形状：作答后的续驱在 HTTP 请求内跑，进程重启 / 请求被杀把它连根带走 ——
线程早已答完（无 open+blocking 线程），会话却永远停在 ``waiting_clarification``，
没有任何回调会再碰它。本文件锁三条判据：

1. 滞留的挂起态会话被重驱（``recovered`` 口径 = 重驱后 ``(status, stage)`` 变化）；
2. **人审接管的蓝图一律跳过**（推进权归 approve/reject，重驱会在人审面上凭空开澄清）；
3. 未到滞留窗口的会话不进扫描面（刚更新过的会话可能正在被别处驱动）。

驱动器本体（pause 短路 / 步数上限）由既有用例覆盖，此处一律以桩替代。
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from django.utils import timezone

from delivery.models import (
    Artifact,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ArtifactService
from services.process_runtime import blueprint_resume
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_artifact():
    return await ArtifactService().create(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )


async def _make_session(
    *,
    status: str = ConvergenceSessionStatus.WAITING_CLARIFICATION,
    stage: str = "spec_gate",
    artifact=None,
) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        status=status,
        current_stage=stage,
        current_artifact_version_id=getattr(artifact, "current_version_id", None),
    )


def _stale_now() -> object:
    """扫描注入的「现在」：把所有刚建的会话推成已滞留（auto_now 无法回拨）。"""
    return timezone.now() + timedelta(minutes=blueprint_resume._STALL_WAITING_MINUTES + 5)


async def test_stalled_waiting_session_gets_redriven(monkeypatch) -> None:
    """1. 滞留的 waiting_clarification 会话被重驱，(status, stage) 变化计入 recovered。"""
    artifact = await _make_artifact()
    await _make_session(artifact=artifact)

    async def _fake_drive(engine, target):
        target.status = ConvergenceSessionStatus.RUNNING
        target.current_stage = "repo_plan"
        return target

    monkeypatch.setattr(
        blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", _fake_drive
    )
    monkeypatch.setattr(
        blueprint_resume, "_afeedback_chat_barrier_if_any", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        blueprint_resume, "_aresume_workflow_node_if_any", AsyncMock(return_value=None)
    )

    counts = await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())

    assert counts["scanned"] == 1
    assert counts["recovered"] == 1
    assert counts["skipped_human_owned"] == 0
    # 非恒真对照：重驱后无变化 ⇒ unchanged（pause 短路的合法等待形状）
    session2 = await _make_session(artifact=artifact)

    async def _noop_drive(engine, target):
        return target

    monkeypatch.setattr(
        blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", _noop_drive
    )
    counts2 = await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())
    assert counts2["unchanged"] >= 1
    assert session2.id is not None  # 显式消费，防未用变量


async def test_human_owned_blueprint_is_skipped(monkeypatch) -> None:
    """2. 蓝图已被人审接管（pending_review 及之后）⇒ 跳过，绝不重驱。"""
    artifact = await _make_artifact()
    await Artifact.objects.filter(id=artifact.id).aupdate(blueprint_status="pending_review")
    await _make_session(artifact=artifact)

    drive = AsyncMock()
    monkeypatch.setattr(blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", drive)

    counts = await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())

    assert counts["scanned"] == 1
    assert counts["skipped_human_owned"] == 1
    assert counts["recovered"] == 0
    drive.assert_not_awaited()


async def test_fresh_sessions_are_not_scanned(monkeypatch) -> None:
    """3. 未到滞留窗口的会话不进扫描面（可能正被别处驱动，绝不双跑）。"""
    artifact = await _make_artifact()
    await _make_session(artifact=artifact)

    drive = AsyncMock()
    monkeypatch.setattr(blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", drive)

    counts = await blueprint_resume.arecover_stalled_blueprint_sessions(now=timezone.now())

    assert counts["scanned"] == 0
    drive.assert_not_awaited()


async def _make_running_research_task(project, *, started_at):
    from agents.models import AgentSession
    from repositories.models import Repository
    from subagent.models import SubAgentSession

    session = await _make_session(
        status=ConvergenceSessionStatus.WAITING_EVENT,
        stage="repo_research",
    )
    repo = await Repository.objects.acreate(
        name=f"recovery-{session.id}",
        git_url=f"https://gitlab.example.com/recovery/{session.id}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    main = await AgentSession.objects.acreate(
        session_id=f"agent-{session.id}",
        space=project,
        status=AgentSession.Status.RUNNING,
    )
    sub = await SubAgentSession.objects.acreate(
        session_id=f"research-{session.id}",
        main_session=main,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        repo_url=repo.git_url,
        started_at=started_at,
    )
    task = await RepoResearchTask.objects.acreate(
        session=session,
        repository=repo,
        subagent_session=sub,
        status=RepoResearchTaskStatus.RUNNING,
    )
    return task, sub


async def test_recovery_reconciles_runner_completion_without_structured_callback(project) -> None:
    from runners.models import Runner, RunnerEvent

    task, sub = await _make_running_research_task(project, started_at=timezone.now())
    runner = await Runner.objects.acreate(name="callback-miss", token_hash="a" * 64)
    await RunnerEvent.objects.acreate(
        runner=runner,
        event_type=RunnerEvent.EventType.TASK_COMPLETED,
        detail={"task_id": sub.session_id},
    )

    counts = await blueprint_resume.areconcile_stalled_blueprint_research_tasks(
        now=timezone.now()
    )

    await task.arefresh_from_db()
    await sub.arefresh_from_db()
    assert counts["completed_without_callback"] == 1
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error["reason"] == "completed_without_structured_result_callback"
    assert sub.status == sub.Status.COMPLETED


async def _make_never_dispatched_research_task():
    """派发期无在线 runner ⇒ task 留在 pending 且**从未**关联 subagent session。"""
    from repositories.models import Repository

    session = await _make_session(
        status=ConvergenceSessionStatus.WAITING_EVENT,
        stage="repo_research",
    )
    repo = await Repository.objects.acreate(
        name=f"degraded-{session.id}",
        git_url=f"https://gitlab.example.com/degraded/{session.id}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session,
        repository=repo,
        status=RepoResearchTaskStatus.PENDING,
    )
    return session, task


async def _make_online_runner(name: str):
    from runners.models import Runner

    return await Runner.objects.acreate(
        name=name,
        token_hash=name.ljust(64, "b"),
        status="online",
        last_heartbeat=timezone.now(),
    )


async def test_never_dispatched_research_is_redispatched_once_runner_is_back(monkeypatch) -> None:
    """⭐ 死锁的锁：无 runner 降级留下的 pending task，runner 回来后必须被重派。

    三要素缺一不可地锁死了这条链 —— 容器从未起过（无 callback）、对账只扫 RUNNING、
    ``waiting_event`` 短路判据要求全部终态。没有本兜底，会话永久停在 ``researching``。
    """
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    session, _task = await _make_never_dispatched_research_task()
    await _make_online_runner("redispatch-online")
    dispatch = AsyncMock(return_value={"dispatched": 1, "synthesized": 0, "degraded": False})
    monkeypatch.setattr(BlueprintResearchAdapter, "dispatch", dispatch)

    counts = await blueprint_resume.aredispatch_never_dispatched_blueprint_research_tasks(
        now=_stale_now()
    )

    assert counts == {"scanned": 1, "redispatched": 1, "unchanged": 0}
    # AsyncMock 顶掉类属性后不走描述符绑定 ⇒ 第一个实参就是会话本体（无 self）。
    assert str(dispatch.await_args.args[0].id) == str(session.id)


async def test_redispatch_is_a_noop_while_no_runner_is_online(monkeypatch) -> None:
    """非恒真对照：仍无在线 runner ⇒ 空转返回，⛔ 不白派一轮（也不刷日志噪声）。"""
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    await _make_never_dispatched_research_task()
    dispatch = AsyncMock(return_value={"dispatched": 0})
    monkeypatch.setattr(BlueprintResearchAdapter, "dispatch", dispatch)

    counts = await blueprint_resume.aredispatch_never_dispatched_blueprint_research_tasks(
        now=_stale_now()
    )

    assert counts == {"scanned": 0, "redispatched": 0, "unchanged": 0}
    dispatch.assert_not_awaited()


async def test_already_dispatched_research_is_never_redispatched(monkeypatch) -> None:
    """非恒真对照：已起过容器（有 subagent session）的仓不进重派面，绝不重开容器。"""
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    session, task = await _make_never_dispatched_research_task()
    await _make_online_runner("already-dispatched")
    sub = await _make_running_research_task_stub(session)
    await RepoResearchTask.objects.filter(id=task.id).aupdate(subagent_session=sub)
    dispatch = AsyncMock(return_value={"dispatched": 1})
    monkeypatch.setattr(BlueprintResearchAdapter, "dispatch", dispatch)

    counts = await blueprint_resume.aredispatch_never_dispatched_blueprint_research_tasks(
        now=_stale_now()
    )

    assert counts["scanned"] == 0
    dispatch.assert_not_awaited()


async def _make_running_research_task_stub(session):
    from agents.models import AgentSession
    from subagent.models import SubAgentSession

    main = await AgentSession.objects.acreate(
        session_id=f"agent-stub-{session.id}",
        status=AgentSession.Status.RUNNING,
    )
    return await SubAgentSession.objects.acreate(
        session_id=f"research-stub-{session.id}",
        main_session=main,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        repo_url="https://gitlab.example.com/degraded/stub.git",
    )


async def test_recovery_tick_redispatches_before_it_redrives(monkeypatch) -> None:
    """接线锁：重派必须在重驱**之前** —— 反了这一 tick 依然推不动（短路仍成立）。"""
    order: list[str] = []

    async def _spy_redispatch(**_kwargs):
        order.append("redispatch")
        return {"scanned": 0, "redispatched": 0, "unchanged": 0}

    async def _spy_drive(_engine, target):
        order.append("drive")
        return target

    artifact = await _make_artifact()
    await _make_session(artifact=artifact)
    monkeypatch.setattr(
        blueprint_resume,
        "aredispatch_never_dispatched_blueprint_research_tasks",
        _spy_redispatch,
    )
    monkeypatch.setattr(
        blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", _spy_drive
    )
    monkeypatch.setattr(
        blueprint_resume, "_afeedback_chat_barrier_if_any", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        blueprint_resume, "_aresume_workflow_node_if_any", AsyncMock(return_value=None)
    )

    await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())

    assert order[:2] == ["redispatch", "drive"]


async def test_recovery_enforces_research_task_timeout_without_runner_terminal_event(project) -> None:
    from services.process_runtime.blueprint_research_adapter import _RESEARCH_TIMEOUT

    started_at = timezone.now() - timedelta(seconds=_RESEARCH_TIMEOUT + 1)
    task, sub = await _make_running_research_task(project, started_at=started_at)

    counts = await blueprint_resume.areconcile_stalled_blueprint_research_tasks(
        now=timezone.now()
    )

    await task.arefresh_from_db()
    await sub.arefresh_from_db()
    assert counts["timed_out"] == 1
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error["reason"] == "container_timeout"
    assert sub.status == sub.Status.TIMEOUT
