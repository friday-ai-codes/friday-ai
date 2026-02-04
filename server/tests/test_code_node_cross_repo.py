"""Tests for CodeImplementNode cross-repo context support."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from workflows.nodes.ai.code import CodeImplementNode
from workflows.nodes.base import ExecutionContext
class TestCodeImplementNodeCrossRepoContext:
 """Test cross-repo context handling in CodeImplementNode."""
 def test_config_schema_has_cross_repo_context(self) -> None:
 """Verify cross_repo_context is in config_schema."""
 node = CodeImplementNode
 properties = node.config_schema["properties"]
 assert "cross_repo_context" in properties
 cross_repo_prop = properties["cross_repo_context"]
 assert cross_repo_prop["type"] == "string"
 assert cross_repo_prop["default"] == ""
 # Description should mention read-only
 assert "只读" in cross_repo_prop["description"]
 def test_cross_repo_context_description_mentions_api_consistency(self) -> None:
 """Verify description mentions interface/API consistency purpose."""
 node = CodeImplementNode
 description = node.config_schema["properties"]["cross_repo_context"]["description"]
 # Should mention interface consistency (接口一致性)
 assert "接口一致性" in description or "一致性" in description
 @pytest.mark.asyncio
 async def test_cross_repo_context_passed_to_environment(self) -> None:
 """Verify cross_repo_context is passed to container environment."""
 node = CodeImplementNode
 # Create mock context
 mock_context = MagicMock(spec=ExecutionContext)
 mock_context.execution_id = "test-exec-123"
 mock_context.node_id = "test-node-456"
 mock_context.workflow_context = {}
 mock_context.node_config = {
 "plan": "Implement API endpoint",
 "repository_path": "/path/to/repo",
 "branch_name": "feature/test",
 "cross_repo_context": "def api_handler: pass",
 "execution_mode": "auto",
 }
 mock_context.render_template = lambda x: x # Pass through
 # Mock the container executor
 mock_executor = AsyncMock
 mock_executor.start_execution = AsyncMock(return_value="container-id-789")
 with patch(
 "workflows.nodes.ai.code.get_container_executor",
 return_value=mock_executor,
 ):
 await node.execute(mock_context)
 # Verify start_execution was called
 mock_executor.start_execution.assert_called_once
 # Get the ExecutionRequest that was passed
 call_args = mock_executor.start_execution.call_args
 request = call_args[0][0]
 # Verify FRIDAY_TASK_CROSS_REPO_CONTEXT is in environment
 assert "FRIDAY_TASK_CROSS_REPO_CONTEXT" in request.environment
 assert request.environment["FRIDAY_TASK_CROSS_REPO_CONTEXT"] == "def api_handler: pass"
 @pytest.mark.asyncio
 async def test_empty_cross_repo_context_not_in_environment(self) -> None:
 """Verify empty cross_repo_context does not pollute environment."""
 node = CodeImplementNode
 # Create mock context with empty cross_repo_context
 mock_context = MagicMock(spec=ExecutionContext)
 mock_context.execution_id = "test-exec-123"
 mock_context.node_id = "test-node-456"
 mock_context.workflow_context = {}
 mock_context.node_config = {
 "plan": "Implement API endpoint",
 "repository_path": "/path/to/repo",
 "branch_name": "feature/test",
 "cross_repo_context": "", # Empty context
 "execution_mode": "auto",
 }
 mock_context.render_template = lambda x: x
 mock_executor = AsyncMock
 mock_executor.start_execution = AsyncMock(return_value="container-id-789")
 with patch(
 "workflows.nodes.ai.code.get_container_executor",
 return_value=mock_executor,
 ):
 await node.execute(mock_context)
 # Verify start_execution was called
 mock_executor.start_execution.assert_called_once
 # Get the ExecutionRequest
 call_args = mock_executor.start_execution.call_args
 request = call_args[0][0]
 # FRIDAY_TASK_CROSS_REPO_CONTEXT should NOT be in environment
 assert "FRIDAY_TASK_CROSS_REPO_CONTEXT" not in request.environment
