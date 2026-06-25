"""AICodingNode 子步骤集成测试。

覆盖 work item 需求：
- SubStepMixin 提取并独立存在
- AICodingNode 声明 4 个子步骤
- _init_sub_steps 创建 pending 记录
- SubStepMixin 方法签名完整
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from projects.models import Space
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
def workflow(db: None, project: "Space") -> "Workflow":
    """创建测试工作流。"""
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Coding Workflow", space=project)


@pytest.fixture
def workflow_node(db: None, workflow: "Workflow") -> "WorkflowNode":
    """创建测试工作流节点。"""
    from workflows.models.node import WorkflowNode

    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_coding",
        name="Test Coding Node",
        config={},
    )


@pytest.fixture
def workflow_execution(db: None, workflow: "Workflow") -> WorkflowExecution:
    """创建测试工作流执行实例。"""
    return WorkflowExecution.objects.create(
        workflow=workflow,
        space=workflow.space,
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
# SubStepMixin 独立存在测试
# ============================================================================


def test_sub_step_mixin_exists() -> None:
    """SubStepMixin 类存在且包含必要属性和方法。"""
    from workflows.nodes.ai.sub_step_mixin import SubStepMixin

    assert hasattr(SubStepMixin, "sub_steps")
    assert hasattr(SubStepMixin, "_init_sub_steps")
    assert hasattr(SubStepMixin, "emit_sub_step")
    assert SubStepMixin.sub_steps == []


def test_ai_agent_base_node_inherits_mixin() -> None:
    """AIAgentBaseNode 继承 SubStepMixin。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode
    from workflows.nodes.ai.sub_step_mixin import SubStepMixin

    assert issubclass(AIAgentBaseNode, SubStepMixin)


# ============================================================================
# AICodingNode 子步骤声明测试
# ============================================================================


def test_coding_node_sub_steps_declaration() -> None:
    """AICodingNode 声明 4 个子步骤。"""
    from workflows.nodes.ai.coding import AICodingNode

    assert len(AICodingNode.sub_steps) == 4
    step_types = [s[0] for s in AICodingNode.sub_steps]
    assert step_types == ["prepare_plan", "coding_execute", "create_mr", "send_notification"]


def test_coding_node_inherits_sub_step_mixin() -> None:
    """AICodingNode 继承 SubStepMixin。"""
    from workflows.nodes.ai.coding import AICodingNode
    from workflows.nodes.ai.sub_step_mixin import SubStepMixin

    assert issubclass(AICodingNode, SubStepMixin)


# ============================================================================
# _init_sub_steps 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_coding_node_init_sub_steps(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """AICodingNode._init_sub_steps 创建 4 个 pending 记录。"""
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._init_sub_steps(execution_context)

    sub_steps = [
        s async for s in NodeSubStep.objects.filter(
            node_execution=node_execution
        ).order_by("step_order")
    ]
    assert len(sub_steps) == 4
    assert sub_steps[0].step_type == "prepare_plan"
    assert sub_steps[0].name == "准备方案"
    assert sub_steps[0].status == SubStepStatus.PENDING
    assert sub_steps[1].step_type == "coding_execute"
    assert sub_steps[2].step_type == "create_mr"
    assert sub_steps[3].step_type == "send_notification"

    await node_execution.arefresh_from_db()
    assert node_execution.sub_step_total_count == 4


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_coding_node_emit_sub_step(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """AICodingNode.emit_sub_step 正确推进子步骤状态。"""
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._init_sub_steps(execution_context)

    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        await node.emit_sub_step(execution_context, "prepare_plan", SubStepStatus.RUNNING)

    sub_step = await NodeSubStep.objects.aget(
        node_execution=node_execution, step_type="prepare_plan"
    )
    assert sub_step.status == SubStepStatus.RUNNING
    assert sub_step.started_at is not None


# ============================================================================
# 回归测试：已有 PlanGenerationNode 仍通过 SubStepMixin 工作
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_plan_generation_node_still_works(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """重构后 AIPlanGenerationNode 通过 SubStepMixin 仍正常工作。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    await node._init_sub_steps(execution_context)

    sub_steps = [
        s async for s in NodeSubStep.objects.filter(
            node_execution=node_execution
        ).order_by("step_order")
    ]
    assert len(sub_steps) == 3
    assert sub_steps[0].step_type == "analyze"
