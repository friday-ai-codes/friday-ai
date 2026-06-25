"""派发器内存队列续派守护（）。

修复前缺陷：``_pending`` 仅在 runner 重连时排空，任务完成释放槽位时不续派，
导致批量 repo_summary/PageIndex 派发只跑前 ``runner.concurrent`` 个、其余卡死。
本测试验证 ``drain_pending()`` 在槽位释放后能把队列里等待的任务派出去。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from django.db import models as db_models
from django.db.models.functions import Greatest
from django.utils import timezone

from agents.models import AgentSession
from runners.dispatcher import DispatchTask, TaskDispatcher
from runners.models import Runner, RunnerTaskAssignment
from subagent.models import SubAgentSession

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_runner(concurrent: int = 1) -> Runner:
    return await Runner.objects.acreate(
        name="drain-runner",
        token_hash="d" * 64,
        status=Runner.Status.ONLINE,
        is_active=True,
        is_paused=False,
        channel_name="drain.test.chan",
        tags=["x"],
        concurrent=concurrent,
        current_tasks=0,
        last_heartbeat=timezone.now(),
    )


async def _make_session(session_id: str) -> SubAgentSession:
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
    )


def _task(session_id: str) -> DispatchTask:
    return DispatchTask(
        task_id=session_id,
        task_type="repo_summary",
        tags=["x"],
        image="img",
        repo_url="https://example.com/r.git",
        branch="",
        target_branch="",
        prompt="p",
        timeout=600,
        node_execution_id="",
        session_id=session_id,
        metadata={},
    )


async def test_drain_pending_dispatches_queued_task_after_slot_frees() -> None:
    """concurrent=1：A 派出占满槽 → B 进队列；释放槽位 + drain → B 被派出。"""
    runner = await _make_runner(concurrent=1)
    await _make_session("sessA")
    await _make_session("sessB")

    dispatcher = TaskDispatcher()

    with patch(
        "tools.registry.RemoteToolRegistry.aget_tools_payload",
        new=AsyncMock(return_value=[]),
    ):
        # A：有空槽 → 直接派发，current_tasks 0→1
        await dispatcher.dispatch(_task("sessA"))
        await runner.arefresh_from_db()
        assert runner.current_tasks == 1
        assert dispatcher._pending.qsize() == 0
        assert await RunnerTaskAssignment.objects.filter(
            session__session_id="sessA", status="assigned"
        ).aexists()

        # B：无空槽（1 不 < 1）→ 进内存队列
        await dispatcher.dispatch(_task("sessB"))
        assert dispatcher._pending.qsize() == 1
        assert not await RunnerTaskAssignment.objects.filter(
            session__session_id="sessB"
        ).aexists()

        # 模拟 A 完成释放槽位（consumers._free_runner_slot_and_drain 的等价动作）
        await Runner.objects.filter(id=runner.id).aupdate(
            current_tasks=Greatest(db_models.F("current_tasks") - 1, db_models.Value(0)),
        )
        await dispatcher.drain_pending()

        # B 现在应被派出，队列排空
        assert dispatcher._pending.qsize() == 0
        await runner.arefresh_from_db()
        assert runner.current_tasks == 1
        assert await RunnerTaskAssignment.objects.filter(
            session__session_id="sessB", status="assigned"
        ).aexists()


async def test_drain_pending_stops_when_no_free_slot() -> None:
    """无空槽时 drain 不空转：队列保持原样，任务放回。"""
    await _make_runner(concurrent=1)  # 需在 DB（供 _find_matching_runners），变量本身不引用
    await _make_session("sessA")
    await _make_session("sessB")

    dispatcher = TaskDispatcher()
    with patch(
        "tools.registry.RemoteToolRegistry.aget_tools_payload",
        new=AsyncMock(return_value=[]),
    ):
        await dispatcher.dispatch(_task("sessA"))  # 占满
        await dispatcher.dispatch(_task("sessB"))  # 入队
        assert dispatcher._pending.qsize() == 1

        # 槽位仍满 → drain 不应派出 B
        await dispatcher.drain_pending()
        assert dispatcher._pending.qsize() == 1
        assert not await RunnerTaskAssignment.objects.filter(
            session__session_id="sessB"
        ).aexists()


def test_consumer_has_free_slot_and_drain_helper() -> None:
    """consumers 暴露 _free_runner_slot_and_drain（完成/失败路径调用）。"""
    from runners.consumers import RunnerConsumer

    assert hasattr(RunnerConsumer, "_free_runner_slot_and_drain")
