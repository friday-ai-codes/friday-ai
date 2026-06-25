import asyncio

import pytest

from projects.models import Space
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
    ExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_simple_linear_workflow():
    """
    Test a simple linear workflow: Manual Trigger -> Code Node (mock) -> End
    """
    # 0. Create Space (Required FK)
    project = await Space.objects.acreate(
        name="Test Space", description="For Workflow Testing"
    )

    # 1. Create Workflow
    workflow = await Workflow.objects.acreate(
        name="Test Linear Workflow", trigger_type="manual", space=project
    )

    # 2. Create Nodes
    # Entry Node
    node1 = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )

    # Second Node (using ConditionNode as a pass-through dummy)
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

    # 4. Execute
    engine = WorkflowEngine()
    execution = await engine.start_execution(
        workflow=workflow, input_data={"test": "data"}, trigger_type="manual"
    )

    assert execution.status in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]

    # Wait for completion (poll)
    for _ in range(10):
        await asyncio.sleep(0.5)
        await execution.arefresh_from_db()
        if execution.status in [
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        ]:
            break

    assert execution.status == ExecutionStatus.COMPLETED
    assert execution.completed_nodes == 2
