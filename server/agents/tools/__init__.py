"""
Tool framework for the Agent system.
Provides:
- @tool decorator for registering async functions as tools
- ToolResult for standardized tool output
- ToolDefinition for tool metadata
- ToolRegistry for tool discovery and schema generation
"""
from agents.tools.base import (
 ToolCategory,
 ToolDefinition,
 ToolResult,
 tool,
)
from agents.tools.registry import ToolRegistry
__all__ = [
 "tool",
 "ToolResult",
 "ToolDefinition",
 "ToolCategory",
 "ToolRegistry",
]
