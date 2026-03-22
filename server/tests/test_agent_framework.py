"""Integration tests for Agent tool framework."""
import pytest
from agents.tools import ToolRegistry, ToolResult, tool
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
