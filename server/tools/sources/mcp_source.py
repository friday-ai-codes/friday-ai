"""MCP Server tool executor: connects to external MCP servers via stdio."""
from typing import Any
import structlog
from django.conf import settings
from mcp import ClientSession, StdioServerParameters, stdio_client
from tools.models import RemoteTool
logger = structlog.get_logger(__name__)
class CommandNotAllowedError(Exception):
 """MCP 命令不在白名单中。"""
 def __init__(self, command: str) -> None:
 self.command = command
 super.__init__(f"命令 '{command}' 不在 MCP 白名单中")
async def execute_mcp(tool: RemoteTool, arguments: dict[str, Any]) -> str:
 """Execute a tool on an MCP server (start process, call, shutdown)."""
 config = tool.config
 server_command: str = config["server_command"]
 # 白名单校验：未授权命令直接拒绝，不启动子进程
 if server_command not in settings.MCP_ALLOWED_COMMANDS:
 logger.warning("mcp_command_blocked", tool=tool.name, command=server_command)
 raise CommandNotAllowedError(server_command)
 params = StdioServerParameters(
 command=server_command,
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
