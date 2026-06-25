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


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_pending_execution_blocks_new_start(monkeypatch, concurrency_workflow):
    def close_background_coro(coro):
        coro.close()

    monkeypatch.setattr(scheduler_module, "_run_in_thread", close_background_coro)

    engine = WorkflowEngine()

    first = await engine.start_execution(workflow=concurrency_workflow, input_data={})

    with pytest.raises(ValueError, match="最大并发数"):
        await engine.start_execution(workflow=concurrency_workflow, input_data={})

    await first.arefresh_from_db()
    assert first.status == ExecutionStatus.PENDING


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_concurrent_starts_allow_only_one(monkeypatch, concurrency_workflow):
    def close_background_coro(coro):
        coro.close()

    monkeypatch.setattr(scheduler_module, "_run_in_thread", close_background_coro)

    engine = WorkflowEngine()

    async def _start_once():
        try:
            execution = await engine.start_execution(workflow=concurrency_workflow, input_data={})
            return execution
        except Exception as exc:  # noqa: BLE001
            return exc

    results = await asyncio.gather(_start_once(), _start_once())

    success_count = sum(isinstance(item, WorkflowExecution) for item in results)
    failure_count = sum(isinstance(item, ValueError) for item in results)

    assert success_count == 1
    assert failure_count == 1

    active_count = await WorkflowExecution.objects.filter(
        workflow=concurrency_workflow,
        status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
    ).acount()
    assert active_count == 1
