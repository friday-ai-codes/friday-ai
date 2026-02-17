"""E2E tests for error scenarios and error message clarity.
These tests verify that when things fail, users get clear, actionable error
messages that help them understand and resolve the issue.
Note: These tests focus on node-level error handling since the full E2E
webhook flow requires complex infrastructure setup. The key requirement
is that error messages are clear and actionable.
"""
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from feishu.client import FeishuAPIError
from workflows.nodes.ai.coding_dispatcher import AICodingDispatcherNode
from workflows.nodes.ai.technical_plan import TechnicalPlanNode
from workflows.nodes.base import ExecutionContext, NodeResult
# ============================================================================
# Helper Functions
# ============================================================================
@dataclass
class MockClaudeConfig:
 """Mock Claude configuration for testing."""
 api_key: str = "test-api-key"
 base_url: str = "https://api.anthropic.com"
 model: str = "claude-3-5-sonnet-20241022"
 source: str = "system"
@contextmanager
def mock_claude_config(
 api_key: str = "test-api-key",
 base_url: str = "https://api.anthropic.com",
) -> Generator[MagicMock, None, None]:
 """Context manager to mock get_claude_config to avoid database access.
 This is required because TechnicalPlanNode._call_llm calls get_claude_config
 which tries to access the database for system settings.
 """
 mock_config = MockClaudeConfig(api_key=api_key, base_url=base_url)
 with patch(
 "services.claude_config.get_claude_config",
 return_value=mock_config,
 ) as mock:
 yield mock
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
 # "token must be bytes or str" error in decrypt_value
 mock_project = MagicMock
 mock_project.claude_api_key_encrypted = None # Prevent decrypt_value from failing
 mock_project.claude_base_url = None # Fall back to system config
 mock_project.anthropic_api_key = "test-api-key" # Legacy field
 context.workflow_execution = MagicMock
 context.workflow_execution.workflow = MagicMock
 context.workflow_execution.workflow.project = mock_project
 return context
# ============================================================================
# Test Class: LLM Error Scenarios
# ============================================================================
class TestLLMErrorScenarios:
 """Tests for LLM API error handling and error message clarity."""
 @pytest.mark.asyncio
 async def test_llm_api_500_error_shows_clear_message(self):
 """LLM API 500 error produces clear error message mentioning API failure."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={"model": "claude-3-5-sonnet-20241022"},
 global_params={
 "work_item_name": "Test Feature",
 "description": "Implement a new feature",
 "project_key": "test-project",
 },
 )
 # Mock LLM to return 500 error
 mock_response = MagicMock
 mock_response.status_code = 500
 mock_response.text = "Internal Server Error"
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention LLM or API error
 assert any(
 keyword in error_lower
 for keyword in ["llm", "api", "500", "错误"]
 ), f"Error message should mention LLM/API failure: {result.error}"
 @pytest.mark.asyncio
 async def test_llm_api_timeout_shows_clear_message(self):
 """LLM API timeout produces clear error message mentioning timeout."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={"model": "claude-3-5-sonnet-20241022"},
 global_params={
 "work_item_name": "Test Feature",
 "description": "This should timeout",
 "project_key": "test-project",
 },
 )
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(
 side_effect=httpx.TimeoutException("Connection timed out")
 )
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention timeout
 assert any(
 keyword in error_lower
 for keyword in ["timeout", "timed out", "超时"]
 ), f"Error message should mention timeout: {result.error}"
 @pytest.mark.asyncio
 async def test_llm_invalid_json_response_shows_clear_message(self):
 """LLM returning invalid JSON produces clear parse error message."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={"model": "claude-3-5-sonnet-20241022"},
 global_params={
 "work_item_name": "Test Feature",
 "description": "Should fail on JSON parse",
 "project_key": "test-project",
 },
 )
 # Mock LLM to return invalid JSON
 mock_response = MagicMock
 mock_response.status_code = 200
 mock_response.json.return_value = {
 "id": "msg_test",
 "type": "message",
 "role": "assistant",
 "content": [
 {
 "type": "text",
 "text": "This is not valid JSON { broken syntax",
 }
 ],
 }
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention parse/JSON error
 assert any(
 keyword in error_lower
 for keyword in ["parse", "json", "解析", "格式", "llm"]
 ), f"Error message should mention JSON/parse error: {result.error}"
# ============================================================================
# Test Class: Schema Validation Errors
# ============================================================================
class TestSchemaValidationErrors:
 """Tests for technical plan schema validation error messages."""
 @pytest.mark.asyncio
 async def test_invalid_technical_plan_schema_shows_clear_message(self):
 """Missing required fields in technical plan produces clear validation error."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={"model": "claude-3-5-sonnet-20241022"},
 global_params={
 "work_item_name": "Test Feature",
 "description": "Should fail schema validation",
 "project_key": "test-project",
 },
 )
 # Mock LLM to return plan missing required fields (no execution_plan)
 invalid_plan = {
 "title": "Incomplete Plan",
 "summary": "This plan is missing execution_plan",
 # Missing: execution_plan (required)
 }
 mock_response = MagicMock
 mock_response.status_code = 200
 mock_response.json.return_value = {
 "id": "msg_test",
 "type": "message",
 "content": [{"type": "text", "text": json.dumps(invalid_plan)}],
 }
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention validation or schema or field name
 assert any(
 keyword in error_lower
 for keyword in [
 "validation",
 "schema",
 "验证",
 "execution_plan",
 "required",
 "必填",
 ]
 ), f"Error should mention validation/schema: {result.error}"
 @pytest.mark.asyncio
 async def test_empty_execution_plan_shows_clear_message(self):
 """Empty execution_plan in dispatcher produces clear error about missing tasks."""
 node = AICodingDispatcherNode
 # Create context with empty execution_plan but valid plan structure
 empty_plan = {
 "title": "Empty Plan",
 "summary": "This plan has no tasks",
 "execution_plan":, # Empty - should fail
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
 error_lower = result.error.lower
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
 async def test_missing_requirement_info_shows_clear_message(self):
 """Empty work item description produces clear error message."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={"model": "claude-3-5-sonnet-20241022"},
 global_params={
 "work_item_name": "", # Empty name
 "description": "", # Empty description
 "project_key": "test-project",
 },
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention requirement or description or work_item_name
 assert any(
 keyword in error_lower
 for keyword in [
 "requirement",
 "description",
 "work_item_name",
 "需求",
 "描述",
 "缺少",
 ]
 ), f"Error should mention missing requirement info: {result.error}"
 @pytest.mark.asyncio
 async def test_missing_plan_input_shows_clear_message(self):
 """Missing technical plan input produces clear error message."""
 node = AICodingDispatcherNode
 context = create_mock_context(
 node_config={"merge_same_branch": True},
 node_outputs={}, # No plan output
 global_params={}, # No plan in global params either
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention technical plan or input
 assert any(
 keyword in error_lower
 for keyword in ["plan", "方案", "技术", "input", "输入", "缺少"]
 ), f"Error should mention missing plan: {result.error}"
# ============================================================================
# Test Class: Feishu API Errors
# ============================================================================
class TestFeishuAPIErrors:
 """Tests for Feishu API error handling and error messages."""
 @pytest.mark.asyncio
 async def test_feishu_writeback_failure_shows_clear_message(self):
 """Feishu field update failure produces clear error message."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={
 "model": "claude-3-5-sonnet-20241022",
 "feishu_field_key": "technical_plan",
 "auto_transition_status": False,
 },
 global_params={
 "work_item_name": "Test Feature",
 "description": "Should fail on Feishu writeback",
 "project_key": "test-project",
 "work_item_id": 12345,
 "work_item_type": "story",
 },
 )
 # Create valid plan response
 valid_plan = {
 "title": "Test Plan",
 "summary": "Test summary",
 "execution_plan": [
 {
 "id": "task-001",
 "name": "Task 1",
 "repository_id": "repo-001",
 "repository_name": "test-repo",
 "branch_strategy": "feature",
 "coding_instruction": "Do something",
 "files":,
 "dependencies":,
 }
 ],
 }
 mock_llm_response = MagicMock
 mock_llm_response.status_code = 200
 mock_llm_response.json.return_value = {
 "id": "msg_test",
 "type": "message",
 "content": [{"type": "text", "text": json.dumps(valid_plan)}],
 }
 # Mock feishu client to fail on update_field
 mock_feishu = MagicMock
 mock_feishu.update_field = AsyncMock(
 side_effect=FeishuAPIError("更新字段失败: 字段不存在")
 )
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_llm_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 with patch(
 "workflows.nodes.ai.technical_plan.create_feishu_client_for_project",
 return_value=mock_feishu,
 ):
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 error_lower = result.error.lower
 # Should mention Feishu or writeback or field update
 assert any(
 keyword in error_lower
 for keyword in ["feishu", "飞书", "回填", "field", "字段"]
 ), f"Error should mention Feishu/writeback: {result.error}"
 @pytest.mark.asyncio
 async def test_feishu_status_transition_failure_is_warning_not_failure(self):
 """Feishu status transition failure is a warning, node still succeeds."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={
 "model": "claude-3-5-sonnet-20241022",
 "feishu_field_key": "technical_plan",
 "auto_transition_status": True,
 "target_status": "待审核",
 },
 global_params={
 "work_item_name": "Test Feature",
 "description": "Status transition should fail but node continues",
 "project_key": "test-project",
 "work_item_id": 12345,
 "work_item_type": "story",
 },
 )
 # Create valid plan response
 valid_plan = {
 "title": "Test Plan",
 "summary": "Test summary",
 "execution_plan": [
 {
 "id": "task-001",
 "name": "Task 1",
 "repository_id": "repo-001",
 "repository_name": "test-repo",
 "branch_strategy": "feature",
 "coding_instruction": "Do something",
 "files":,
 "dependencies":,
 }
 ],
 }
 mock_llm_response = MagicMock
 mock_llm_response.status_code = 200
 mock_llm_response.json.return_value = {
 "id": "msg_test",
 "type": "message",
 "content": [{"type": "text", "text": json.dumps(valid_plan)}],
 }
 # Mock feishu client where update_field succeeds but transition_status fails
 mock_feishu = MagicMock
 mock_feishu.update_field = AsyncMock(return_value=True)
 mock_feishu.transition_status = AsyncMock(
 side_effect=Exception("状态流转失败: 无可用流转")
 )
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_llm_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 with patch(
 "workflows.nodes.ai.technical_plan.create_feishu_client_for_project",
 return_value=mock_feishu,
 ):
 result = await node.execute(context)
 # Node should still complete successfully despite transition failure
 assert result.status == "completed", (
 f"Node should complete despite transition failure: {result.error}"
 )
 # Output should indicate transition was not successful
 assert result.output is not None
 assert result.output.get("status_transition") is False
# ============================================================================
# Test Class: Workflow Recovery
# ============================================================================
class TestWorkflowRecovery:
 """Tests for workflow failure state management."""
 @pytest.mark.asyncio
 async def test_failed_node_has_descriptive_error(self):
 """Failed node has descriptive error message, not just 'Error'."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={"model": "claude-3-5-sonnet-20241022"},
 global_params={
 "work_item_name": "Test Feature",
 "description": "This should fail with detailed error",
 "project_key": "test-project",
 },
 )
 # Mock LLM to return 500 error
 mock_response = MagicMock
 mock_response.status_code = 500
 mock_response.text = "Internal Server Error"
 with mock_claude_config:
 with patch("httpx.AsyncClient") as mock_client_class:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_class.return_value = mock_client
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.error is not None
 # Error message should be descriptive (not just "Error" or empty)
 assert len(result.error) > 10, (
 f"Error message should be descriptive: {result.error}"
 )
 # Should have next_handle set to error
 assert result.next_handle == "error"
 @pytest.mark.asyncio
 async def test_node_result_has_proper_failure_structure(self):
 """Failed NodeResult has all required fields for error tracking."""
 node = TechnicalPlanNode
 context = create_mock_context(
 node_config={},
 global_params={
 "work_item_name": "",
 "description": "",
 },
 )
 result = await node.execute(context)
 # Verify NodeResult structure
 assert isinstance(result, NodeResult)
 assert result.status == "failed"
 assert result.error is not None
 assert result.next_handle == "error"
 # Output may or may not be set on failure, but error must be set
 assert len(result.error) > 0
