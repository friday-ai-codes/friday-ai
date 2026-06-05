"""ToolDefinition → LangChain StructuredTool 桥接模块（implementation contract）。

从 chat_runner.py 抽取 StructuredTool 装配三件套供 workflow 节点复用。
chat 场景和 workflow 节点场景共享此 helper，差异仅在 injected_values 字段：

- chat 场景：``{"project_id": ..., "conversation_id": ...}``
- workflow 节点：``{"project_id": ..., "session_id": ...}``

本 adapter v1 **不**支持 ``default_values`` 参数（Q2 选项 B 锁定）；chat_runner
的 ``default_search_branch`` "LLM 未提供时覆盖" 语义保留在 chat_runner 二次闭包
（Pitfall #12）。

公共 API：

    build_langchain_tools(tool_names, *, injected_values=None) -> list[BaseTool]

其中 ``injected_values`` 会在 ``tool_def.parameters.properties`` 中存在时，
从 ``args_schema`` 剔除并在运行时由闭包注入；不存在时静默忽略（避免污染不相关
工具的 args_schema）。
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from agents.tools.base import ToolDefinition, ToolResult, _tool_registry

__all__ = ["build_langchain_tools"]


def _schema_type_to_python(prop: dict[str, Any]) -> Any:
    """JSON Schema type → Python 类型（chat_runner.py work item 一字不改 copy）。

    支持 nullable union（``["string", "null"]`` 取非 null 首项）；未知类型 → ``Any``。
    """
    schema_type = prop.get("type", "string")
    if isinstance(schema_type, list):
        non_null = [item for item in schema_type if item != "null"]
        schema_type = non_null[0] if non_null else "string"
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict[str, Any],
        "array": list[Any],
    }.get(schema_type, Any)


def _build_args_schema(tool_def: ToolDefinition, hidden_fields: set[str]) -> type[BaseModel]:
    """ToolDefinition.parameters → pydantic BaseModel（chat_runner.py work item 一字不改 copy）。

    ``hidden_fields`` 从 ``properties`` 和 ``required`` 中都剔除，运行时由闭包注入。

    生成的模型类名使用 CapitalCase + ``"Args"`` 后缀，例如 ``search_repository_code``
    → ``SearchRepositoryCodeArgs``。
    """
    properties = tool_def.parameters.get("properties", {})
    required = set(tool_def.parameters.get("required", [])) - hidden_fields
    fields: dict[str, tuple[Any, Any]] = {}

    for name, prop in properties.items():
        if name in hidden_fields:
            continue
        annotation = _schema_type_to_python(prop)
        description = prop.get("description", "")
        if name in required:
            default = Field(..., description=description)
        else:
            default = Field(prop.get("default", None), description=description)
        fields[name] = (annotation, default)

    model_name = "".join(part.capitalize() for part in tool_def.name.split("_")) + "Args"
    return create_model(model_name, **cast(dict[str, Any], fields))


def build_langchain_tools(
    tool_names: list[str],
    *,
    injected_values: dict[str, Any] | None = None,
) -> list[BaseTool]:
    """按名从 ``_tool_registry`` 拉取 ToolDefinition 并包装为 LangChain StructuredTool。

    Args:
        tool_names: 要桥接的工具名列表；不在 ``_tool_registry`` 的名字**静默跳过**
            （向前兼容：允许节点声明白名单中偶有删除工具）。
        injected_values: 运行时由闭包注入的字段（不应暴露给 LLM），例如
            ``{"project_id": ..., "session_id": ..., "conversation_id": ...}``。
            这些字段会从对应工具的 ``args_schema`` 中剔除 + 调用时合并到 kwargs
            前传给 ``ToolDefinition.func``。

            **关键语义：** 仅注入 ``tool_def.parameters.properties`` 中存在的字段
            —— 若某工具不关心 ``session_id``，injected_values 中的 ``session_id``
            对该工具无效（既不 hide 也不注入），避免污染不相关工具的 args_schema。

    Returns:
        ``list[BaseTool]``（实际每个元素都是 ``StructuredTool``）。

    Examples:
        >>> tools = build_langchain_tools(
        ...     ["search_repository_code"],
        ...     injected_values={"project_id": "abc"},
        ... )
        >>> # tools[0].args_schema 不含 project_id 字段；运行时自动注入
    """
    injected_values = injected_values or {}
    tools: list[BaseTool] = []

    for tool_name in tool_names:
        if tool_name not in _tool_registry:
            continue
        tool_def = _tool_registry[tool_name]
        properties = tool_def.parameters.get("properties", {})

        # 只注入 properties 中存在的字段（避免 feishu_im_tools 等不关心
        # session_id 的工具被污染）
        active_injections = {k: v for k, v in injected_values.items() if k in properties}
        hidden_fields = set(active_injections.keys())
        args_schema = _build_args_schema(tool_def, hidden_fields)

        async def _execute(
            _tool_def: ToolDefinition = tool_def,
            _injected: dict[str, Any] = active_injections,
            **kwargs: Any,
        ) -> str:
            # injected 先入，kwargs 后入 —— 但由于 hidden_fields 已从 args_schema
            # 剔除，LLM 产出的 tool_call.args 经 pydantic 校验后不会含 injected
            # 字段，因此不存在"kwargs 覆盖 injected"的越权路径（security mitigation-01）。
            merged = {**_injected, **kwargs}
            result: ToolResult = await _tool_def.func(**merged)
            return result.to_content()

        tools.append(
            StructuredTool.from_function(
                coroutine=_execute,
                name=tool_def.name,
                description=tool_def.description,
                args_schema=args_schema,
                infer_schema=False,
            )
        )
    return tools
