"""AIPlanGenerationNode unit tests.
Tests the AIPlanGenerationNode's independent execution behavior,
including happy path, error handling, and output mapping.
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.result import AgentResult
from tests.e2e.fixtures.technical_plans import VALID_TECHNICAL_PLAN
from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
from workflows.nodes.base import ExecutionContext, NodeResult
def _make_context(
 *,
 user_prompt: str = "实现用户认证模块",
 system_prompt: str = "",
 input_data: dict[str, Any] | None = None,
 extra_config: dict[str, Any] | None = None,
) -> ExecutionContext:
 """Build a minimal ExecutionContext for AIPlanGenerationNode tests.
 Constructs the mock workflow_execution -> workflow -> project chain
 required by AIAgentBaseNode.execute.
 """
 config: dict[str, Any] = {
 "user_prompt": user_prompt,
 "model": "claude-sonnet-4-20250514",
 "chat_id": "",
 }
 if system_prompt:
 config["system_prompt"] = system_prompt
 if extra_config:
 config.update(extra_config)
 # Build project -> workflow -> workflow_execution mock chain
 mock_project = MagicMock
 # Phase Task 6: Project.id 是 UUIDField，必须用 UUID 字符串（render_prompt 会查 DB）
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_project.feishu_doc_folder_token = "folder_token_123"
 mock_workflow = MagicMock
 mock_workflow.project = mock_project
 mock_execution = MagicMock
 mock_execution.workflow = mock_workflow
 mock_execution.triggered_by = MagicMock(id=1)
 ctx = ExecutionContext(
 execution_id="00000000-0000-0000-0000-000000000001",
 node_id="00000000-0000-0000-0000-000000000011",
 node_config=config,
 input_data=input_data or {},
 workflow_context={},
 previous_outputs={},
 workflow_execution=mock_execution,
 )
 return ctx
def _make_agent_result(
 *,
 plan: dict[str, Any] | None = None,
 status: str = "completed",
 final_answer: str = "方案已生成",
 output: list[Any] | None = None,
 metadata: dict[str, Any] | None = None,
) -> AgentResult:
 """Build an AgentResult with optional plan in metadata."""
 meta = metadata or {}
 if plan is not None and "plan" not in meta:
 meta["plan"] = plan
 return AgentResult(
 output=output or,
 status=status,
 final_answer=final_answer,
 usage={"input_tokens": 1000, "output_tokens": 500},
 metadata=meta,
 )
@pytest.mark.django_db(transaction=True)
class TestAIPlanGenerationNode:
 """Unit tests for AIPlanGenerationNode independent execution."""
 @pytest.mark.asyncio
 @patch("workflows.nodes.ai.base_agent.AgentSession.objects")
 @patch("workflows.nodes.ai.base_agent.SDKAgentRunner")
 @patch("services.claude_config.get_claude_config")
 @patch("workflows.nodes.ai.base_agent.AIAgentBaseNode._resolve_api_key_and_model")
 @patch("workflows.nodes.ai.base_agent.AIAgentBaseNode._get_user")
 @patch("workflows.nodes.ai.base_agent.AIAgentBaseNode._get_project")
 async def test_execute_happy_path(
 self,
 mock_get_project: MagicMock,
 mock_get_user: MagicMock,
 mock_resolve: MagicMock,
 mock_get_config: MagicMock,
 mock_runner_cls: MagicMock,
 mock_session_objects: MagicMock,
 ) -> None:
 """SDKAgentRunner returns a valid plan in metadata -> completed with plan output."""
 # Arrange
 mock_project = MagicMock
 # Phase Task 6: Project.id 是 UUIDField，必须用 UUID 字符串（render_prompt 会查 DB）
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_project.feishu_doc_folder_token = "folder_token_123"
 mock_get_project.return_value = mock_project
 mock_user = MagicMock(id=1)
 mock_get_user.return_value = mock_user
 mock_resolve.return_value = ("sk-test", "claude-sonnet-4-20250514")
 mock_config_obj = MagicMock
 mock_config_obj.api_key = "sk-test"
 mock_config_obj.base_url = "https://api.anthropic.com"
 mock_get_config.return_value = mock_config_obj
 mock_session_objects.aupdate_or_create = AsyncMock(
 return_value=(MagicMock, True)
 )
 agent_result = _make_agent_result(plan=VALID_TECHNICAL_PLAN)
 # Mock SDKAgentRunner: stream returns empty async generator, result returns AgentResult
 mock_runner_instance = MagicMock
 async def _empty_stream(prompt):
 return
 yield # noqa: RET504
 mock_runner_instance.stream = MagicMock(side_effect=_empty_stream)
 mock_runner_instance.result = agent_result
 mock_runner_cls.return_value = mock_runner_instance
 ctx = _make_context
 node = AIPlanGenerationNode
 # Act
 result: NodeResult = await node.execute(ctx)
 # Assert
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert result.output["plan"] == VALID_TECHNICAL_PLAN
 assert result.output["final_answer"] == "方案已生成"
 assert "usage" in result.output
 @pytest.mark.asyncio
 @patch("workflows.nodes.ai.base_agent.AgentSession.objects")
 @patch("workflows.nodes.ai.base_agent.SDKAgentRunner")
 @patch("services.claude_config.get_claude_config")
 @patch("workflows.nodes.ai.base_agent.AIAgentBaseNode._resolve_api_key_and_model")
 @patch("workflows.nodes.ai.base_agent.AIAgentBaseNode._get_user")
 @patch("workflows.nodes.ai.base_agent.AIAgentBaseNode._get_project")
 async def test_execute_plan_from_verify_tool(
 self,
 mock_get_project: MagicMock,
 mock_get_user: MagicMock,
 mock_resolve: MagicMock,
 mock_get_config: MagicMock,
 mock_runner_cls: MagicMock,
 mock_session_objects: MagicMock,
 ) -> None:
 """AgentResult.output contains verify_plan tool call -> map_output extracts plan."""
 mock_project = MagicMock
 mock_project.id = 1
 mock_project.feishu_doc_folder_token = "folder_token_123"
 mock_get_project.return_value = mock_project
 mock_user = MagicMock(id=1)
 mock_get_user.return_value = mock_user
 mock_resolve.return_value = ("sk-test", "claude-sonnet-4-20250514")
 mock_config_obj = MagicMock
 mock_config_obj.api_key = "sk-test"
 mock_config_obj.base_url = "https://api.anthropic.com"
 mock_get_config.return_value = mock_config_obj
 mock_session_objects.aupdate_or_create = AsyncMock(
 return_value=(MagicMock, True)
 )
 # Plan is in tool call history, NOT in metadata
 tool_output = [
 {"tool": "search_code", "input": {"query": "auth"}, "output": "..."},
 {
 "tool": "verify_plan",
 "input": {"plan": VALID_TECHNICAL_PLAN},
 "output": {"valid": True},
 },
 ]
 agent_result = AgentResult(
 output=tool_output,
 status="completed",
 final_answer="方案已验证通过",
 usage={"input_tokens": 2000, "output_tokens": 800},
 metadata={}, # No plan in metadata
 )
 mock_runner_instance = MagicMock
 async def _empty_stream(prompt):
 return
 yield # noqa: RET504
 mock_runner_instance.stream = MagicMock(side_effect=_empty_stream)
 mock_runner_instance.result = agent_result
 mock_runner_cls.return_value = mock_runner_instance
 ctx = _make_context
 node = AIPlanGenerationNode
 result: NodeResult = await node.execute(ctx)
 assert result.status == "completed"
 assert result.output["plan"] == VALID_TECHNICAL_PLAN
 @pytest.mark.asyncio
 async def test_execute_empty_user_prompt(self) -> None:
 """Empty user_prompt in config -> returns failed status."""
 ctx = _make_context(user_prompt="")
 node = AIPlanGenerationNode
 result: NodeResult = await node.execute(ctx)
 assert result.status == "failed"
 assert result.error is not None
 assert "User Prompt" in result.error
 def test_get_system_prompt_includes_schema(self) -> None:
 """get_system_prompt returns string containing JSON Schema."""
 ctx = _make_context
 node = AIPlanGenerationNode
 prompt = node.get_system_prompt(ctx)
 assert isinstance(prompt, str)
 assert "JSON Schema" in prompt or "json" in prompt.lower
 # Should contain schema fields
 assert "title" in prompt
 assert "execution_plan" in prompt
 assert "verify_plan" in prompt
 def test_get_enabled_tools_includes_defaults(self) -> None:
 """get_enabled_tools returns default tool set for plan generation."""
 ctx = _make_context
 node = AIPlanGenerationNode
 tools = node.get_enabled_tools(ctx)
 assert tools is not None
 assert "verify_plan" in tools
 assert "send_plan_card" in tools
 assert "create_feishu_document" in tools
 assert "search_code" in tools
 def test_map_output_no_plan(self) -> None:
 """AgentResult with no extractable plan -> output.plan is None with error."""
 node = AIPlanGenerationNode
 result = AgentResult(
 output=,
 status="completed",
 final_answer="I could not generate a plan.",
 usage={"input_tokens": 500, "output_tokens": 100},
 metadata={},
 )
 output = node.map_output(result)
 assert output["plan"] is None
 assert "error" in output
 assert output["final_answer"] == "I could not generate a plan."
