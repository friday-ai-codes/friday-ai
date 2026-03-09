"""子步骤 emit 和 signal 广播测试。
覆盖 和 需求：
- _init_sub_steps 批量创建 pending 记录
- emit_sub_step 推进状态 + 发送 signal
- signal handler 广播 sub_step.update 到 MONITOR_GROUP
- NodeExecution 进度字段更新
- NodeExecutionSerializer/NodeExecutionListSerializer 返回 sub_step_progress
"""
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
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
def workflow(db: None, project: "Project") -> "Workflow":
 """创建测试工作流。"""
 from workflows.models.workflow import Workflow
 return Workflow.objects.create(name="Test Workflow", project=project)
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
# ============================================================================
# Signal + Handler Tests
# ============================================================================
@pytest.mark.django_db
def test_signal_triggers_broadcast(node_execution: NodeExecution) -> None:
 """emit sub_step_updated signal → handler 调用 channel_layer.group_send。"""
 # 创建一个子步骤
 sub_step = NodeSubStep.objects.create(
 node_execution=node_execution,
 step_type="analyze",
 name="分析需求",
 step_order=0,
 status=SubStepStatus.RUNNING,
 )
 mock_channel_layer = MagicMock
 mock_channel_layer.group_send = AsyncMock
 with patch("workflows.signal_handlers.get_channel_layer", return_value=mock_channel_layer):
 sub_step_updated.send(
 sender=type(node_execution),
 sub_step=sub_step,
 node_execution_id=node_execution.id,
 )
 # 验证 group_send 被调用
 mock_channel_layer.group_send.assert_called_once
 call_args = mock_channel_layer.group_send.call_args
 # 第一个参数是 group name
 assert call_args[0][0] == "monitor"
 # 第二个参数是消息
 msg = call_args[0][1]
 assert msg["type"] == "monitor.event"
 assert msg["data"]["event"] == "sub_step.update"
 assert msg["data"]["node_execution_id"] == str(node_execution.id)
 assert msg["data"]["data"]["step_type"] == "analyze"
 assert msg["data"]["data"]["status"] == "running"
 assert msg["data"]["data"]["name"] == "分析需求"
@pytest.mark.django_db
def test_signal_handler_skips_without_channel_layer -> None:
 """channel_layer 为 None 时 handler 静默跳过。"""
 from workflows.signal_handlers import handle_sub_step_updated
 mock_sub_step = MagicMock
 with patch("workflows.signal_handlers.get_channel_layer", return_value=None):
 # 不应抛出异常
 handle_sub_step_updated(
 sender=object,
 sub_step=mock_sub_step,
 node_execution_id=uuid.uuid4,
 )
# ============================================================================
# NodeExecution Progress Field Tests
# ============================================================================
@pytest.mark.django_db
def test_progress_count_defaults(node_execution: NodeExecution) -> None:
 """NodeExecution 进度字段默认值为 0。"""
 assert node_execution.sub_step_completed_count == 0
 assert node_execution.sub_step_total_count == 0
