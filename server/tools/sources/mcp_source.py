"""MCP Server tool executor: connects to external MCP servers via stdio."""
from typing import Any
import structlog
from mcp import ClientSession, StdioServerParameters, stdio_client
from tools.models import RemoteTool
logger = structlog.get_logger(__name__)
async def execute_mcp(tool: RemoteTool, arguments: dict[str, Any]) -> str:
 """Execute a tool on an MCP server (start process, call, shutdown)."""
 config = tool.config
 params = StdioServerParameters(
 command=config["server_command"],
 args=config.get("server_args", ),
 )
 tool_name: str = config.get("tool_name", tool.name)
 logger.info("execute_mcp", tool=tool.name, command=config["server_command"], mcp_tool=tool_name)
 async with stdio_client(params) as (read_stream, write_stream):
 async with ClientSession(read_stream, write_stream) as session:
 await session.initialize
 result = await session.call_tool(tool_name, arguments)
 # Extract text from first content block
 if result.content:
 first = result.content[0]
 return getattr(first, "text", str(first))
 return ""
