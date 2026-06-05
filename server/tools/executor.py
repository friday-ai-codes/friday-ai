"""ToolExecutor: unified dispatcher for remote tool execution."""

import asyncio
from typing import Any

import structlog

from tools.models import RemoteTool
from tools.registry import RemoteToolRegistry
from tools.sources.builtin import execute_builtin
from tools.sources.mcp_source import CommandNotAllowedError, execute_mcp
from tools.sources.skill import execute_skill

logger = structlog.get_logger(__name__)


async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a remote tool by name, returning {"ok": bool, "result"|"error": ...}."""
    tool = await RemoteToolRegistry.aget_tool(tool_name)
    if not tool:
        return {"ok": False, "error": {"code": "not_found", "message": f"Tool not found: {tool_name}"}}

    try:
        result = await asyncio.wait_for(_dispatch(tool, arguments), timeout=tool.timeout)
        return {"ok": True, "result": result}
    except CommandNotAllowedError as e:
        logger.warning("mcp_command_not_allowed", tool=tool_name, command=e.command)
        return {"ok": False, "error": {"code": "command_not_allowed", "message": str(e)}}
    except TimeoutError:
        return {"ok": False, "error": {"code": "timeout", "message": f"Tool {tool_name} timed out after {tool.timeout}s"}}
    except Exception as e:
        logger.exception("tool_execution_failed", tool=tool_name)
        return {"ok": False, "error": {"code": "execution_error", "message": str(e)}}


async def _dispatch(tool: RemoteTool, arguments: dict[str, Any]) -> Any:
    if tool.source == RemoteTool.Source.BUILTIN:
        return await execute_builtin(tool, arguments)
    elif tool.source == RemoteTool.Source.MCP:
        return await execute_mcp(tool, arguments)
    elif tool.source == RemoteTool.Source.SKILL:
        return await execute_skill(tool, arguments)
    raise ValueError(f"Unknown source: {tool.source}")
