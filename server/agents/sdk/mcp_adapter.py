"""MCP 适配层：将现有工具注册为 SDK MCP server。

工具本体零改动 — 通过适配器将 ToolDefinition 转为 SdkMcpTool，
handler 通过 **args 解包 dict 为命名参数调用原函数。

space_id 在适配层自动注入，不暴露给 LLM（避免 LLM 编造 UUID）。
"""

from __future__ import annotations

import copy
from typing import Any

import structlog
from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from agents.tools.base import ToolCategory, ToolDefinition, ToolResult, _tool_registry

logger = structlog.get_logger(__name__)

MCP_SERVER_NAME = "chat-tools"


def _adapt_tool(
    tool_def: ToolDefinition,
    inject_values: dict[str, Any] | None = None,
) -> SdkMcpTool[dict[str, Any]]:
    """将 ToolDefinition 适配为 SdkMcpTool。

    对于 inject_values 中的字段（如 space_id），从 input_schema 中移除
    使 LLM 看不到该参数，在 handler 中自动注入。

    Args:
        tool_def: 现有工具定义
        inject_values: 需要自动注入的字段 → 值映射

    Returns:
        适配后的 SdkMcpTool 实例
    """
    inject_values = inject_values or {}

    schema = copy.deepcopy(tool_def.parameters)
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for field_name in inject_values:
        props.pop(field_name, None)
        if field_name in required:
            required = [r for r in required if r != field_name]
    schema["properties"] = props
    schema["required"] = required

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        merged = {**inject_values, **args}
        try:
            result: ToolResult = await tool_def.func(**merged)
            content_text = result.to_content()
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
        input_schema=schema,
        handler=handler,
    )


def create_chat_tools_mcp_server(
    space_id: str = "",
    conversation_id: str = "",
    event_callback: Any = None,
) -> McpSdkServerConfig:
    """创建包含所有 PROJECT 类别工具的 MCP server。

    space_id、conversation_id、event_callback 被自动注入到需要它们的工具中，LLM 不可见。

    Args:
        space_id: 当前空间 UUID
        conversation_id: 当前对话 UUID（用于 deep_analysis 失败时中断会话）
        event_callback: 向 SSE 流推送事件的回调（用于深度分析实时进度）

    Returns:
        McpSdkServerConfig (TypedDict)
    """
    import agents.tools.chat_tools  # noqa: F401
    import agents.tools.space_tools  # noqa: F401

    inject_values: dict[str, Any] = {}
    if space_id:
        inject_values["space_id"] = space_id
    if conversation_id:
        inject_values["conversation_id"] = conversation_id
    if event_callback:
        inject_values["event_callback"] = event_callback

    sdk_tools: list[SdkMcpTool[dict[str, Any]]] = []
    for tool_def in _tool_registry.values():
        if tool_def.category == ToolCategory.PROJECT:
            tool_props = tool_def.parameters.get("properties", {})
            tool_inject = {k: v for k, v in inject_values.items() if k in tool_props}
            sdk_tools.append(
                _adapt_tool(tool_def, tool_inject if tool_inject else None)
            )

    logger.info(
        "mcp_server_created",
        server=MCP_SERVER_NAME,
        tool_count=len(sdk_tools),
        tools=[t.name for t in sdk_tools],
        space_id=space_id,
    )

    return create_sdk_mcp_server(name=MCP_SERVER_NAME, tools=sdk_tools)


async def build_allowed_tools(space_id: str) -> list[str]:
    """根据仓库索引状态动态生成 allowed_tools 列表。

    查询指定 space 下是否存在已索引仓库，
    有则返回所有 PROJECT 工具的 MCP 格式名，无则返回空列表。

    Args:
        space_id: 空间 UUID

    Returns:
        工具名列表，格式: mcp__chat-tools__{tool_name}
    """
    from repositories.models import Repository

    # space_id 为空（如 reposummary 失败后恢复 agent 会话的路径未携带有效 project_id）时，
    # 直接拿空字符串当 UUID 过滤会抛 ValidationError（badly formed hexadecimal UUID）。
    # 提前短路返回空白名单，避免污染失败处理链路。
    if not space_id:
        logger.info("build_allowed_tools_empty_space_id", allowed_tools=[])
        return []

    has_indexed = await Repository.objects.filter(
        projects__id=space_id,
        index_status="indexed",
        is_deleted=False,
    ).aexists()

    if not has_indexed:
        logger.info(
            "no_indexed_repos",
            space_id=space_id,
            allowed_tools=[],
        )
        return []

    # 确保工具模块已导入
    import agents.tools.chat_tools  # noqa: F401
    import agents.tools.space_tools  # noqa: F401

    tools = [
        f"mcp__{MCP_SERVER_NAME}__{tool_def.name}"
        for tool_def in _tool_registry.values()
        if tool_def.category == ToolCategory.PROJECT
    ]

    logger.info(
        "allowed_tools_built",
        space_id=space_id,
        tool_count=len(tools),
    )

    return tools
