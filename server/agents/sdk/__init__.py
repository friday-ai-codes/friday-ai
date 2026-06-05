"""SDK 适配层：将现有工具桥接到 Claude Agent SDK。"""

from agents.sdk.event_adapter import EventAdapter
from agents.sdk.hooks import create_post_tool_use_hook, create_stop_hook
from agents.sdk.mcp_adapter import build_allowed_tools, create_chat_tools_mcp_server
from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig

__all__ = [
    "EventAdapter",
    "SDKAgentRunner",
    "SdkRunnerConfig",
    "build_allowed_tools",
    "create_chat_tools_mcp_server",
    "create_post_tool_use_hook",
    "create_stop_hook",
]
