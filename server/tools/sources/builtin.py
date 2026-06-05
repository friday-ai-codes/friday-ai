"""Builtin tool executor: dynamically imports and calls handler functions."""

import importlib
from typing import Any

import structlog

from tools.models import RemoteTool

logger = structlog.get_logger(__name__)


async def execute_builtin(tool: RemoteTool, arguments: dict[str, Any]) -> str:
    """Execute a builtin tool by importing its handler from config["handler"]."""
    handler_path: str = tool.config["handler"]
    module_path, func_name = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)

    logger.info("execute_builtin", tool=tool.name, handler=handler_path)
    result = await func(**arguments)

    # ToolResult -> string for LLM consumption
    if hasattr(result, "to_content"):
        return result.to_content()
    return str(result)
