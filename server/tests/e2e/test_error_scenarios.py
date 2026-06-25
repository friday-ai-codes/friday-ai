"""E2E tests for error scenarios and error message clarity.

These tests verify that when things fail, users get clear, actionable error
messages that help them understand and resolve the issue.

Note: These tests focus on node-level error handling since the full E2E
webhook flow requires complex infrastructure setup. The key requirement
is that error messages are clear and actionable.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from workflows.nodes.ai.coding_dispatcher import AICodingDispatcherNode
from workflows.nodes.base import ExecutionContext, NodeResult

# ============================================================================
# Helper Functions
# ============================================================================


def create_mock_context(
    node_config: dict[str, Any] | None = None,
    global_params: dict[str, Any] | None = None,
    node_outputs: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock ExecutionContext for node testing."""
    context = MagicMock(spec=ExecutionContext)
    context.node_config = node_config or {}

    # Mock global params
    _global_params = global_params or {}
    context.get_global_param = MagicMock(
        side_effect=lambda key, default=None: _global_params.get(key, default)
    )

    # Mock node outputs
    _node_outputs = node_outputs or {}
    context.get_node_output = MagicMock(
        side_effect=lambda key: _node_outputs.get(key)
    )

    # Mock workflow execution with proper project structure
    # IMPORTANT: claude_api_key_encrypted must be None (not MagicMock) to avoid
    # "token must be bytes or str" error in decrypt_value()
    mock_project = MagicMock()
    mock_project.claude_api_key_encrypted = None  # Prevent decrypt_value from failing
    mock_project.claude_base_url = None  # Fall back to system config
    mock_project.anthropic_api_key = "test-api-key"  # Legacy field

    context.workflow_execution = MagicMock()
    context.workflow_execution.workflow = MagicMock()
    context.workflow_execution.workflow.space = mock_project

    return context


# ============================================================================
# Test Class: Schema Validation Errors
# ============================================================================


class TestSchemaValidationErrors:
    """Tests for schema validation error messages."""

    @pytest.mark.asyncio
    async def test_empty_execution_plan_shows_clear_message(self) -> None:
        """Empty execution_plan in dispatcher produces clear error about missing tasks."""
        node = AICodingDispatcherNode()

        # Create context with empty execution_plan but valid plan structure
        empty_plan = {
            "title": "Empty Plan",
            "summary": "This plan has no tasks",
            "execution_plan": [],  # Empty - should fail
            "total_tasks": 0,
        }

        context = create_mock_context(
            node_config={"merge_same_branch": True},
            node_outputs={"plan": {"plan": empty_plan}},
            global_params={"technical_plan": empty_plan},
        )

        result = await node.execute(context)

        assert result.status == "failed"
        assert result.error is not None

        error_lower = result.error.lower()
        # Should mention empty or execution_plan or validation
        assert any(
            keyword in error_lower
            for keyword in ["empty", "空", "execution_plan", "至少", "任务", "缺少", "验证"]
        ), f"Error should mention empty execution_plan: {result.error}"


# ============================================================================
# Test Class: Resource Errors
# ============================================================================


class TestResourceErrors:
    """Tests for resource-related error messages (missing repos, requirements)."""

    @pytest.mark.asyncio
    async def test_missing_plan_input_shows_clear_message(self) -> None:
        """Missing technical plan input produces clear error message."""
        node = AICodingDispatcherNode()
        context = create_mock_context(
            node_config={"merge_same_branch": True},
            node_outputs={},  # No plan output
            global_params={},  # No plan in global params either
        )

        result = await node.execute(context)

        assert result.status == "failed"
        assert result.error is not None

        error_lower = result.error.lower()
        # Should mention technical plan or input
        assert any(
            keyword in error_lower
            for keyword in ["plan", "方案", "技术", "input", "输入", "缺少"]
        ), f"Error should mention missing plan: {result.error}"


# ============================================================================
# Test Class: Workflow Recovery
# ============================================================================


class TestWorkflowRecovery:
    """Tests for workflow failure state management."""

    @pytest.mark.asyncio
    async def test_dispatcher_failed_node_has_descriptive_error(self) -> None:
        """Failed dispatcher node has descriptive error message, not just 'Error'."""
        node = AICodingDispatcherNode()
        context = create_mock_context(
            node_config={"merge_same_branch": True},
            node_outputs={},  # No plan output - will cause failure
            global_params={},
        )

        result = await node.execute(context)

        assert result.status == "failed"
        assert result.error is not None
        # Error message should be descriptive (not just "Error" or empty)
        assert len(result.error) > 10, (
            f"Error message should be descriptive: {result.error}"
        )

    @pytest.mark.asyncio
    async def test_node_result_has_proper_failure_structure(self) -> None:
        """Failed NodeResult has all required fields for error tracking."""
        node = AICodingDispatcherNode()
        context = create_mock_context(
            node_config={"merge_same_branch": True},
            node_outputs={},  # No plan output - will cause failure
            global_params={},
        )

        result = await node.execute(context)

        # Verify NodeResult structure
        assert isinstance(result, NodeResult)
        assert result.status == "failed"
        assert result.error is not None
        assert result.next_handle == "error"
        # Output may or may not be set on failure, but error must be set
        assert len(result.error) > 0
