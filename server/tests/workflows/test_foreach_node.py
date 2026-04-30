"""Tests for ForEachNode.
Covers:
- Registry registration
- Sequential mode
- Parallel mode
- Abort on error
- Continue on error
- Max concurrency limit
- Template variable resolution
"""
import asyncio
from unittest.mock import MagicMock
import pytest
from workflows.nodes.base import ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import NodeRegistry
class TestForEachNodeRegistry:
 """Test 1: ForEachNode registered in NodeRegistry."""
 @pytest.mark.django_db
 def test_foreach_registered(self):
 registry = NodeRegistry
 node_class = registry.get("foreach")
 assert node_class is not None
 assert node_class.node_type == "foreach"
 assert node_class.category == NodeCategory.CONTROL
 assert node_class.execution_mode == "server_local"
class TestForEachNodeSequential:
 """Test 2: Sequential mode iterates over list."""
 @pytest.mark.asyncio
 async def test_sequential_mode(self):
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 context = ExecutionContext(
 execution_id="exec-001",
 node_id="node-001",
 node_config={
 "list_source": "{{input.items}}",
 "execution_mode": "sequential",
 "max_concurrency": 5,
 "on_iteration_error": "abort",
 },
 input_data={"items": [1, 2, 3]},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert len(result.output["results"]) == 3
 assert result.output["success_count"] == 3
 assert result.output["failed_count"] == 0
 # Each iteration returns the item itself
 assert result.output["results"] == [1, 2, 3]
class TestForEachNodeParallel:
 """Test 3: Parallel mode produces same results as sequential."""
 @pytest.mark.asyncio
 async def test_parallel_mode(self):
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 context = ExecutionContext(
 execution_id="exec-002",
 node_id="node-002",
 node_config={
 "list_source": "{{input.items}}",
 "execution_mode": "parallel",
 "max_concurrency": 5,
 "on_iteration_error": "abort",
 },
 input_data={"items": [1, 2, 3]},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert len(result.output["results"]) == 3
 assert result.output["success_count"] == 3
 assert result.output["failed_count"] == 0
 # Order may differ in parallel mode
 assert sorted(result.output["results"]) == [1, 2, 3]
class TestForEachNodeAbortOnError:
 """Test 4: Abort mode stops on first failure."""
 @pytest.mark.asyncio
 async def test_abort_stops_on_failure(self):
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 # Mock _run_iteration to simulate failure on item 2
 call_count = 0
 async def mock_run_iteration(ctx, item, index):
 nonlocal call_count
 call_count += 1
 if item == 2:
 return {"status": "failed", "error": "simulated error", "item": item, "index": index}
 return {"status": "completed", "output": item, "item": item, "index": index}
 node._run_iteration = mock_run_iteration # type: ignore[method-assign]
 context = ExecutionContext(
 execution_id="exec-003",
 node_id="node-003",
 node_config={
 "list_source": "{{input.items}}",
 "execution_mode": "sequential",
 "max_concurrency": 5,
 "on_iteration_error": "abort",
 },
 input_data={"items": [1, 2, 3]},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 # Should have executed items 1 and 2, then aborted
 assert call_count == 2
 assert result.output["success_count"] == 1
 assert result.output["failed_count"] == 1
 assert len(result.output["results"]) == 2
class TestForEachNodeContinueOnError:
 """Test 5: Continue mode records errors and proceeds."""
 @pytest.mark.asyncio
 async def test_continue_records_errors(self):
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 async def mock_run_iteration(ctx, item, index):
 if item == 2:
 return {"status": "failed", "error": "simulated error", "item": item, "index": index}
 return {"status": "completed", "output": item, "item": item, "index": index}
 node._run_iteration = mock_run_iteration # type: ignore[method-assign]
 context = ExecutionContext(
 execution_id="exec-004",
 node_id="node-004",
 node_config={
 "list_source": "{{input.items}}",
 "execution_mode": "sequential",
 "max_concurrency": 5,
 "on_iteration_error": "continue",
 },
 input_data={"items": [1, 2, 3]},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["success_count"] == 2
 assert result.output["failed_count"] == 1
 assert len(result.output["results"]) == 3
 # The failed item should be recorded as an error dict
 failed_results = [r for r in result.output["results"] if isinstance(r, dict) and r.get("status") == "failed"]
 assert len(failed_results) == 1
 assert failed_results[0]["item"] == 2
class TestForEachNodeMaxConcurrency:
 """Test 6: Max concurrency limits parallel execution."""
 @pytest.mark.asyncio
 async def test_max_concurrency_respected(self):
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 concurrent_count = 0
 max_observed = 0
 async def mock_run_iteration(ctx, item, index):
 nonlocal concurrent_count, max_observed
 concurrent_count += 1
 max_observed = max(max_observed, concurrent_count)
 await asyncio.sleep(0.05) # Small delay to allow overlap
 concurrent_count -= 1
 return {"status": "completed", "output": item, "item": item, "index": index}
 node._run_iteration = mock_run_iteration # type: ignore[method-assign]
 context = ExecutionContext(
 execution_id="exec-005",
 node_id="node-005",
 node_config={
 "list_source": "{{input.items}}",
 "execution_mode": "parallel",
 "max_concurrency": 2,
 "on_iteration_error": "abort",
 },
 input_data={"items": [1, 2, 3, 4, 5]},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 # Max observed concurrency should not exceed 2
 assert max_observed <= 2, f"Expected max concurrency <= 2, got {max_observed}"
 assert result.output["success_count"] == 5
class TestForEachNodeTemplateResolution:
 """Test 7: List input supports template variable resolution."""
 @pytest.mark.asyncio
 async def test_template_variable_list(self):
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 context = ExecutionContext(
 execution_id="exec-006",
 node_id="node-006",
 node_config={
 "list_source": "{{input.items}}",
 "execution_mode": "sequential",
 "max_concurrency": 5,
 "on_iteration_error": "abort",
 },
 input_data={"items": ["a", "b", "c"]},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["results"] == ["a", "b", "c"]
 @pytest.mark.asyncio
 async def test_non_list_input_wrapped(self):
 """Non-list input should be wrapped as single-element list."""
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 context = ExecutionContext(
 execution_id="exec-007",
 node_id="node-007",
 node_config={
 "list_source": "{{input.value}}",
 "execution_mode": "sequential",
 "max_concurrency": 5,
 "on_iteration_error": "abort",
 },
 input_data={"value": "single_item"},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["results"] == ["single_item"]
 assert result.output["success_count"] == 1
 @pytest.mark.asyncio
 async def test_json_string_parsed(self):
 """JSON string input should be parsed to list."""
 from workflows.nodes.control.loop import ForEachNode
 node = ForEachNode
 context = ExecutionContext(
 execution_id="exec-008",
 node_id="node-008",
 node_config={
 "list_source": "{{input.json_str}}",
 "execution_mode": "sequential",
 "max_concurrency": 5,
 "on_iteration_error": "abort",
 },
 input_data={"json_str": '[1, 2, 3]'},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["results"] == [1, 2, 3]
