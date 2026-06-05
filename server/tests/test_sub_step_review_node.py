"""AICodeReviewNode 子步骤集成测试。

覆盖 work item 需求：
- AICodeReviewNode 声明 3 个子步骤
- _init_sub_steps 创建 pending 记录
- emit_sub_step 正确推进状态
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from projects.models import Project
    from workflows.models.node import WorkflowNode
    from workflows.models.workflow import Workflow
    from workflows.nodes.base import ExecutionContext

from workflows.models.execution import (
    NodeExecution,
    NodeSubStep,
    SubStepStatus,
    WorkflowExecution,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def workflow(db: None, project: "Project") -> "Workflow":
    """创建测试工作流。"""
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Review Workflow", project=project)


@pytest.fixture
def workflow_node(db: None, workflow: "Workflow") -> "WorkflowNode":
    """创建测试工作流节点。"""
    from workflows.models.node import WorkflowNode

    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_code_review",
        name="Test Review Node",
        config={},
    )


@pytest.fixture
def workflow_execution(db: None, workflow: "Workflow") -> WorkflowExecution:
    """创建测试工作流执行实例。"""
    return WorkflowExecution.objects.create(
        workflow=workflow,
        project=workflow.project,
        status="running",
    )


@pytest.fixture
def node_execution(
    db: None,
    workflow_execution: WorkflowExecution,
    workflow_node: "WorkflowNode",
) -> NodeExecution:
    """创建测试节点执行记录。"""
    return NodeExecution.objects.create(
        workflow_execution=workflow_execution,
        node=workflow_node,
        status="running",
    )


@pytest.fixture
def execution_context(
    node_execution: NodeExecution,
    workflow_execution: WorkflowExecution,
) -> "ExecutionContext":
    """创建测试 ExecutionContext。"""
    from workflows.nodes.base import ExecutionContext

    return ExecutionContext(
        execution_id=str(workflow_execution.id),
        node_id=str(node_execution.node_id),
        node_config={},
        input_data={},
        workflow_context={},
        previous_outputs={},
        workflow_execution=workflow_execution,
        node_execution=node_execution,
    )


# ============================================================================
# AICodeReviewNode 子步骤声明测试
# ============================================================================


def test_review_node_sub_steps_declaration() -> None:
    """AICodeReviewNode 声明 3 个子步骤。"""
    from workflows.nodes.ai.code_review import AICodeReviewNode

    assert len(AICodeReviewNode.sub_steps) == 3
    step_types = [s[0] for s in AICodeReviewNode.sub_steps]
    assert step_types == ["fetch_diff", "ai_review", "send_notification"]


def test_review_node_sub_step_names() -> None:
    """AICodeReviewNode 子步骤名称正确。"""
    from workflows.nodes.ai.code_review import AICodeReviewNode

    names = [s[1] for s in AICodeReviewNode.sub_steps]
    assert names == ["获取Diff", "AI审查", "发送通知"]


# ============================================================================
# _init_sub_steps 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_review_node_init_sub_steps(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """AICodeReviewNode._init_sub_steps 创建 3 个 pending 记录。"""
    from workflows.nodes.ai.code_review import AICodeReviewNode

    node = AICodeReviewNode()
    await node._init_sub_steps(execution_context)

    sub_steps = [
        s async for s in NodeSubStep.objects.filter(
            node_execution=node_execution
        ).order_by("step_order")
    ]
    assert len(sub_steps) == 3
    assert sub_steps[0].step_type == "fetch_diff"
    assert sub_steps[0].name == "获取Diff"
    assert sub_steps[0].status == SubStepStatus.PENDING
    assert sub_steps[1].step_type == "ai_review"
    assert sub_steps[2].step_type == "send_notification"

    await node_execution.arefresh_from_db()
    assert node_execution.sub_step_total_count == 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_review_node_emit_sub_step_running(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """emit_sub_step(running) 正确更新状态。"""
    from workflows.nodes.ai.code_review import AICodeReviewNode

    node = AICodeReviewNode()
    await node._init_sub_steps(execution_context)

    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        await node.emit_sub_step(execution_context, "fetch_diff", SubStepStatus.RUNNING)

    sub_step = await NodeSubStep.objects.aget(
        node_execution=node_execution, step_type="fetch_diff"
    )
    assert sub_step.status == SubStepStatus.RUNNING
    assert sub_step.started_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_review_node_emit_sub_step_completed(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """emit_sub_step(completed) 更新状态并递增进度。"""
    from workflows.nodes.ai.code_review import AICodeReviewNode

    node = AICodeReviewNode()
    await node._init_sub_steps(execution_context)

    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        await node.emit_sub_step(execution_context, "fetch_diff", SubStepStatus.RUNNING)
        await node.emit_sub_step(execution_context, "fetch_diff", SubStepStatus.COMPLETED)

    sub_step = await NodeSubStep.objects.aget(
        node_execution=node_execution, step_type="fetch_diff"
    )
    assert sub_step.status == SubStepStatus.COMPLETED
    assert sub_step.completed_at is not None

    await node_execution.arefresh_from_db()
    assert node_execution.sub_step_completed_count == 1
