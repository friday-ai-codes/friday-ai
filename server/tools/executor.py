"""ToolExecutor: unified dispatcher for remote tool execution."""

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from tools.models import RemoteTool
from tools.registry import RemoteToolRegistry
from tools.sources.builtin import execute_builtin
from tools.sources.mcp_source import CommandNotAllowedError, execute_mcp
from tools.sources.skill import execute_skill

if TYPE_CHECKING:
    from interactions.models import InteractionRun

logger = structlog.get_logger(__name__)


async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    run: "InteractionRun | None" = None,
) -> dict[str, Any]:
    """Execute a remote tool by name, returning {"ok": bool, "result"|"error": ...}.

    ``run``（101-04 步级 trace）：仅透传给 skill 分支写步级 ToolCallRecord；
    builtin / mcp 分支签名不动，既有调用方零改动（默认 None）。
    """
    tool = await RemoteToolRegistry.aget_tool(tool_name)
    if not tool:
        return {
            "ok": False,
            "error": {"code": "not_found", "message": f"Tool not found: {tool_name}"},
        }

    try:
        result = await asyncio.wait_for(_dispatch(tool, arguments, run=run), timeout=tool.timeout)
        return {"ok": True, "result": result}
    except CommandNotAllowedError as e:
        logger.warning("mcp_command_not_allowed", tool=tool_name, command=e.command)
        return {"ok": False, "error": {"code": "command_not_allowed", "message": str(e)}}
    except TimeoutError:
        return {
            "ok": False,
            "error": {
                "code": "timeout",
                "message": f"Tool {tool_name} timed out after {tool.timeout}s",
            },
        }
    except Exception as e:
        logger.exception("tool_execution_failed", tool=tool_name)
        return {"ok": False, "error": {"code": "execution_error", "message": str(e)}}


async def _dispatch(
    tool: RemoteTool,
    arguments: dict[str, Any],
    run: "InteractionRun | None" = None,
) -> Any:
    if tool.source == RemoteTool.Source.BUILTIN:
        return await execute_builtin(tool, arguments)
    elif tool.source == RemoteTool.Source.MCP:
        return await execute_mcp(tool, arguments)
    elif tool.source == RemoteTool.Source.SKILL:
        return await execute_skill(tool, arguments, run=run)
    raise ValueError(f"Unknown source: {tool.source}")
