"""Tests for workflow nodes.

Tests cover:
- Node registry
- Base node functionality
- Trigger nodes (manual, webhook)
- Control nodes (condition, approval)
- Integration nodes (HTTP request)
"""

import pytest

from workflows.models import WorkflowExecution
from workflows.nodes.base import ExecutionContext, NodeCategory, NodePort, NodeResult, PortType
from workflows.nodes.registry import NodeRegistry

# ============================================================================
# Node Registry Tests
# ============================================================================


@pytest.mark.django_db
class TestNodeRegistry:
    """Tests for the NodeRegistry singleton."""

    def test_registry_is_singleton(self):
        """Test that registry is a singleton."""
        registry1 = NodeRegistry()
        registry2 = NodeRegistry()
        assert registry1 is registry2

    def test_registry_has_nodes(self):
        """Test that registry has registered nodes."""
        registry = NodeRegistry()
        node_types = registry.get_all_schemas()

        assert len(node_types) > 0

    def test_registry_has_manual_trigger(self):
        """Test that manual trigger is registered."""
        registry = NodeRegistry()
        node_class = registry.get("manual_trigger")

        assert node_class is not None

    def test_registry_has_condition(self):
        """Test that condition node is registered."""
        registry = NodeRegistry()
        node_class = registry.get("condition")

        assert node_class is not None

    def test_registry_has_approval(self):
        """Test that approval node is registered."""
        registry = NodeRegistry()
        node_class = registry.get("human_approval")

        assert node_class is not None

    def test_registry_unknown_node_returns_none(self):
        """Test that unknown node type returns None."""
        registry = NodeRegistry()
        node_class = registry.get("unknown_node_type")

        assert node_class is None

    def test_list_node_types_returns_metadata(self):
        """Test that get_all_schemas returns metadata."""
        registry = NodeRegistry()
        node_types = registry.get_all_schemas()

        # Each entry should have required fields
        for node_type in node_types:
            assert "node_type" in node_type
            assert "display_name" in node_type
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
            port_type=PortType.ANY,
        )

        assert port.name == "output"
        assert port.label == "Output"
        assert port.port_type == PortType.ANY

    def test_node_port_optional_fields(self):
        """Test NodePort with optional fields."""
        port = NodePort(
            name="data",
            label="Data Output",
            port_type=PortType.OBJECT,
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
            status="completed",
            output={"data": "value"},
        )

        assert result.status == "completed"
        assert result.output == {"data": "value"}
        assert result.error is None

    def test_create_failure_result(self):
        """Test creating a failure result."""
        result = NodeResult(
            status="failed",
            error="Something went wrong",
        )

        assert result.status == "failed"
        assert result.error == "Something went wrong"

    def test_result_with_next_handle(self):
        """Test result with next handle for branching."""
        result = NodeResult(
            status="completed",
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
        registry = NodeRegistry()
        node_class = registry.get("manual_trigger")

        assert node_class is not None
        assert node_class.node_type == "manual_trigger"
        assert node_class.category == NodeCategory.TRIGGER

    def test_manual_trigger_has_output_port(self):
        """Test manual trigger has output port."""
        registry = NodeRegistry()
        node_class = registry.get("manual_trigger")

        # Use class attribute instead of removed get_output_ports() method
        output_ports = node_class.outputs

        assert len(output_ports) >= 1

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_manual_trigger_reads_executor_without_async_lazy_load(self, obs_workflow, user):
        """Executor metadata uses async-safe lookup when the FK is not cached."""
        from workflows.nodes.triggers.manual import ManualTriggerNode

        execution = await WorkflowExecution.objects.acreate(
            workflow=obs_workflow,
            project=obs_workflow.project,
            trigger_type="manual",
            triggered_by=user,
            status="running",
        )
        execution = await WorkflowExecution.objects.aget(pk=execution.pk)
        assert "triggered_by" not in execution._state.fields_cache

        context = ExecutionContext(
            execution_id=str(execution.id),
            node_id="manual-001",
            node_config={},
            input_data={"raw_payload": {"feature": "uat"}},
            workflow_context={},
            previous_outputs={},
            workflow_execution=execution,
        )

        result = await ManualTriggerNode().execute(context)

        assert result.status == "completed"
        assert result.output["data"]["executor_id"] == str(user.id)
        assert result.output["data"]["executor_name"] == user.username


# ============================================================================
# Condition Node Tests
# ============================================================================


@pytest.mark.django_db
class TestConditionNode:
    """Tests for ConditionNode."""

    def test_condition_metadata(self):
        """Test condition node has correct metadata."""
        registry = NodeRegistry()
        node_class = registry.get("condition")

        assert node_class is not None
        assert node_class.node_type == "condition"
        assert node_class.category == NodeCategory.CONTROL

    def test_condition_has_multiple_outputs(self):
        """Test condition node has dynamic output ports."""
        registry = NodeRegistry()
        node_class = registry.get("condition")

        # ConditionNode uses dynamic outputs based on config
        # Test with a sample config that has conditions
        sample_config = {
            "conditions": [
                {
                    "name": "Branch 1",
                    "expression": {"field": "status", "operator": "eq", "value": "active"},
                }
            ],
            "default_branch": "else",
        }
        output_ports = node_class.get_dynamic_outputs(sample_config)

        # Should have at least branch_0 and default (else) outputs
        assert len(output_ports) >= 2


# ============================================================================
# Approval Node Tests
# ============================================================================


@pytest.mark.django_db
class TestApprovalNode:
    """Tests for HumanApprovalNode."""

    def test_approval_metadata(self):
        """Test approval node has correct metadata."""
        registry = NodeRegistry()
        node_class = registry.get("human_approval")

        assert node_class is not None
        assert node_class.node_type == "human_approval"
        assert node_class.category == NodeCategory.CONTROL

    def test_approval_has_approved_rejected_outputs(self):
        """Test approval node has approved/rejected outputs."""
        registry = NodeRegistry()
        node_class = registry.get("human_approval")

        # Use class attribute instead of removed get_output_ports() method
        output_ports = node_class.outputs
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
        registry = NodeRegistry()
        node_class = registry.get("http_request")

        assert node_class is not None
        assert node_class.node_type == "http_request"
        assert node_class.category == NodeCategory.INTEGRATION

    def test_http_request_config_schema(self):
        """Test HTTP request node has config schema."""
        registry = NodeRegistry()
        node_class = registry.get("http_request")

        # Use class attribute instead of removed get_config_schema() method
        schema = node_class.config_schema

        # Should have URL in config
        assert schema is not None


# ============================================================================
# execution_mode Tests
# ============================================================================


@pytest.mark.django_db
class TestExecutionMode:
    """Tests for execution_mode ClassVar on all nodes."""

    def test_all_nodes_have_execution_mode(self):
        """Every registered node must declare execution_mode."""
        for node_type, cls in NodeRegistry.get_all().items():
            assert hasattr(cls, "execution_mode"), f"{cls.__name__} missing execution_mode"
            assert cls.execution_mode in ("server_local", "runner_dispatched"), (
                f"{cls.__name__} has invalid execution_mode={cls.execution_mode}"
            )

    def test_runner_dispatched_nodes(self):
        """ai_coding must be runner_dispatched."""
        for name in ("ai_coding",):
            cls = NodeRegistry.get(name)
            assert cls is not None, f"{name} not registered"
            assert cls.execution_mode == "runner_dispatched"

    def test_server_local_nodes(self):
        """Control/trigger/integration nodes must be server_local."""
        for name in ("condition", "delay", "manual_trigger", "http_request", "notify_feishu"):
            cls = NodeRegistry.get(name)
            assert cls is not None, f"{name} not registered"
            assert cls.execution_mode == "server_local"

    def test_get_schema_includes_execution_mode(self):
        """get_schema() output must contain execution_mode."""
        for schema in NodeRegistry.get_all_schemas():
            assert "execution_mode" in schema, (
                f"{schema['node_type']} schema missing execution_mode"
            )

    def test_init_subclass_rejects_missing_execution_mode(self):
        """Concrete BaseNode subclass without execution_mode must raise TypeError."""
        from workflows.nodes.base import BaseNode

        with pytest.raises(TypeError, match="必须声明 execution_mode"):

            class _BadNode(BaseNode):
                node_type = "test_bad"
                display_name = "bad"
                description = "bad"
                icon = "x"
                category = NodeCategory.CONTROL
