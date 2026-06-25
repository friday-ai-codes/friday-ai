"""Tests for workflow models.

Tests cover:
- Workflow model CRUD operations
- WorkflowNode model operations
- WorkflowEdge model operations
- WorkflowExecution model and status management
- NodeExecution model and approval methods
"""

import pytest
from django.db import IntegrityError

from projects.models import Space
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    NodeSubStep,
    SubStepStatus,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)


@pytest.fixture
def workflow_project(db):
    """Create a project for workflow tests."""
    return Space.objects.create(
        name="Workflow Test Space",
        description="Space for workflow testing",
    )


@pytest.fixture
def workflow(db, workflow_project):
    """Create a test workflow."""
    return Workflow.objects.create(
        name="Test Workflow",
        description="A test workflow",
        space=workflow_project,
        trigger_type="manual",
    )


@pytest.fixture
def workflow_with_nodes(db, workflow):
    """Create a workflow with nodes and edges."""
    # Create nodes
    trigger_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Start",
        position_x=0,
        position_y=0,
    )
    action_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="condition",
        name="Check",
        position_x=200,
        position_y=0,
        config={"expression": "true", "cases": []},
    )

    # Create edge
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger_node,
        target_node=action_node,
        source_handle="default",
        target_handle="default",
    )

    return workflow


# ============================================================================
# Workflow Model Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowModel:
    """Tests for the Workflow model."""

    def test_create_workflow(self, workflow_project):
        """Test basic workflow creation."""
        workflow = Workflow.objects.create(
            name="New Workflow",
            space=workflow_project,
            trigger_type="manual",
        )
        assert workflow.id is not None
        assert workflow.name == "New Workflow"
        assert workflow.trigger_type == "manual"
        assert workflow.is_active is True

    def test_workflow_requires_project(self, db):
        """Test that workflow requires a project."""
        with pytest.raises(IntegrityError):
            Workflow.objects.create(
                name="Orphan Workflow",
                trigger_type="manual",
            )

    def test_workflow_clone(self, workflow_with_nodes):
        """Test workflow cloning functionality."""
        original = workflow_with_nodes
        original_node_count = original.nodes.count()
        original_edge_count = original.edges.count()

        # Clone the workflow
        cloned = original.clone(new_name="Cloned Workflow")

        assert cloned.id != original.id
        assert cloned.name == "Cloned Workflow"
        assert cloned.nodes.count() == original_node_count
        assert cloned.edges.count() == original_edge_count

    def test_workflow_to_json(self, workflow_with_nodes):
        """Test workflow JSON export."""
        data = workflow_with_nodes.to_json()

        # to_json returns nested structure with version, workflow, nodes, edges
        assert "version" in data
        assert "workflow" in data
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_workflow_str(self, workflow):
        """Test workflow string representation."""
        assert str(workflow) == "Test Workflow (Workflow Test Space)"


# ============================================================================
# WorkflowNode Model Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowNodeModel:
    """Tests for the WorkflowNode model."""

    def test_create_node(self, workflow):
        """Test basic node creation."""
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="Test Node",
            position_x=100,
            position_y=200,
        )
        assert node.id is not None
        assert node.node_type == "manual_trigger"
        assert node.position_x == 100

    def test_node_config_defaults(self, workflow):
        """Test node config defaults to empty dict."""
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Config Test",
            position_x=0,
            position_y=0,
        )
        assert node.config == {}

    def test_node_clone(self, workflow):
        """Test node cloning."""
        original = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="http_request",
            name="HTTP Node",
            config={"url": "https://example.com"},
            position_x=100,
            position_y=100,
        )

        cloned = original.clone(new_workflow=workflow)
        assert cloned.id != original.id
        assert cloned.name == original.name
        assert cloned.config == original.config


# ============================================================================
# WorkflowEdge Model Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowEdgeModel:
    """Tests for the WorkflowEdge model."""

    def test_create_edge(self, workflow):
        """Test basic edge creation."""
        node1 = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="Node 1",
            position_x=0,
            position_y=0,
        )
        node2 = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Node 2",
            position_x=200,
            position_y=0,
        )

        edge = WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node1,
            target_node=node2,
            source_handle="default",
            target_handle="default",
        )

        assert edge.id is not None
        assert edge.source_node == node1
        assert edge.target_node == node2

    def test_edge_unique_constraint(self, workflow):
        """Test edge uniqueness constraint."""
        node1 = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="Node 1",
            position_x=0,
            position_y=0,
        )
        node2 = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Node 2",
            position_x=200,
            position_y=0,
        )

        # Create first edge
        WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node1,
            target_node=node2,
            source_handle="default",
            target_handle="default",
        )

        # Try to create duplicate edge - should fail
        with pytest.raises(IntegrityError):
            WorkflowEdge.objects.create(
                workflow=workflow,
                source_node=node1,
                target_node=node2,
                source_handle="default",
                target_handle="default",
            )


# ============================================================================
# WorkflowExecution Model Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowExecutionModel:
    """Tests for the WorkflowExecution model."""

    def test_create_execution(self, workflow):
        """Test basic execution creation."""
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
            input_data={"key": "value"},
        )
        assert execution.id is not None
        assert execution.status == ExecutionStatus.PENDING
        assert execution.input_data == {"key": "value"}

    def test_execution_status_transitions(self, workflow):
        """Test execution status can be updated."""
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
        )

        # Update to running
        execution.status = ExecutionStatus.RUNNING
        execution.save()
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.RUNNING

        # Update to completed
        execution.status = ExecutionStatus.COMPLETED
        execution.save()
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

    def test_execution_context_storage(self, workflow):
        """Test execution context JSON storage."""
        context = {
            "work_item_id": "12345",
            "repository_path": "/path/to/repo",
            "nested": {"key": "value"},
        }
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="feishu_webhook",
            context=context,
        )
        execution.refresh_from_db()
        assert execution.context == context


# ============================================================================
# NodeExecution Model Tests
# ============================================================================


@pytest.mark.django_db
class TestNodeExecutionModel:
    """Tests for the NodeExecution model."""

    def test_create_node_execution(self, workflow):
        """Test basic node execution creation."""
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="Test Node",
            position_x=0,
            position_y=0,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
        )

        node_exec = NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
        )
        assert node_exec.id is not None
        assert node_exec.status == NodeExecutionStatus.PENDING

    def test_node_execution_status_flow(self, workflow):
        """Test node execution status transitions."""
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Test Node",
            position_x=0,
            position_y=0,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
        )

        node_exec = NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
        )

        # Pending -> Running
        node_exec.status = NodeExecutionStatus.RUNNING
        node_exec.save()
        assert node_exec.status == NodeExecutionStatus.RUNNING

        # Running -> Completed
        node_exec.status = NodeExecutionStatus.COMPLETED
        node_exec.output_data = {"result": "success"}
        node_exec.save()
        assert node_exec.status == NodeExecutionStatus.COMPLETED
        assert node_exec.output_data == {"result": "success"}

    def test_node_execution_approval_status(self, workflow):
        """Test node execution approval status."""
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="human_approval",
            name="Approval Node",
            position_x=0,
            position_y=0,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
        )

        node_exec = NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
            status=NodeExecutionStatus.WAITING_APPROVAL,
        )

        assert node_exec.status == NodeExecutionStatus.WAITING_APPROVAL


# ============================================================================
# NodeSubStep Model Tests
# ============================================================================


@pytest.mark.django_db
class TestNodeSubStepModel:
    """Tests for the NodeSubStep model."""

    @pytest.fixture
    def node_execution(self, workflow):
        """创建用于测试的 NodeExecution。"""
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="ai_coding",
            name="AI Coding Node",
            position_x=100,
            position_y=100,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
        )
        return NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
        )

    def test_create_sub_step(self, node_execution):
        """Test NodeSubStep 可创建并关联到 NodeExecution。"""
        sub_step = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="调用工具",
            step_type="tool_call",
            step_order=1,
        )
        assert sub_step.id is not None
        assert sub_step.status == SubStepStatus.PENDING
        assert sub_step.name == "调用工具"
        assert sub_step.step_type == "tool_call"
        assert sub_step.step_order == 1
        assert sub_step.input_data == {}
        assert sub_step.output_data == {}
        assert sub_step.started_at is None
        assert sub_step.completed_at is None

    def test_sub_step_status_enum(self):
        """Test SubStepStatus 枚举包含四个正确的值。"""
        assert SubStepStatus.PENDING == "pending"
        assert SubStepStatus.RUNNING == "running"
        assert SubStepStatus.COMPLETED == "completed"
        assert SubStepStatus.FAILED == "failed"
        assert len(SubStepStatus.choices) == 4

    def test_sub_steps_ordering(self, node_execution):
        """Test 子步骤按 step_order 排序。"""
        NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤3",
            step_type="code_generation",
            step_order=3,
        )
        NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤1",
            step_type="thinking",
            step_order=1,
        )
        NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤2",
            step_type="tool_call",
            step_order=2,
        )

        sub_steps = list(NodeSubStep.objects.filter(node_execution=node_execution))
        assert len(sub_steps) == 3
        assert sub_steps[0].name == "步骤1"
        assert sub_steps[1].name == "步骤2"
        assert sub_steps[2].name == "步骤3"

    def test_cascade_delete(self, node_execution):
        """Test 删除 NodeExecution 级联删除其 sub_steps。"""
        NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤1",
            step_type="thinking",
            step_order=1,
        )
        NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤2",
            step_type="tool_call",
            step_order=2,
        )

        assert NodeSubStep.objects.filter(node_execution=node_execution).count() == 2
        node_execution.delete()
        assert NodeSubStep.objects.count() == 0

    def test_mark_started(self, node_execution):
        """Test mark_started 方法更新状态和时间戳。"""
        sub_step = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤1",
            step_type="thinking",
            step_order=1,
        )

        sub_step.mark_started()
        sub_step.refresh_from_db()

        assert sub_step.status == SubStepStatus.RUNNING
        assert sub_step.started_at is not None

    def test_mark_completed(self, node_execution):
        """Test mark_completed 方法更新状态、时间戳和输出数据。"""
        sub_step = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤1",
            step_type="tool_call",
            step_order=1,
        )

        sub_step.mark_started()
        output = {"result": "success", "data": [1, 2, 3]}
        sub_step.mark_completed(output_data=output)
        sub_step.refresh_from_db()

        assert sub_step.status == SubStepStatus.COMPLETED
        assert sub_step.completed_at is not None
        assert sub_step.output_data == output

    def test_mark_failed(self, node_execution):
        """Test mark_failed 方法更新状态和记录错误。"""
        sub_step = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤1",
            step_type="code_generation",
            step_order=1,
        )

        sub_step.mark_started()
        sub_step.mark_failed(error="Code generation timeout")
        sub_step.refresh_from_db()

        assert sub_step.status == SubStepStatus.FAILED
        assert sub_step.completed_at is not None
        assert sub_step.output_data["error"] == "Code generation timeout"

    def test_duration_property(self, node_execution):
        """Test duration 属性计算。"""
        sub_step = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="步骤1",
            step_type="thinking",
            step_order=1,
        )

        # 未开始时 duration 为 None
        assert sub_step.duration is None

        # 开始但未完成时 duration 为 None
        sub_step.mark_started()
        assert sub_step.duration is None

        # 完成后 duration 有值
        sub_step.mark_completed()
        assert sub_step.duration is not None
        assert sub_step.duration >= 0

    def test_sub_step_with_input_output(self, node_execution):
        """Test 子步骤可存储复杂的输入输出数据。"""
        input_data = {"tool": "write_file", "path": "src/main.py", "content": "print('hello')"}
        output_data = {"success": True, "bytes_written": 15}

        sub_step = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="写入文件",
            step_type="tool_call",
            step_order=1,
            input_data=input_data,
            output_data=output_data,
        )
        sub_step.refresh_from_db()

        assert sub_step.input_data == input_data
        assert sub_step.output_data == output_data
