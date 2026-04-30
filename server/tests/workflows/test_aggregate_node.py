"""Tests for VariableAggregateNode.
Covers:
- Registry registration
- Mappings with two upstream nodes
- Output field extraction
- Whole output object when output_field is empty
- Conflict resolution (later overrides earlier)
- Missing source_node graceful handling
"""
import pytest
from workflows.nodes.base import ExecutionContext, NodeCategory
from workflows.nodes.registry import NodeRegistry
class TestVariableAggregateNodeRegistry:
 """Test 1: VariableAggregateNode registered in NodeRegistry."""
 @pytest.mark.django_db
 def test_aggregate_registered(self):
 registry = NodeRegistry
 node_class = registry.get("aggregate")
 assert node_class is not None
 assert node_class.node_type == "aggregate"
 assert node_class.category == NodeCategory.CONTROL
 assert node_class.execution_mode == "server_local"
class TestVariableAggregateNodeMappings:
 """Test 2: Mappings bind upstream outputs to target keys."""
 @pytest.mark.asyncio
 async def test_two_upstream_nodes(self):
 from workflows.nodes.data.aggregate import VariableAggregateNode
 node = VariableAggregateNode
 context = ExecutionContext(
 execution_id="exec-001",
 node_id="node-001",
 node_config={
 "mappings": [
 {"source_node": "node_a", "output_field": "", "target_key": "result_a"},
 {"source_node": "node_b", "output_field": "", "target_key": "result_b"},
 ],
 },
 input_data={},
 workflow_context={},
 previous_outputs={
 "node_a": {"data": "value_a"},
 "node_b": {"data": "value_b"},
 },
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["result_a"] == {"data": "value_a"}
 assert result.output["result_b"] == {"data": "value_b"}
class TestVariableAggregateNodeOutputField:
 """Test 3 & 4: Output field extraction vs whole object."""
 @pytest.mark.asyncio
 async def test_output_field_extraction(self):
 """Test 3: output_field specified extracts that field."""
 from workflows.nodes.data.aggregate import VariableAggregateNode
 node = VariableAggregateNode
 context = ExecutionContext(
 execution_id="exec-002",
 node_id="node-002",
 node_config={
 "mappings": [
 {"source_node": "node_a", "output_field": "name", "target_key": "user_name"},
 ],
 },
 input_data={},
 workflow_context={},
 previous_outputs={
 "node_a": {"name": "Alice", "age": 30},
 },
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["user_name"] == "Alice"
 @pytest.mark.asyncio
 async def test_whole_object_when_output_field_empty(self):
 """Test 4: Empty output_field returns whole upstream output."""
 from workflows.nodes.data.aggregate import VariableAggregateNode
 node = VariableAggregateNode
 context = ExecutionContext(
 execution_id="exec-003",
 node_id="node-003",
 node_config={
 "mappings": [
 {"source_node": "node_a", "output_field": "", "target_key": "all_data"},
 ],
 },
 input_data={},
 workflow_context={},
 previous_outputs={
 "node_a": {"name": "Bob", "age": 25},
 },
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["all_data"] == {"name": "Bob", "age": 25}
class TestVariableAggregateNodeConflict:
 """Test 5: Later mapping overrides earlier on target_key conflict."""
 @pytest.mark.asyncio
 async def test_later_overrides_earlier(self):
 from workflows.nodes.data.aggregate import VariableAggregateNode
 node = VariableAggregateNode
 context = ExecutionContext(
 execution_id="exec-004",
 node_id="node-004",
 node_config={
 "mappings": [
 {"source_node": "node_a", "output_field": "", "target_key": "shared"},
 {"source_node": "node_b", "output_field": "", "target_key": "shared"},
 ],
 },
 input_data={},
 workflow_context={},
 previous_outputs={
 "node_a": {"value": "from_a"},
 "node_b": {"value": "from_b"},
 },
 )
 result = await node.execute(context)
 assert result.status == "completed"
 # Later mapping (node_b) should override earlier (node_a)
 assert result.output["shared"] == {"value": "from_b"}
class TestVariableAggregateNodeMissingSource:
 """Test 6: Missing source_node returns None without exception."""
 @pytest.mark.asyncio
 async def test_missing_source_returns_none(self):
 from workflows.nodes.data.aggregate import VariableAggregateNode
 node = VariableAggregateNode
 context = ExecutionContext(
 execution_id="exec-005",
 node_id="node-005",
 node_config={
 "mappings": [
 {"source_node": "missing_node", "output_field": "", "target_key": "missing"},
 ],
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["missing"] == {}
 @pytest.mark.asyncio
 async def test_empty_mappings(self):
 """Empty mappings returns empty output."""
 from workflows.nodes.data.aggregate import VariableAggregateNode
 node = VariableAggregateNode
 context = ExecutionContext(
 execution_id="exec-006",
 node_id="node-006",
 node_config={"mappings": },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output == {}
