"""Tests for stop_before_node_id execution feature."""

import asyncio

import pytest

from projects.models import Space
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
    ExecutionStatus,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stop_before_second_node():
    """Test that execution stops before the specified node."""
    # 0. Create Space
    project = await Space.objects.acreate(
        name="Test Space", description="For stop_before testing"
    )

    # 1. Create Workflow
    workflow = await Workflow.objects.acreate(
        name="Test Stop Before", trigger_type="manual", space=project
    )

    # 2. Create Nodes: manual_trigger -> condition -> end
    node1 = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    node2 = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="Check",
        position_x=200,
        position_y=0,
        config={"expression": "true", "cases": []},
    )
    node3 = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="End",
        position_x=400,
        position_y=0,
        config={"expression": "true", "cases": []},
    )

    # 3. Create Edges
    await WorkflowEdge.objects.acreate(
        workflow=workflow,
        source_node=node1,
        target_node=node2,
        source_handle="default",
        target_handle="default",
    )
    await WorkflowEdge.objects.acreate(
        workflow=workflow,
        source_node=node2,
        target_node=node3,
        source_handle="default",
        target_handle="default",
    )

    # 4. Execute with stop_before_node_id pointing to node2
    engine = WorkflowEngine()
    execution = await engine.start_execution(
        workflow=workflow,
        input_data={"test": "data"},
        trigger_type="manual",
        stop_before_node_id=str(node2.id),
        run_sync=True,
    )

    # Wait for completion
    for _ in range(20):
        await asyncio.sleep(0.3)
        await execution.arefresh_from_db()
        if execution.status in [
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        ]:
            break

    # 5. Assertions
    assert execution.status == ExecutionStatus.COMPLETED

    # Node1 should be completed
    node1_exec = await execution.node_executions.aget(node_id=node1.id)
    assert node1_exec.status == NodeExecutionStatus.COMPLETED

    # Node2 should be pending (stopped before)
    node2_exec = await execution.node_executions.aget(node_id=node2.id)
    assert node2_exec.status == NodeExecutionStatus.PENDING

    # Node3 should be skipped (downstream of stop)
    node3_exec = await execution.node_executions.aget(node_id=node3.id)
    assert node3_exec.status == NodeExecutionStatus.SKIPPED


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stop_before_nonexistent_node_runs_all():
    """Test that execution completes normally when stop_before_node_id doesn't exist."""
    # 0. Create Space
    project = await Space.objects.acreate(
        name="Test Space", description="For stop_before testing"
    )

    # 1. Create Workflow
    workflow = await Workflow.objects.acreate(
        name="Test Stop Before Nonexistent", trigger_type="manual", space=project
    )

    # 2. Create Nodes
    node1 = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    node2 = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="Check",
        position_x=200,
        position_y=0,
        config={"expression": "true", "cases": []},
    )

    # 3. Create Edge
    await WorkflowEdge.objects.acreate(
        workflow=workflow,
        source_node=node1,
        target_node=node2,
        source_handle="default",
        target_handle="default",
    )

    # 4. Execute with non-existent stop_before_node_id
    engine = WorkflowEngine()
    execution = await engine.start_execution(
        workflow=workflow,
        input_data={"test": "data"},
        trigger_type="manual",
        stop_before_node_id="00000000-0000-0000-0000-000000000000",
        run_sync=True,
    )

    # Wait for completion
    for _ in range(20):
        await asyncio.sleep(0.3)
        await execution.arefresh_from_db()
        if execution.status in [
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        ]:
            break

    # 5. Assertions
    assert execution.status == ExecutionStatus.COMPLETED
    assert execution.completed_nodes == 2

    # Both nodes should be completed
    node1_exec = await execution.node_executions.aget(node_id=node1.id)
    assert node1_exec.status == NodeExecutionStatus.COMPLETED

    node2_exec = await execution.node_executions.aget(node_id=node2.id)
    assert node2_exec.status == NodeExecutionStatus.COMPLETED
