"""子步骤 emit 和 signal 广播测试。

覆盖 work item 和 work item 需求：
- _init_sub_steps() 批量创建 pending 记录
- emit_sub_step() 推进状态 + 发送 signal
- signal handler 广播 sub_step.update 到 execution_{id} 组
- NodeExecution 进度字段更新
- NodeExecutionSerializer/NodeExecutionListSerializer 返回 sub_step_progress
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

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
from workflows.signals import sub_step_updated

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def workflow(db: None, project: "Space") -> "Workflow":
    """创建测试工作流。"""
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Test Workflow", space=project)


@pytest.fixture
def workflow_node(db: None, workflow: "Workflow") -> "WorkflowNode":
    """创建测试工作流节点。"""
    from workflows.models.node import WorkflowNode

    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_plan_generation",
        name="Test AI Node",
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
    """创建测试 ExecutionContext（使用真实 node_execution）。"""
    from workflows.nodes.base import ExecutionContext

    return ExecutionContext(
        execution_id=str(workflow_execution.id),
        node_id=str(node_execution.node_id),
        node_config={"user_prompt": "test prompt"},
        input_data={},
        workflow_context={},
        previous_outputs={},
        workflow_execution=workflow_execution,
        node_execution=node_execution,
    )


@pytest.fixture
def empty_context() -> "ExecutionContext":
    """创建无 node_execution 的 ExecutionContext。"""
    from workflows.nodes.base import ExecutionContext

    return ExecutionContext(
        execution_id="test-exec-id",
        node_id="test-node-id",
        node_config={},
        input_data={},
        workflow_context={},
        previous_outputs={},
        workflow_execution=None,
        node_execution=None,
    )


# ============================================================================
# Signal + Handler Tests
# ============================================================================


@pytest.mark.django_db
def test_signal_triggers_broadcast(node_execution: NodeExecution) -> None:
    """emit sub_step_updated signal → handler 调用 channel_layer.group_send。"""
    sub_step = NodeSubStep.objects.create(
        node_execution=node_execution,
        step_type="analyze",
        name="分析需求",
        step_order=0,
        status=SubStepStatus.RUNNING,
    )

    mock_channel_layer = MagicMock()
    mock_channel_layer.group_send = AsyncMock()

    with patch("workflows.signal_handlers.get_channel_layer", return_value=mock_channel_layer):
        sub_step_updated.send(
            sender=type(node_execution),
            sub_step=sub_step,
            node_execution_id=node_execution.id,
        )

    mock_channel_layer.group_send.assert_called_once()
    call_args = mock_channel_layer.group_send.call_args
    assert call_args[0][0] == f"execution_{node_execution.workflow_execution_id}"
    msg = call_args[0][1]
    assert msg["type"] == "workflow.event"
    assert msg["event"] == "sub_step.update"
    assert msg["node_execution_id"] == str(node_execution.id)
    assert msg["data"]["step_type"] == "analyze"
    assert msg["data"]["status"] == "running"
    assert msg["data"]["name"] == "分析需求"


@pytest.mark.django_db
def test_signal_handler_skips_without_channel_layer() -> None:
    """channel_layer 为 None 时 handler 静默跳过。"""
    from workflows.signal_handlers import handle_sub_step_updated

    mock_sub_step = MagicMock()
    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        handle_sub_step_updated(
            sender=object,
            sub_step=mock_sub_step,
            node_execution_id=uuid.uuid4(),
        )


# ============================================================================
# NodeExecution Progress Field Tests
# ============================================================================


@pytest.mark.django_db
def test_progress_count_defaults(node_execution: NodeExecution) -> None:
    """NodeExecution 进度字段默认值为 0。"""
    assert node_execution.sub_step_completed_count == 0
    assert node_execution.sub_step_total_count == 0


# ============================================================================
# _init_sub_steps Tests
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_init_sub_steps_creates_pending(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """_init_sub_steps() 批量创建 pending 记录，设置总数。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    await node._init_sub_steps(execution_context)

    # 验证创建了 3 个子步骤
    sub_steps = [
        s async for s in NodeSubStep.objects.filter(
            node_execution=node_execution
        ).order_by("step_order")
    ]
    assert len(sub_steps) == 3
    assert sub_steps[0].step_type == "analyze"
    assert sub_steps[0].name == "分析需求"
    assert sub_steps[0].step_order == 0
    assert sub_steps[0].status == SubStepStatus.PENDING
    assert sub_steps[1].step_type == "generate_plan"
    assert sub_steps[2].step_type == "review"

    # 验证 NodeExecution 总数已更新
    await node_execution.arefresh_from_db()
    assert node_execution.sub_step_total_count == 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_init_sub_steps_no_execution(empty_context: "ExecutionContext") -> None:
    """node_execution 为 None 时 _init_sub_steps() 静默返回。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    # 不应抛出异常
    await node._init_sub_steps(empty_context)


# ============================================================================
# emit_sub_step Tests
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_emit_sub_step_running(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """emit_sub_step(running) 更新状态和 started_at。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    await node._init_sub_steps(execution_context)

    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        await node.emit_sub_step(execution_context, "analyze", SubStepStatus.RUNNING)

    sub_step = await NodeSubStep.objects.aget(
        node_execution=node_execution, step_type="analyze"
    )
    assert sub_step.status == SubStepStatus.RUNNING
    assert sub_step.started_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_emit_sub_step_completed(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """emit_sub_step(completed) 更新状态、completed_at 和进度计数。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    await node._init_sub_steps(execution_context)

    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        await node.emit_sub_step(execution_context, "analyze", SubStepStatus.RUNNING)
        await node.emit_sub_step(execution_context, "analyze", SubStepStatus.COMPLETED)

    sub_step = await NodeSubStep.objects.aget(
        node_execution=node_execution, step_type="analyze"
    )
    assert sub_step.status == SubStepStatus.COMPLETED
    assert sub_step.completed_at is not None

    await node_execution.arefresh_from_db()
    assert node_execution.sub_step_completed_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_emit_sub_step_failed(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """emit_sub_step(failed) 更新状态和 completed_at，但不增加 completed_count。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    await node._init_sub_steps(execution_context)

    with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
        await node.emit_sub_step(execution_context, "analyze", SubStepStatus.RUNNING)
        await node.emit_sub_step(execution_context, "analyze", SubStepStatus.FAILED)

    sub_step = await NodeSubStep.objects.aget(
        node_execution=node_execution, step_type="analyze"
    )
    assert sub_step.status == SubStepStatus.FAILED
    assert sub_step.completed_at is not None

    await node_execution.arefresh_from_db()
    assert node_execution.sub_step_completed_count == 0  # failed 不增加


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_emit_sub_step_sends_signal(
    execution_context: "ExecutionContext",
    node_execution: NodeExecution,
) -> None:
    """emit_sub_step() 发送 sub_step_updated signal。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    await node._init_sub_steps(execution_context)

    signal_received: list[dict[str, Any]] = []

    def signal_handler(sender: type, sub_step: Any, node_execution_id: uuid.UUID, **kwargs: Any) -> None:
        signal_received.append({
            "step_type": sub_step.step_type,
            "status": sub_step.status,
            "node_execution_id": node_execution_id,
        })

    sub_step_updated.connect(signal_handler)
    try:
        with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
            await node.emit_sub_step(execution_context, "analyze", SubStepStatus.RUNNING)
    finally:
        sub_step_updated.disconnect(signal_handler)

    assert len(signal_received) == 1
    assert signal_received[0]["step_type"] == "analyze"
    assert signal_received[0]["status"] == SubStepStatus.RUNNING
    assert signal_received[0]["node_execution_id"] == node_execution.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_emit_sub_step_no_execution(empty_context: "ExecutionContext") -> None:
    """node_execution 为 None 时 emit_sub_step() 静默返回。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    node = AIPlanGenerationNode()
    # 不应抛出异常
    await node.emit_sub_step(empty_context, "analyze", SubStepStatus.RUNNING)


# ============================================================================
# AIPlanGenerationNode sub_steps Declaration Tests
# ============================================================================


def test_plan_generation_node_sub_steps() -> None:
    """AIPlanGenerationNode 声明 3 个子步骤。"""
    from workflows.nodes.ai.plan_generation import AIPlanGenerationNode

    assert len(AIPlanGenerationNode.sub_steps) == 3
    step_types = [s[0] for s in AIPlanGenerationNode.sub_steps]
    assert step_types == ["analyze", "generate_plan", "review"]


def test_base_node_sub_steps_empty() -> None:
    """AIAgentBaseNode 默认 sub_steps 为空列表。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode

    assert AIAgentBaseNode.sub_steps == []


# ============================================================================
# Serializer sub_step_progress Tests (work item)
# ============================================================================


@pytest.mark.django_db
def test_node_execution_serializer_progress_with_steps(
    node_execution: NodeExecution,
) -> None:
    """NodeExecutionSerializer 返回 sub_step_progress（有子步骤时）。"""
    from workflows.api.serializers import NodeExecutionSerializer

    node_execution.sub_step_total_count = 3
    node_execution.sub_step_completed_count = 1
    node_execution.save(update_fields=["sub_step_total_count", "sub_step_completed_count"])

    serializer = NodeExecutionSerializer(node_execution)
    data = serializer.data
    assert data["sub_step_progress"] == {"completed": 1, "total": 3}


@pytest.mark.django_db
def test_node_execution_serializer_progress_none(
    node_execution: NodeExecution,
) -> None:
    """NodeExecutionSerializer 无子步骤时 sub_step_progress 为 None。"""
    from workflows.api.serializers import NodeExecutionSerializer

    serializer = NodeExecutionSerializer(node_execution)
    data = serializer.data
    assert data["sub_step_progress"] is None


@pytest.mark.django_db
def test_node_execution_list_serializer_progress(
    node_execution: NodeExecution,
) -> None:
    """NodeExecutionListSerializer 返回 sub_step_progress。"""
    from workflows.api.serializers import NodeExecutionListSerializer

    node_execution.sub_step_total_count = 5
    node_execution.sub_step_completed_count = 3
    node_execution.save(update_fields=["sub_step_total_count", "sub_step_completed_count"])

    serializer = NodeExecutionListSerializer(node_execution)
    data = serializer.data
    assert data["sub_step_progress"] == {"completed": 3, "total": 5}


@pytest.mark.django_db
def test_node_execution_list_serializer_progress_none(
    node_execution: NodeExecution,
) -> None:
    """NodeExecutionListSerializer 无子步骤时 sub_step_progress 为 None。"""
    from workflows.api.serializers import NodeExecutionListSerializer

    serializer = NodeExecutionListSerializer(node_execution)
    data = serializer.data
    assert data["sub_step_progress"] is None
