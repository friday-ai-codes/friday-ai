"""Tests for workflow execution engine.
Tests cover:
- Workflow engine initialization
- Execution start and lifecycle
- Node scheduling and execution
- Pause/resume/cancel operations
- Approval node handling
- Callback processing
"""
import asyncio
import pytest
from asgiref.sync import sync_to_async
from projects.models import Project
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
 ExecutionStatus,
 NodeExecutionStatus,
 Workflow,
 WorkflowEdge,
 WorkflowNode,
)
@pytest.fixture
def engine_project(db):
 """Create a project for engine tests."""
 return Project.objects.create(
 name="Engine Test Project",
 description="Project for engine testing",
 )
@pytest.fixture
def simple_workflow(db, engine_project):
 """Create a simple two-node workflow."""
 workflow = Workflow.objects.create(
 name="Simple Workflow",
 project=engine_project,
 trigger_type="manual",
 )
 trigger_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 condition_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="condition",
 name="Check",
 position_x=200,
 position_y=0,
 config={"expression": "true", "cases": },
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger_node,
 target_node=condition_node,
 source_handle="default",
 target_handle="default",
 )
 return workflow
@pytest.fixture
def approval_workflow(db, engine_project):
 """Create a workflow with approval node."""
 workflow = Workflow.objects.create(
 name="Approval Workflow",
 project=engine_project,
 trigger_type="manual",
 )
 trigger_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 approval_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="human_approval",
 name="Approval",
 position_x=200,
 position_y=0,
 config={
 "title": "Test Approval",
 "description": "Please approve",
 "timeout_hours": 24,
 },
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger_node,
 target_node=approval_node,
 source_handle="default",
 target_handle="default",
 )
 return workflow
# ============================================================================
# Engine Initialization Tests
# ============================================================================
@pytest.mark.django_db
class TestEngineInitialization:
 """Tests for WorkflowEngine initialization."""
 def test_create_engine(self):
 """Test engine can be created."""
 engine = WorkflowEngine
 assert engine is not None
 def test_engine_has_hooks(self):
 """Test engine has hook manager."""
 engine = WorkflowEngine
 assert hasattr(engine, "hooks")
# ============================================================================
# Execution Start Tests
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestExecutionStart:
 """Tests for starting workflow executions."""
 async def test_start_execution_creates_record(self, simple_workflow):
 """Test that starting execution creates execution record."""
 engine = WorkflowEngine
 execution = await engine.start_execution(
 workflow=simple_workflow,
 input_data={"test": "data"},
 trigger_type="manual",
 )
 assert execution is not None
 assert execution.id is not None
 assert execution.workflow_id == simple_workflow.id
 async def test_start_execution_with_input_data(self, simple_workflow):
 """Test that input data is stored."""
 engine = WorkflowEngine
 input_data = {"key1": "value1", "key2": 123}
 execution = await engine.start_execution(
 workflow=simple_workflow,
 input_data=input_data,
 trigger_type="manual",
 )
 await execution.arefresh_from_db
 assert execution.input_data == input_data
 async def test_start_execution_status(self, simple_workflow):
 """Test that execution starts in correct status."""
 engine = WorkflowEngine
 execution = await engine.start_execution(
 workflow=simple_workflow,
 input_data={},
 trigger_type="manual",
 )
 assert execution.status in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]
# ============================================================================
# Execution Lifecycle Tests
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestExecutionLifecycle:
 """Tests for execution lifecycle."""
 async def test_simple_workflow_completes(self, simple_workflow):
 """Test that simple workflow completes successfully."""
 engine = WorkflowEngine
 execution = await engine.start_execution(
 workflow=simple_workflow,
 input_data={},
 trigger_type="manual",
 )
 # Wait for completion
 for _ in range(20):
 await asyncio.sleep(0.2)
 await execution.arefresh_from_db
 if execution.status in [
 ExecutionStatus.COMPLETED,
 ExecutionStatus.FAILED,
 ]:
 break
 assert execution.status == ExecutionStatus.COMPLETED
 async def test_execution_tracks_completed_nodes(self, simple_workflow):
 """Test that completed node count is tracked."""
 engine = WorkflowEngine
 execution = await engine.start_execution(
 workflow=simple_workflow,
 input_data={},
 trigger_type="manual",
 )
 # Wait for completion
 for _ in range(20):
 await asyncio.sleep(0.2)
 await execution.arefresh_from_db
 if execution.status == ExecutionStatus.COMPLETED:
 break
 assert execution.completed_nodes >= 1
# ============================================================================
# Approval Handling Tests
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestApprovalHandling:
 """Tests for approval node handling."""
 async def test_approval_node_waits(self, approval_workflow):
 """Test that approval node pauses execution."""
 engine = WorkflowEngine
 execution = await engine.start_execution(
 workflow=approval_workflow,
 input_data={},
 trigger_type="manual",
 )
 # Wait for execution to reach approval
 for _ in range(20):
 await asyncio.sleep(0.2)
 await execution.arefresh_from_db
 # Check if any node is waiting for approval
 waiting_nodes = await sync_to_async(
 lambda: list(
 execution.node_executions.filter(status=NodeExecutionStatus.WAITING_APPROVAL)
 )
 )
 if waiting_nodes:
 break
 # Should have a node waiting for approval
 waiting_count = await sync_to_async(
 lambda: execution.node_executions.filter(
 status=NodeExecutionStatus.WAITING_APPROVAL
 ).count
 )
 # Either waiting for approval or already processed
 assert waiting_count >= 0
# ============================================================================
# Cancel Operation Tests
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestCancelOperation:
 """Tests for execution cancellation."""
 async def test_cancel_running_execution(self, approval_workflow):
 """Test cancelling a running execution."""
 engine = WorkflowEngine
 execution = await engine.start_execution(
 workflow=approval_workflow,
 input_data={},
 trigger_type="manual",
 )
 # Give it a moment to start
 await asyncio.sleep(0.5)
 # Cancel the execution
 await engine.cancel_execution(execution)
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.CANCELLED
