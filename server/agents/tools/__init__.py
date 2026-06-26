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
from agents.tools.board_split_tools import split_feature_list_to_boards
from agents.tools.clarification import ask_clarification
from agents.tools.delivery_knowledge_tools import (
    get_entity_timeline,
    get_related_entities,
    search_delivery_knowledge,
)
from agents.tools.feishu_doc_tools import (
    create_feishu_document,
    fetch_feishu_document,
)
from agents.tools.feishu_im_tools import send_card_message
from agents.tools.find_api_callers import find_api_callers
from agents.tools.find_api_handler import find_api_handler
from agents.tools.find_related_code import find_related_code
from agents.tools.langchain_adapter import build_langchain_tools
from agents.tools.list_endpoints import list_endpoints
from agents.tools.plan_research_tools import start_plan_research
from agents.tools.registry import ToolRegistry
from agents.tools.repository_relevance import analyze_repository_relevance
from agents.tools.send_plan_card import send_plan_card
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
    # LangChain bridge (implementation contract)
    "build_langchain_tools",
    # Space tools
    "list_space_repositories",
    "get_repository_info",
    "search_repository_code",
    # Code graph tools (implementation)
    "find_related_code",
    # Delivery knowledge tools (Phase 16)
    "search_delivery_knowledge",
    "get_entity_timeline",
    "get_related_entities",
    # API graph tools (implementation)
    "find_api_handler",
    "find_api_callers",
    "list_endpoints",
    # Cross-repo relevance (implementation)
    "analyze_repository_relevance",
    # Clarification (implementation)
    "ask_clarification",
    # Work item tools
    "get_work_item_detail",
    "list_related_work_items",
    "add_work_item_comment",
    # Board split tool (BOARD-01)
    "split_feature_list_to_boards",
    # Feishu IM tools
    "send_card_message",
    "send_plan_card",
    # Feishu document tools
    "fetch_feishu_document",
    "create_feishu_document",
    # User interaction tools
    "ask_user_question",
    # Plan verification tools
    "verify_plan",
    # Plan orchestration chat entry (ENTRY-02)
    "start_plan_research",
]
