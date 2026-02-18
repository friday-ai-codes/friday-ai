"""Skill executor: sequentially executes a list of tool steps."""
from typing import Any
import structlog
from tools.models import RemoteTool
logger = structlog.get_logger(__name__)
async def execute_skill(tool: RemoteTool, arguments: dict[str, Any]) -> list[dict[str, Any]]:
 """Execute skill steps sequentially. Aborts on first failure."""
 # Import here to avoid circular import (executor -> skill -> executor)
 from tools.executor import execute_tool
 steps: list[dict[str, Any]] = tool.config.get("steps", )
 results: list[dict[str, Any]] =
 for i, step in enumerate(steps):
 step_name: str = step["tool_name"]
 step_args: dict[str, Any] = step.get("arguments", {})
 logger.info("execute_skill_step", tool=tool.name, step=i, step_tool=step_name)
 result = await execute_tool(step_name, step_args)
 results.append(result)
 if not result.get("ok"):
 logger.warning("skill_step_failed", tool=tool.name, step=i, step_tool=step_name)
 break
 return results
