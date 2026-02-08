"""
Tool framework for the Agent system.
Provides:
- @tool decorator for registering async functions as tools
- ToolResult for standardized tool output
- ToolDefinition for tool metadata
- ToolRegistry for tool discovery and schema generation
- Project and repository query tools
"""
from agents.tools.base import (
 ToolCategory,
 ToolDefinition,
 ToolResult,
 tool,
)
from agents.tools.project_tools import (
 get_repository_info,
 list_project_repositories,
 search_repository_code,
)
from agents.tools.registry import ToolRegistry
from agents.tools.work_item_tools import (
 add_work_item_comment,
 get_work_item_detail,
 list_related_work_items,
)
__all__ = [
 # Core framework
 "tool",
 "ToolResult",
 "ToolDefinition",
 "ToolCategory",
 "ToolRegistry",
 # Project tools
 "list_project_repositories",
 "get_repository_info",
 "search_repository_code",
 # Work item tools
 "get_work_item_detail",
 "list_related_work_items",
 "add_work_item_comment",
]
