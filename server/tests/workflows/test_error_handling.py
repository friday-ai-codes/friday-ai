"""Tests for workflow node error handling framework.
Tests cover:
-: on_error field (abort/retry/ignore) with default abort
-: Retry with exponential backoff
-: Node timeout triggering on_error strategy
-: Continue-on-fail (ignore mode) with fallback_values
"""
import pytest
from projects.models import Project
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
 ExecutionStatus,
 NodeExecutionStatus,
 Workflow,
 WorkflowEdge,
 WorkflowNode,
)
from workflows.nodes.base import BaseNode, ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import NodeRegistry
# ---------------------------------------------------------------------------
# Test node types: controllable pass/fail for testing
# ---------------------------------------------------------------------------
class AlwaysFailNode(BaseNode):
 """Node that always fails — for testing error handling."""
 node_type = "test_always_fail"
 display_name = "Always Fail"
 description = "Always raises an exception"
 category = NodeCategory.ACTION
 execution_mode = "server_local"
 supports_retry = True
 _fail_count = 0
 async def execute(self, context: ExecutionContext) -> NodeResult:
 AlwaysFailNode._fail_count += 1
 raise RuntimeError(f"Intentional failure #{AlwaysFailNode._fail_count}")
class FailNTimesNode(BaseNode):
 """Node that fails N times then succeeds — for testing retry."""
 node_type = "test_fail_n_times"
 display_name = "Fail N Times"
 description = "Fails a configurable number of times then succeeds"
 category = NodeCategory.ACTION
 execution_mode = "server_local"
 supports_retry = True
 _call_count = 0
 _fail_until = 2 # Default: fail first 2 calls, succeed on 3rd
 async def execute(self, context: ExecutionContext) -> NodeResult:
 FailNTimesNode._call_count += 1
 if FailNTimesNode._call_count <= FailNTimesNode._fail_until:
 raise RuntimeError(f"Transient failure #{FailNTimesNode._call_count}")
 return NodeResult(status="completed", output={"result": "success"})
class SlowNode(BaseNode):
 """Node that takes a long time — for testing timeout."""
 node_type = "test_slow_node"
 display_name = "Slow Node"
 description = "Takes 10 seconds to execute"
 category = NodeCategory.ACTION
 execution_mode = "server_local"
 supports_retry = True
 _sleep_seconds = 10
 async def execute(self, context: ExecutionContext) -> NodeResult:
 await asyncio.sleep(SlowNode._sleep_seconds)
 return NodeResult(status="completed", output={"result": "done"})
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _register_test_nodes:
 """Register test node types for the duration of each test."""
 NodeRegistry.register(AlwaysFailNode)
 NodeRegistry.register(FailNTimesNode)
 NodeRegistry.register(SlowNode)
 yield
 NodeRegistry._nodes.pop("test_always_fail", None)
 NodeRegistry._nodes.pop("test_fail_n_times", None)
 NodeRegistry._nodes.pop("test_slow_node", None)
@pytest.fixture
def engine_project(db):
 """Create a project for error handling tests."""
 return Project.objects.create(
 name="Error Handling Test Project",
 description="Project for error handling testing",
 )
@pytest.fixture
def engine:
 """Create a WorkflowEngine instance."""
 return WorkflowEngine
@pytest.fixture
def abort_workflow(db, engine_project):
 """Workflow with a node that has on_error=abort (default)."""
 workflow = Workflow.objects.create(
 name="Abort Workflow",
 project=engine_project,
 trigger_type="manual",
 )
 trigger = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 fail_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="test_always_fail",
 name="Failing Node",
 position_x=200,
 position_y=0,
 on_error="abort",
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger,
 target_node=fail_node,
 )
 return workflow
@pytest.fixture
def retry_workflow(db, engine_project):
 """Workflow with a node configured for retry."""
 workflow = Workflow.objects.create(
 name="Retry Workflow",
 project=engine_project,
 trigger_type="manual",
 )
 trigger = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 flaky_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="test_fail_n_times",
 name="Flaky Node",
 position_x=200,
 position_y=0,
 on_error="retry",
 retry_times=3,
 retry_delay=1, # Short delay for tests
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger,
 target_node=flaky_node,
 )
 return workflow
@pytest.fixture
def ignore_workflow(db, engine_project):
 """Workflow with a node configured for ignore + fallback."""
 workflow = Workflow.objects.create(
 name="Ignore Workflow",
 project=engine_project,
 trigger_type="manual",
 )
 trigger = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 fail_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="test_always_fail",
 name="Ignored Fail",
 position_x=200,
 position_y=0,
 on_error="ignore",
 fallback_values={"result": "default_value"},
 )
 downstream_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Downstream",
 position_x=400,
 position_y=0,
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger,
 target_node=fail_node,
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=fail_node,
 target_node=downstream_node,
 )
 return workflow
@pytest.fixture
def timeout_retry_workflow(db, engine_project):
 """Workflow with a slow node: timeout + retry."""
 workflow = Workflow.objects.create(
 name="Timeout Retry Workflow",
 project=engine_project,
 trigger_type="manual",
 )
 trigger = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 slow_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="test_slow_node",
 name="Slow Node",
 position_x=200,
 position_y=0,
 on_error="retry",
 retry_times=1,
 retry_delay=1,
 node_timeout_seconds=1,
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger,
 target_node=slow_node,
 )
 return workflow
# ---------------------------------------------------------------------------
#: on_error field tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestOnErrorField:
 """: on_error field defaults and validation."""
 def test_on_error_field_default_abort(self, engine_project):
 """New nodes default to on_error=abort."""
 workflow = Workflow.objects.create(
 name="Test", project=engine_project, trigger_type="manual",
 )
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Test Node",
 position_x=0,
 position_y=0,
 )
 assert node.on_error == "abort"
 def test_on_error_choices_valid(self, engine_project):
 """Only abort/retry/ignore are valid on_error values."""
 workflow = Workflow.objects.create(
 name="Test", project=engine_project, trigger_type="manual",
 )
 for strategy in ("abort", "retry", "ignore"):
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name=f"Node {strategy}",
 position_x=0,
 position_y=0,
 on_error=strategy,
 )
 assert node.on_error == strategy
 def test_retry_times_default_zero(self, engine_project):
 """retry_times defaults to 0."""
 workflow = Workflow.objects.create(
 name="Test", project=engine_project, trigger_type="manual",
 )
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Test Node",
 position_x=0,
 position_y=0,
 )
 assert node.retry_times == 0
 def test_retry_delay_default_five(self, engine_project):
 """retry_delay defaults to 5."""
 workflow = Workflow.objects.create(
 name="Test", project=engine_project, trigger_type="manual",
 )
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Test Node",
 position_x=0,
 position_y=0,
 )
 assert node.retry_delay == 5
 def test_node_timeout_seconds_default_null(self, engine_project):
 """node_timeout_seconds defaults to null."""
 workflow = Workflow.objects.create(
 name="Test", project=engine_project, trigger_type="manual",
 )
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Test Node",
 position_x=0,
 position_y=0,
 )
 assert node.node_timeout_seconds is None
 def test_fallback_values_default_null(self, engine_project):
 """fallback_values defaults to null."""
 workflow = Workflow.objects.create(
 name="Test", project=engine_project, trigger_type="manual",
 )
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Test Node",
 position_x=0,
 position_y=0,
 )
 assert node.fallback_values is None
 @pytest.mark.asyncio
 async def test_abort_fails_workflow(self, engine, abort_workflow):
 """on_error=abort (default) causes workflow failure."""
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(abort_workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
# ---------------------------------------------------------------------------
#: Retry with exponential backoff
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestRetryBehavior:
 """: Retry with exponential backoff."""
 @pytest.mark.asyncio
 async def test_retry_succeeds_after_transient_failures(self, engine, retry_workflow):
 """Node fails twice, succeeds on 3rd attempt (retry_times=3)."""
 FailNTimesNode._call_count = 0
 FailNTimesNode._fail_until = 2
 execution = await engine.start_execution(retry_workflow, run_sync=True)
 assert execution.status == ExecutionStatus.COMPLETED
 @pytest.mark.asyncio
 async def test_retry_exhausted_returns_failed(self, engine, retry_workflow):
 """Node fails more times than retry_times -> workflow fails."""
 FailNTimesNode._call_count = 0
 FailNTimesNode._fail_until = 10 # Fail more than retry_times=3
 execution = await engine.start_execution(retry_workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
 @pytest.mark.asyncio
 async def test_retry_attempt_increments(self, engine, retry_workflow):
 """NodeExecution.attempt increments on each retry."""
 FailNTimesNode._call_count = 0
 FailNTimesNode._fail_until = 1 # Fail once, succeed on 2nd
 execution = await engine.start_execution(retry_workflow, run_sync=True)
 from workflows.models import NodeExecution
 flaky_ne = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node__node_type="test_fail_n_times",
 ).afirst
 assert flaky_ne is not None
 assert flaky_ne.attempt >= 2
 @pytest.mark.asyncio
 async def test_no_retry_when_on_error_abort(self, engine, abort_workflow):
 """on_error=abort does not retry even if retry_times > 0."""
 node = await WorkflowNode.objects.filter(
 workflow=abort_workflow,
 node_type="test_always_fail",
 ).afirst
 node.retry_times = 5
 await node.asave(update_fields=["retry_times"])
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(abort_workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
 assert AlwaysFailNode._fail_count == 1
# ---------------------------------------------------------------------------
#: Node timeout
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTimeoutBehavior:
 """: Node timeout triggers on_error strategy."""
 @pytest.mark.asyncio
 async def test_timeout_triggers_on_error_abort(self, engine, engine_project):
 """Timeout + on_error=abort -> workflow fails."""
 workflow = await Workflow.objects.acreate(
 name="Timeout Abort", project=engine_project, trigger_type="manual",
 )
 trigger = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Start",
 position_x=0, position_y=0,
 )
 slow_node = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="test_slow_node", name="Slow",
 position_x=200, position_y=0,
 on_error="abort", node_timeout_seconds=1,
 )
 await WorkflowEdge.objects.acreate(
 workflow=workflow, source_node=trigger, target_node=slow_node,
 )
 SlowNode._sleep_seconds = 10
 execution = await engine.start_execution(workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
 @pytest.mark.asyncio
 async def test_timeout_triggers_on_error_retry(self, engine, timeout_retry_workflow):
 """Timeout + on_error=retry -> retry is triggered after timeout."""
 SlowNode._sleep_seconds = 10
 execution = await engine.start_execution(timeout_retry_workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
 from workflows.models import NodeExecution
 slow_ne = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node__node_type="test_slow_node",
 ).afirst
 assert slow_ne is not None
 assert slow_ne.attempt > 1
 @pytest.mark.asyncio
 async def test_no_timeout_when_null(self, engine, engine_project):
 """node_timeout_seconds=None means no timeout — node runs fast and completes."""
 workflow = await Workflow.objects.acreate(
 name="No Timeout", project=engine_project, trigger_type="manual",
 )
 trigger = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Start",
 position_x=0, position_y=0,
 )
 fast_node = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="test_fail_n_times", name="Fast",
 position_x=200, position_y=0,
 on_error="abort", node_timeout_seconds=None,
 )
 await WorkflowEdge.objects.acreate(
 workflow=workflow, source_node=trigger, target_node=fast_node,
 )
 FailNTimesNode._call_count = 0
 FailNTimesNode._fail_until = 0
 execution = await engine.start_execution(workflow, run_sync=True)
 assert execution.status == ExecutionStatus.COMPLETED
# ---------------------------------------------------------------------------
#: Continue on Fail (ignore mode)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestIgnoreBehavior:
 """: on_error=ignore with fallback_values."""
 @pytest.mark.asyncio
 async def test_ignore_downstream_uses_fallback(self, engine, ignore_workflow):
 """on_error=ignore node fails -> downstream executes with fallback_values."""
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(ignore_workflow, run_sync=True)
 assert execution.status == ExecutionStatus.COMPLETED
 @pytest.mark.asyncio
 async def test_ignore_node_status_is_failed(self, engine, ignore_workflow):
 """Tolerated failure node has status=FAILED in DB."""
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(ignore_workflow, run_sync=True)
 from workflows.models import NodeExecution
 ignored_ne = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node__node_type="test_always_fail",
 ).afirst
 assert ignored_ne is not None
 assert ignored_ne.status == NodeExecutionStatus.FAILED
 @pytest.mark.asyncio
 async def test_ignore_without_fallback_values(self, engine, engine_project):
 """on_error=ignore without fallback_values -> downstream gets default."""
 workflow = await Workflow.objects.acreate(
 name="Ignore No Fallback", project=engine_project, trigger_type="manual",
 )
 trigger = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Start",
 position_x=0, position_y=0,
 )
 fail_node = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="test_always_fail", name="Fail No Fallback",
 position_x=200, position_y=0,
 on_error="ignore", fallback_values=None,
 )
 downstream = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Downstream",
 position_x=400, position_y=0,
 )
 await WorkflowEdge.objects.acreate(workflow=workflow, source_node=trigger, target_node=fail_node)
 await WorkflowEdge.objects.acreate(workflow=workflow, source_node=fail_node, target_node=downstream)
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(workflow, run_sync=True)
 assert execution.status == ExecutionStatus.COMPLETED
 @pytest.mark.asyncio
 async def test_abort_failure_skips_downstream(self, engine, engine_project):
 """on_error=abort failure -> downstream skipped, workflow fails."""
 workflow = await Workflow.objects.acreate(
 name="Abort Skips Downstream", project=engine_project, trigger_type="manual",
 )
 trigger = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Start",
 position_x=0, position_y=0,
 )
 fail_node = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="test_always_fail", name="Abort Fail",
 position_x=200, position_y=0, on_error="abort",
 )
 downstream = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Downstream",
 position_x=400, position_y=0,
 )
 await WorkflowEdge.objects.acreate(workflow=workflow, source_node=trigger, target_node=fail_node)
 await WorkflowEdge.objects.acreate(workflow=workflow, source_node=fail_node, target_node=downstream)
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
 from workflows.models import NodeExecution
 downstream_ne = await NodeExecution.objects.filter(
 workflow_execution=execution, node__name="Downstream",
 ).afirst
 assert downstream_ne is not None
 assert downstream_ne.status == NodeExecutionStatus.SKIPPED
 @pytest.mark.asyncio
 async def test_mixed_abort_and_ignore(self, engine, engine_project):
 """ignore failure + abort failure in parallel -> workflow fails (only abort counts)."""
 workflow = await Workflow.objects.acreate(
 name="Mixed", project=engine_project, trigger_type="manual",
 )
 trigger = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="manual_trigger", name="Start",
 position_x=0, position_y=0,
 )
 ignore_node = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="test_always_fail", name="Ignore Branch",
 position_x=200, position_y=0,
 on_error="ignore", fallback_values={"result": "fallback"},
 )
 abort_node = await WorkflowNode.objects.acreate(
 workflow=workflow, node_type="test_always_fail", name="Abort Branch",
 position_x=200, position_y=200, on_error="abort",
 )
 await WorkflowEdge.objects.acreate(workflow=workflow, source_node=trigger, target_node=ignore_node)
 await WorkflowEdge.objects.acreate(workflow=workflow, source_node=trigger, target_node=abort_node)
 AlwaysFailNode._fail_count = 0
 execution = await engine.start_execution(workflow, run_sync=True)
 assert execution.status == ExecutionStatus.FAILED
