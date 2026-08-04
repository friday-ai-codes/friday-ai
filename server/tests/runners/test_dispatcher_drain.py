"""dispatch() durable 化语义（31u，改写自旧内存队列 drain 用例）。

语义变更来由：旧 ``dispatch()`` 先内联试派、无空槽压进程内存队列（``_pending``），靠
runner 上线 / 槽位释放事件 drain —— server 重启即丢且无自动重派。31u 起
``dispatch()`` = ① redacted 快照落库（``last_output["dispatch"]``）② defer
``durable_runner_dispatch``（``lock=dispatch-{session_id}``、⛔ 无 ``idempotency_key``）；
真正的标签匹配派发在 durable worker 任务体执行，无 runner 时按退避 re-defer，
``drain_pending`` / ``on_runner_online`` / ``on_task_rejected`` 内存队列语义整体退役。

任务体（守卫 / re-defer / rehydrate）的覆盖在 ``tests/durable/test_runner_dispatch.py``。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agents.models import AgentSession
from runners.dispatcher import DispatchTask, TaskDispatcher
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_session(session_id: str, last_output: dict | None = None) -> SubAgentSession:
    agent = await AgentSession.objects.acreate(
        session_id=f"agent-{session_id}",
        space=None,
        status=AgentSession.Status.RUNNING,
    )
    return await SubAgentSession.objects.acreate(
        session_id=session_id,
        main_session=agent,
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=SubAgentSession.Status.PENDING,
        repo_url="https://example.com/r.git",
        last_output=last_output or {},
    )


def _task(session_id: str, metadata: dict | None = None) -> DispatchTask:
    return DispatchTask(
        task_id=session_id,
        task_type="repo_summary",
        tags=["x"],
        image="",
        repo_url="https://example.com/r.git",
        branch="main",
        target_branch="main",
        prompt="p",
        timeout=600,
        node_execution_id="",
        session_id=session_id,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_dispatch_persists_redacted_snapshot_and_defers(monkeypatch) -> None:
    """dispatch() = 快照落库 + defer：凭证键剔除、defer 形参正确、不内联建 assignment。"""
    from durable.service import DurableTaskService
    from runners.models import RunnerTaskAssignment

    session = await _make_session("sessA")
    deferred: list[dict] = []

    async def _capture(task_name, payload, **kwargs):
        deferred.append({"task": task_name, "payload": payload, **kwargs})
        return "job-1"

    monkeypatch.setattr(DurableTaskService, "defer", AsyncMock(side_effect=_capture))

    dispatcher = TaskDispatcher()
    await dispatcher.dispatch(
        _task(
            "sessA",
            metadata={
                "repository_id": "repo-1",
                "env_FRIDAY_TASK_GIT_ACCESS_TOKEN": "glpat-SECRET",
            },
        )
    )

    # defer 形参：任务名 / 队列 / lock / payload 只含 session_id+attempt、无 idempotency_key
    assert len(deferred) == 1
    call = deferred[0]
    assert call["task"] == "durable_runner_dispatch"
    assert call["payload"] == {"session_id": "sessA", "attempt": 0}
    assert call["queue"] == "dispatch"
    assert call["lock"] == "dispatch-sessA"
    assert call.get("idempotency_key") is None

    # 快照落库且凭证明文被剔除（记 _redacted_env_keys 标记）
    await session.arefresh_from_db()
    snapshot = session.last_output["dispatch"]
    assert snapshot["repo_url"] == "https://example.com/r.git"
    assert snapshot["metadata"]["repository_id"] == "repo-1"
    assert "env_FRIDAY_TASK_GIT_ACCESS_TOKEN" not in snapshot["metadata"]
    assert snapshot["metadata"]["_redacted_env_keys"] == ["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"]

    # 不再内联试派：assignment 由 durable 任务体建立，dispatch() 本身零 assignment
    assert not await RunnerTaskAssignment.objects.filter(session__session_id="sessA").aexists()


@pytest.mark.asyncio
async def test_dispatch_keeps_existing_snapshot_verbatim(monkeypatch) -> None:
    """编码链已在 dispatch_coding_task 落过快照 → dispatch() 跳过持久化、只入队。"""
    from durable.service import DurableTaskService

    existing = {"dispatch": {"repo_url": "https://example.com/orig.git", "metadata": {}}}
    session = await _make_session("sessB", last_output=existing)

    defer = AsyncMock(return_value="job-2")
    monkeypatch.setattr(DurableTaskService, "defer", defer)

    dispatcher = TaskDispatcher()
    await dispatcher.dispatch(_task("sessB"))

    defer.assert_awaited_once()
    await session.arefresh_from_db()
    # 既有快照逐字保留（不被本次 task 覆盖）
    assert session.last_output["dispatch"]["repo_url"] == "https://example.com/orig.git"


@pytest.mark.asyncio
async def test_dispatch_defer_failure_propagates(monkeypatch) -> None:
    """defer 抛异常向上抛（既有调用方契约：dispatch_coding_task 依赖异常吊销任务 token）。"""
    from durable.service import DurableTaskService

    await _make_session("sessC")
    monkeypatch.setattr(
        DurableTaskService, "defer", AsyncMock(side_effect=RuntimeError("queue down"))
    )

    dispatcher = TaskDispatcher()
    with pytest.raises(RuntimeError, match="queue down"):
        await dispatcher.dispatch(_task("sessC"))


def test_memory_queue_semantics_retired() -> None:
    """内存队列语义整体退役：drain/上线/拒绝重排入口不复存在，_try_assign 保留。"""
    assert not hasattr(TaskDispatcher, "drain_pending")
    assert not hasattr(TaskDispatcher, "on_runner_online")
    assert not hasattr(TaskDispatcher, "on_task_rejected")
    assert hasattr(TaskDispatcher, "_try_assign")


def test_consumer_frees_slot_without_drain() -> None:
    """consumers 槽位释放 helper 更名 _free_runner_slot（续派由 durable re-defer 接管）。"""
    from runners.consumers import RunnerConsumer

    assert hasattr(RunnerConsumer, "_free_runner_slot")
    assert not hasattr(RunnerConsumer, "_free_runner_slot_and_drain")
