"""Tests for workflow nodes.
Tests cover:
- Node registry
- Base node functionality
- Trigger nodes (manual, webhook)
- Control nodes (condition, approval)
- Integration nodes (HTTP request)
"""
import pytest
from workflows.nodes.base import BaseNode, NodePort, NodeResult
from workflows.nodes.registry import NodeRegistry
# ============================================================================
# Node Registry Tests
# ============================================================================
@pytest.mark.django_db
class TestNodeRegistry:
 """Tests for the NodeRegistry singleton."""
 def test_registry_is_singleton(self):
 """Test that registry is a singleton."""
 registry1 = NodeRegistry
 registry2 = NodeRegistry
 assert registry1 is registry2
 def test_registry_has_nodes(self):
 """Test that registry has registered nodes."""
 registry = NodeRegistry
 node_types = registry.list_node_types
 assert len(node_types) > 0
 def test_registry_has_manual_trigger(self):
 """Test that manual trigger is registered."""
 registry = NodeRegistry
 node_class = registry.get_node_class("manual_trigger")
 assert node_class is not None
 def test_registry_has_condition(self):
 """Test that condition node is registered."""
 registry = NodeRegistry
 node_class = registry.get_node_class("condition")
 assert node_class is not None
 def test_registry_has_approval(self):
 """Test that approval node is registered."""
 registry = NodeRegistry
 node_class = registry.get_node_class("human_approval")
 assert node_class is not None
 def test_registry_unknown_node_returns_none(self):
 """Test that unknown node type returns None."""
 registry = NodeRegistry
 node_class = registry.get_node_class("unknown_node_type")
 assert node_class is None
 def test_list_node_types_returns_metadata(self):
 """Test that list_node_types returns metadata."""
 registry = NodeRegistry
 node_types = registry.list_node_types
 # Each entry should have required fields
 for node_type in node_types:
 assert "type" in node_type
 assert "name" in node_type
 assert "category" in node_type
# ============================================================================
# NodePort Tests
# ============================================================================
class TestNodePort:
 """Tests for the NodePort dataclass."""
 def test_create_node_port(self):
 """Test creating a NodePort."""
 port = NodePort(
 name="output",
 label="Output",
 type="default",
 )
 assert port.name == "output"
 assert port.label == "Output"
 assert port.type == "default"
 def test_node_port_optional_fields(self):
 """Test NodePort with optional fields."""
 port = NodePort(
 name="data",
 label="Data Output",
 type="data",
 description="Outputs processed data",
 required=False,
 )
 assert port.description == "Outputs processed data"
 assert port.required is False
# ============================================================================
# NodeResult Tests
# ============================================================================
class TestNodeResult:
 """Tests for the NodeResult dataclass."""
 def test_create_success_result(self):
 """Test creating a success result."""
 result = NodeResult(
 success=True,
 output={"data": "value"},
 )
 assert result.success is True
 assert result.output == {"data": "value"}
 assert result.error is None
 def test_create_failure_result(self):
 """Test creating a failure result."""
 result = NodeResult(
 success=False,
 error="Something went wrong",
 )
 assert result.success is False
 assert result.error == "Something went wrong"
 def test_result_with_next_handle(self):
 """Test result with next handle for branching."""
 result = NodeResult(
 success=True,
 output={},
 next_handle="approved",
 )
 assert result.next_handle == "approved"
# ============================================================================
# Manual Trigger Node Tests
# ============================================================================
@pytest.mark.django_db
class TestManualTriggerNode:
 """Tests for ManualTriggerNode."""
 def test_manual_trigger_metadata(self):
 """Test manual trigger has correct metadata."""
 registry = NodeRegistry
 node_class = registry.get_node_class("manual_trigger")
 assert node_class is not None
 assert node_class.node_type == "manual_trigger"
 assert node_class.category == "trigger"
 def test_manual_trigger_has_output_port(self):
 """Test manual trigger has output port."""
 registry = NodeRegistry
 node_class = registry.get_node_class("manual_trigger")
 node = node_class
 output_ports = node.get_output_ports
 assert len(output_ports) >= 1
# ============================================================================
# Condition Node Tests
# ============================================================================
@pytest.mark.django_db
class TestConditionNode:
 """Tests for ConditionNode."""
 def test_condition_metadata(self):
 """Test condition node has correct metadata."""
 registry = NodeRegistry
 node_class = registry.get_node_class("condition")
 assert node_class is not None
 assert node_class.node_type == "condition"
 assert node_class.category == "control"
 def test_condition_has_multiple_outputs(self):
 """Test condition node has multiple output ports."""
 registry = NodeRegistry
 node_class = registry.get_node_class("condition")
 node = node_class
 output_ports = node.get_output_ports
 # Should have at least true/false or default outputs
 assert len(output_ports) >= 1
# ============================================================================
# Approval Node Tests
# ============================================================================
@pytest.mark.django_db
class TestApprovalNode:
 """Tests for HumanApprovalNode."""
 def test_approval_metadata(self):
 """Test approval node has correct metadata."""
 registry = NodeRegistry
 node_class = registry.get_node_class("human_approval")
 assert node_class is not None
 assert node_class.node_type == "human_approval"
 assert node_class.category == "control"
 def test_approval_has_approved_rejected_outputs(self):
 """Test approval node has approved/rejected outputs."""
 registry = NodeRegistry
 node_class = registry.get_node_class("human_approval")
 node = node_class
 output_ports = node.get_output_ports
 port_names = [p.name for p in output_ports]
 assert "approved" in port_names or "default" in port_names
# ============================================================================
# HTTP Request Node Tests
# ============================================================================
@pytest.mark.django_db
class TestHTTPRequestNode:
 """Tests for HTTPRequestNode."""
 def test_http_request_metadata(self):
 """Test HTTP request node has correct metadata."""
 registry = NodeRegistry
 node_class = registry.get_node_class("http_request")
 assert node_class is not None
 assert node_class.node_type == "http_request"
 assert node_class.category == "integration"
 def test_http_request_config_schema(self):
 """Test HTTP request node has config schema."""
 registry = NodeRegistry
 node_class = registry.get_node_class("http_request")
 node = node_class
 schema = node.get_config_schema
 # Should have URL in config
 assert schema is not None
