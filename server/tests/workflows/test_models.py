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
from projects.models import Project
from workflows.models import (
 ExecutionStatus,
 NodeExecution,
 NodeExecutionStatus,
 Workflow,
 WorkflowEdge,
 WorkflowExecution,
 WorkflowNode,
)
@pytest.fixture
def workflow_project(db):
 """Create a project for workflow tests."""
 return Project.objects.create(
 name="Workflow Test Project",
 description="Project for workflow testing",
 )
@pytest.fixture
def workflow(db, workflow_project):
 """Create a test workflow."""
 return Workflow.objects.create(
 name="Test Workflow",
 description="A test workflow",
 project=workflow_project,
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
 config={"expression": "true", "cases": },
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
 project=workflow_project,
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
 original_node_count = original.nodes.count
 original_edge_count = original.edges.count
 # Clone the workflow
 cloned = original.clone(new_name="Cloned Workflow")
 assert cloned.id != original.id
 assert cloned.name == "Cloned Workflow"
 assert cloned.nodes.count == original_node_count
 assert cloned.edges.count == original_edge_count
 def test_workflow_to_json(self, workflow_with_nodes):
 """Test workflow JSON export."""
 data = workflow_with_nodes.to_json
 assert "name" in data
 assert "nodes" in data
 assert "edges" in data
 assert len(data["nodes"]) == 2
 assert len(data["edges"]) == 1
 def test_workflow_str(self, workflow):
 """Test workflow string representation."""
 assert str(workflow) == "Test Workflow"
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
 cloned = original.clone
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
 trigger_type="manual",
 )
 # Update to running
 execution.status = ExecutionStatus.RUNNING
 execution.save
 execution.refresh_from_db
 assert execution.status == ExecutionStatus.RUNNING
 # Update to completed
 execution.status = ExecutionStatus.COMPLETED
 execution.save
 execution.refresh_from_db
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
 trigger_type="feishu_webhook",
 context=context,
 )
 execution.refresh_from_db
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
 trigger_type="manual",
 )
 node_exec = NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 )
 # Pending -> Running
 node_exec.status = NodeExecutionStatus.RUNNING
 node_exec.save
 assert node_exec.status == NodeExecutionStatus.RUNNING
 # Running -> Completed
 node_exec.status = NodeExecutionStatus.COMPLETED
 node_exec.output_data = {"result": "success"}
 node_exec.save
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
 trigger_type="manual",
 )
 node_exec = NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 status=NodeExecutionStatus.WAITING_APPROVAL,
 )
 assert node_exec.status == NodeExecutionStatus.WAITING_APPROVAL
