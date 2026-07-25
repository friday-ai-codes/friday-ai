"""Concurrency limit tests for workflow execution start path."""

from __future__ import annotations

import asyncio

import pytest

from projects.models import Space
from workflows.engine import scheduler as scheduler_module
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import ExecutionStatus, Workflow, WorkflowExecution, WorkflowNode


@pytest.fixture
def concurrency_workflow(db, user):
    project = Space.objects.create(name="Concurrency Space")
    workflow = Workflow.objects.create(
        name="Concurrency Workflow",
        space=project,
        trigger_type="manual",
        created_by=user,
        max_concurrent_executions=1,
    )
    WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Start",
        position_x=0,
        position_y=0,
    )
    return workflow


def _patch_background_dispatch(monkeypatch) -> list[dict]:
    """拦截后台线程派发，只关掉 coroutine 不真跑，并记录派发参数。

    桩签名与生产 ``scheduler._run_in_thread`` 对齐（CTX-02 起带 ``triggered_by_id`` /
    ``trace_id`` 用于后台线程内重绑发起用户），不用 ``**kwargs`` 吞参数，避免后续
    签名漂移在这里失去感知。返回派发记录供用例断言。
    """
    dispatched: list[dict] = []

    def close_background_coro(coro, *, triggered_by_id=None, trace_id=None):
        dispatched.append({"triggered_by_id": triggered_by_id, "trace_id": trace_id})
        coro.close()

    monkeypatch.setattr(scheduler_module, "_run_in_thread", close_background_coro)
    return dispatched


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_pending_execution_blocks_new_start(monkeypatch, concurrency_workflow):
    dispatched = _patch_background_dispatch(monkeypatch)

    engine = WorkflowEngine()

    first = await engine.start_execution(workflow=concurrency_workflow, input_data={})

    with pytest.raises(ValueError, match="最大并发数"):
        await engine.start_execution(workflow=concurrency_workflow, input_data={})

    await first.arefresh_from_db()
    assert first.status == ExecutionStatus.PENDING

    # 被并发闸门拦下的那次绝不应派发后台执行；且派发时按 CTX-02 携带发起用户。
    assert len(dispatched) == 1
    assert dispatched[0]["triggered_by_id"] == first.triggered_by_id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_concurrent_starts_allow_only_one(monkeypatch, concurrency_workflow):
    dispatched = _patch_background_dispatch(monkeypatch)

    engine = WorkflowEngine()

    async def _start_once():
        try:
            execution = await engine.start_execution(workflow=concurrency_workflow, input_data={})
            return execution
        except Exception as exc:  # noqa: BLE001
            return exc

    results = await asyncio.gather(_start_once(), _start_once())

    # 先把非预期异常暴露出来：上面的宽 except 会把签名漂移之类的 TypeError 也吞成
    # "既不成功也不是并发失败"，让本用例退化成一句无信息的 0 == 1。
    unexpected = [
        item
        for item in results
        if isinstance(item, BaseException) and not isinstance(item, ValueError)
    ]
    assert not unexpected, f"start_execution 抛出非并发限制异常: {unexpected!r}"

    success_count = sum(isinstance(item, WorkflowExecution) for item in results)
    failure_count = sum(isinstance(item, ValueError) for item in results)

    assert success_count == 1
    assert failure_count == 1

    active_count = await WorkflowExecution.objects.filter(
        workflow=concurrency_workflow,
        status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
    ).acount()
    assert active_count == 1
    # 只有获准的那次才派发后台执行。
    assert len(dispatched) == 1
