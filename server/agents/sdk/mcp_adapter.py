"""MCP 适配层：将现有工具注册为 SDK MCP server。
工具本体零改动 — 通过适配器将 ToolDefinition 转为 SdkMcpTool，
handler 通过 **args 解包 dict 为命名参数调用原函数。
"""
from __future__ import annotations
from typing import Any
import structlog
from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server
from agents.tools.base import ToolCategory, ToolDefinition, ToolResult, _tool_registry
logger = structlog.get_logger(__name__)
MCP_SERVER_NAME = "chat-tools"
def _adapt_tool(tool_def: ToolDefinition) -> SdkMcpTool[dict[str, Any]]:
 """将 ToolDefinition 适配为 SdkMcpTool。
 工具函数本体不修改：通过 **args 解包 dict 为命名参数。
 ToolResult 返回值映射为 MCP 响应格式。
 Args:
 tool_def: 现有工具定义
 Returns:
 适配后的 SdkMcpTool 实例
 """
 async def handler(args: dict[str, Any]) -> dict[str, Any]:
 try:
 result: ToolResult = await tool_def.func(**args)
 content_text = result.to_content
 response: dict[str, Any] = {
 "content": [{"type": "text", "text": content_text}],
 }
 if not result.success:
 response["is_error"] = True
 return response
 except Exception as e:
 logger.exception(
 "mcp_tool_handler_error",
 tool=tool_def.name,
 error=str(e),
 )
 return {
 "content": [{"type": "text", "text": f"Error: {e}"}],
 "is_error": True,
 }
 return SdkMcpTool(
 name=tool_def.name,
 description=tool_def.description,
 input_schema=tool_def.parameters,
 handler=handler,
 )
def create_chat_tools_mcp_server -> McpSdkServerConfig:
 """创建包含所有 PROJECT 类别工具的 MCP server。
 遍历 _tool_registry 中 category == PROJECT 的工具，
 为每个生成 SdkMcpTool 适配器。返回值可直接放入
 ClaudeAgentOptions.mcp_servers 字典。
 Returns:
 McpSdkServerConfig (TypedDict)，包含 type="sdk"、name 和 server 实例
 """
 # 确保工具模块已导入（@tool 装饰器在导入时注册）
 import agents.tools.chat_tools # noqa: F401
 import agents.tools.project_tools # noqa: F401
 sdk_tools: list[SdkMcpTool[dict[str, Any]]] =
 for tool_def in _tool_registry.values:
 if tool_def.category == ToolCategory.PROJECT:
 sdk_tools.append(_adapt_tool(tool_def))
 logger.info(
 "mcp_server_created",
 server=MCP_SERVER_NAME,
 tool_count=len(sdk_tools),
 tools=[t.name for t in sdk_tools],
 )
 return create_sdk_mcp_server(name=MCP_SERVER_NAME, tools=sdk_tools)
async def build_allowed_tools(project_id: str) -> list[str]:
 """根据仓库索引状态动态生成 allowed_tools 列表。
 查询指定 project 下是否存在已索引仓库，
 有则返回所有 PROJECT 工具的 MCP 格式名，无则返回空列表。
 Args:
 project_id: 项目 UUID
 Returns:
 工具名列表，格式: mcp__chat-tools__{tool_name}
 """
 from repositories.models import Repository
 has_indexed = await Repository.objects.filter(
 projects__id=project_id,
 index_status="indexed",
 is_deleted=False,
 ).aexists
 if not has_indexed:
 logger.info(
 "no_indexed_repos",
 project_id=project_id,
 allowed_tools=,
 )
 return
 # 确保工具模块已导入
 import agents.tools.chat_tools # noqa: F401
 import agents.tools.project_tools # noqa: F401
 tools = [
 f"mcp__{MCP_SERVER_NAME}__{tool_def.name}"
 for tool_def in _tool_registry.values
 if tool_def.category == ToolCategory.PROJECT
 ]
 logger.info(
 "allowed_tools_built",
 project_id=project_id,
 tool_count=len(tools),
 )
 return tools
