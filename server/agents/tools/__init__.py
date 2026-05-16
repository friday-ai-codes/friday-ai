"""
Tool framework for the Agent system.
Provides:
- @tool decorator for registering async functions as tools
- ToolResult for standardized tool output
- ToolDefinition for tool metadata
- ToolRegistry for tool discovery and schema generation
- Space and repository query tools
"""
from agents.tools.base import (
 ToolCategory,
 ToolDefinition,
 ToolResult,
 tool,
)
from agents.tools.feishu_doc_tools import (
 create_feishu_document,
 fetch_feishu_document,
)
from agents.tools.feishu_im_tools import send_card_message
from agents.tools.find_api_callers import find_api_callers
from agents.tools.find_api_handler import find_api_handler
from agents.tools.find_related_code import find_related_code
from agents.tools.list_endpoints import list_endpoints
from agents.tools.langchain_adapter import build_langchain_tools
from agents.tools.registry import ToolRegistry
from agents.tools.space_tools import (
 get_repository_info,
 list_space_repositories,
 search_repository_code,
)
from agents.tools.user_interaction import ask_user_question
from agents.tools.verify_plan import verify_plan
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
 # LangChain bridge (Phase)
 "build_langchain_tools",
 # Space tools
 "list_space_repositories",
 "get_repository_info",
 "search_repository_code",
 # Code graph tools (Phase)
 "find_related_code",
 # API graph tools (Phase)
 "find_api_handler",
 "find_api_callers",
 "list_endpoints",
 # Work item tools
 "get_work_item_detail",
 "list_related_work_items",
 "add_work_item_comment",
 # Feishu IM tools
 "send_card_message",
 # Feishu document tools
 "fetch_feishu_document",
 "create_feishu_document",
 # User interaction tools
 "ask_user_question",
 # Plan verification tools
 "verify_plan",
]
