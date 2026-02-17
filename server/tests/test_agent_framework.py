"""Integration tests for Agent framework."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from agents.core import AgentLoop, AgentConfig, AgentContext, AgentResult
from agents.llm import LLMResponse, ToolCall
from agents.tools import tool, ToolResult, ToolRegistry
# Test tool
@tool(
 name="echo",
 description="Echo the input message",
 category="GENERAL",
 parameters={
 "type": "object",
 "properties": {"message": {"type": "string"}},
 "required": ["message"],
 },
)
async def echo_tool(message: str) -> ToolResult:
 return ToolResult(success=True, output=f"Echo: {message}")
@pytest.mark.asyncio
async def test_tool_registration:
 """Test that @tool decorator registers tools."""
 tools = ToolRegistry.get_all_tools
 tool_names = [t.name for t in tools]
 assert "echo" in tool_names
@pytest.mark.asyncio
async def test_tool_schema_generation:
 """Test that tool schemas are generated correctly."""
 schemas = ToolRegistry.get_tool_schemas(["echo"])
 assert len(schemas) == 1
 assert schemas[0]["name"] == "echo"
 assert "input_schema" in schemas[0]
@pytest.mark.asyncio
async def test_tool_validation:
 """Test tool argument validation."""
 valid, err = ToolRegistry.validate_tool_arguments("echo", {"message": "hello"})
 assert valid is True
 valid, err = ToolRegistry.validate_tool_arguments("echo", {})
 assert valid is False
 assert "message" in err.lower
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_agent_loop_completion:
 """Test agent loop completes when LLM returns no tool calls."""
 # Mock provider that returns final answer immediately
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(return_value=LLMResponse(
 content="I'm done!",
 raw_content=[{"type": "text", "text": "I'm done!"}],
 tool_calls=,
 usage={"input_tokens": 10, "output_tokens": 5},
 stop_reason="end_turn",
 ))
 mock_provider.get_tool_schema = MagicMock(return_value=)
 config = AgentConfig(max_iterations=5)
 context = AgentContext(session_id="test-1", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider)
 # Mock state manager to avoid DB
 loop.state_manager.save_state = AsyncMock
 result = await loop.run("Hello")
 assert result.status == "completed"
 assert result.final_answer == "I'm done!"
 assert result.usage["input_tokens"] == 10
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_agent_loop_max_iterations:
 """Test agent loop stops at max iterations."""
 # Mock provider that always returns tool calls
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(return_value=LLMResponse(
 content="",
 raw_content=[{"type": "tool_use", "id": "123", "name": "echo", "input": {"message": "test"}}],
 tool_calls=[ToolCall(id="123", name="echo", arguments={"message": "test"})],
 usage={"input_tokens": 10, "output_tokens": 5},
 stop_reason="tool_use",
 ))
 mock_provider.get_tool_schema = MagicMock(return_value=)
 config = AgentConfig(max_iterations=2)
 context = AgentContext(session_id="test-2", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider)
 # Mock state manager
 loop.state_manager.save_state = AsyncMock
 loop.state_manager.log_tool_call = AsyncMock
 result = await loop.run("Loop forever")
 assert result.status == "max_iterations"
 assert result.metadata["iterations"] == 2
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_agent_loop_tool_execution:
 """Test that tools are executed and results are collected."""
 call_count = 0
 # Mock provider that returns tool call first, then final answer
 async def mock_chat(*args, **kwargs):
 nonlocal call_count
 call_count += 1
 if call_count == 1:
 # First call: request tool use
 return LLMResponse(
 content="",
 raw_content=[{"type": "tool_use", "id": "tc-1", "name": "echo", "input": {"message": "hello"}}],
 tool_calls=[ToolCall(id="tc-1", name="echo", arguments={"message": "hello"})],
 usage={"input_tokens": 10, "output_tokens": 5},
 stop_reason="tool_use",
 )
 else:
 # Second call: final answer
 return LLMResponse(
 content="Done with echo!",
 raw_content=[{"type": "text", "text": "Done with echo!"}],
 tool_calls=,
 usage={"input_tokens": 15, "output_tokens": 10},
 stop_reason="end_turn",
 )
 mock_provider = MagicMock
 mock_provider.chat = mock_chat
 mock_provider.get_tool_schema = MagicMock(return_value=)
 config = AgentConfig(max_iterations=5)
 context = AgentContext(session_id="test-3", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider)
 # Mock state manager
 loop.state_manager.save_state = AsyncMock
 loop.state_manager.log_tool_call = AsyncMock
 result = await loop.run("Echo hello")
 assert result.status == "completed"
 assert result.final_answer == "Done with echo!"
 assert result.usage["input_tokens"] == 25 # 10 + 15
 assert result.usage["output_tokens"] == 15 # 5 + 10
 assert len(result.output) == 1
 assert "Echo: hello" in result.output[0]
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_agent_loop_tool_error_handling:
 """Test that tool errors are returned to LLM, not thrown."""
 call_count = 0
 async def mock_chat(*args, **kwargs):
 nonlocal call_count
 call_count += 1
 if call_count == 1:
 # Request a non-existent tool
 return LLMResponse(
 content="",
 raw_content=[{"type": "tool_use", "id": "tc-1", "name": "nonexistent_tool", "input": {}}],
 tool_calls=[ToolCall(id="tc-1", name="nonexistent_tool", arguments={})],
 usage={"input_tokens": 10, "output_tokens": 5},
 stop_reason="tool_use",
 )
 else:
 # Final answer after seeing error
 return LLMResponse(
 content="I see the tool was not found.",
 raw_content=[{"type": "text", "text": "I see the tool was not found."}],
 tool_calls=,
 usage={"input_tokens": 15, "output_tokens": 10},
 stop_reason="end_turn",
 )
 mock_provider = MagicMock
 mock_provider.chat = mock_chat
 config = AgentConfig(max_iterations=5)
 context = AgentContext(session_id="test-4", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider)
 # Mock state manager
 loop.state_manager.save_state = AsyncMock
 # Should not raise - error is returned to LLM
 result = await loop.run("Use nonexistent tool")
 assert result.status == "completed"
 assert "not found" in result.final_answer.lower
