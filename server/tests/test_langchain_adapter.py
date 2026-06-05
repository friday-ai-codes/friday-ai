"""LangChain adapter 单元测试（implementation contract）。

覆盖 `agents.tools.langchain_adapter.build_langchain_tools` 的：
- 空列表 / 未知工具静默跳过
- 已知工具包装为 StructuredTool
- injected_values 仅注入 properties 中存在的字段（避免污染不相关 args_schema）
- hidden_fields 从 args_schema 剔除
- _schema_type_to_python / _build_args_schema 私有 helper 行为
- StructuredTool 运行时合并 injected + kwargs 传给原 ToolDefinition.func
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import BaseTool, StructuredTool

from agents.tools.base import ToolCategory, ToolDefinition, ToolResult, _tool_registry
from agents.tools.langchain_adapter import (
    _build_args_schema,
    _schema_type_to_python,
    build_langchain_tools,
)


# ============================================================================
# 测试辅助：临时注册一个 ToolDefinition 到 _tool_registry 的 fixture
# ============================================================================


def _register_fake_tool(
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    parameters: dict[str, Any],
    func: Any,
    description: str = "fake tool for unit test",
) -> ToolDefinition:
    """通过 monkeypatch.setitem 注册临时 ToolDefinition，测试后自动清理。"""
    tool_def = ToolDefinition(
        name=name,
        description=description,
        category=ToolCategory.GENERAL,
        parameters=parameters,
        func=func,
        requires_suspension=False,
    )
    monkeypatch.setitem(_tool_registry, name, tool_def)
    return tool_def


# ============================================================================
# Test 1：build_langchain_tools([]) 返回空列表
# ============================================================================


def test_empty_tool_names_returns_empty_list() -> None:
    assert build_langchain_tools([]) == []


# ============================================================================
# Test 2：未知工具名静默跳过（不 raise）
# ============================================================================


def test_unknown_tool_silently_skipped() -> None:
    result = build_langchain_tools(["definitely_not_a_real_tool_xyz"])
    assert result == []


def test_unknown_tool_mixed_with_known_returns_only_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop(**_kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output={"ok": True})

    _register_fake_tool(
        monkeypatch,
        name="fake_known_tool_mix",
        parameters={"type": "object", "properties": {}, "required": []},
        func=_noop,
    )
    result = build_langchain_tools(["fake_known_tool_mix", "not_exist_tool_qqq"])
    assert len(result) == 1
    assert result[0].name == "fake_known_tool_mix"


# ============================================================================
# Test 3：已知工具被包装为 StructuredTool（用真实注册的 send_plan_card）
# ============================================================================


def test_known_tool_wrapped_as_structured_tool() -> None:
    # 触发 send_plan_card 的 @tool 注册
    import agents.tools.send_plan_card  # noqa: F401

    assert "send_plan_card" in _tool_registry, "send_plan_card 应已在 _tool_registry"

    tools = build_langchain_tools(["send_plan_card"])
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "send_plan_card"
    assert isinstance(tool, BaseTool)
    assert isinstance(tool, StructuredTool)


# ============================================================================
# Test 4：injected_values 字段从 args_schema 剔除（hidden_fields 机制）
# ============================================================================


def test_injected_values_hides_fields_from_args_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop(**_kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output=None)

    _register_fake_tool(
        monkeypatch,
        name="fake_tool_with_project_id",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "internal id"},
                "user_input": {"type": "string", "description": "user question"},
            },
            "required": ["project_id", "user_input"],
        },
        func=_noop,
    )

    tools = build_langchain_tools(
        ["fake_tool_with_project_id"],
        injected_values={"project_id": "p1"},
    )
    assert len(tools) == 1
    tool = tools[0]
    schema = tool.args_schema
    # pydantic v2 model_fields
    field_names = set(schema.model_fields.keys())
    assert "project_id" not in field_names, "injected 字段应从 args_schema 剔除"
    assert "user_input" in field_names


# ============================================================================
# Test 5：injected_values 仅注入 properties 中存在的字段（不污染不相关 tool）
# ============================================================================


def test_injected_values_only_injects_existing_props(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """properties 只有 user_input 的工具，即便传 project_id/session_id 也不被 hide，
    且运行时不注入（active_injections 为空）。"""
    captured: dict[str, Any] = {}

    async def _capture(**kwargs: Any) -> ToolResult:
        captured.update(kwargs)
        return ToolResult(success=True, output={"received": True})

    _register_fake_tool(
        monkeypatch,
        name="fake_tool_no_injectable_fields",
        parameters={
            "type": "object",
            "properties": {
                "user_input": {"type": "string", "description": "user question"},
            },
            "required": ["user_input"],
        },
        func=_capture,
    )

    tools = build_langchain_tools(
        ["fake_tool_no_injectable_fields"],
        injected_values={"project_id": "p1", "session_id": "s1"},
    )
    assert len(tools) == 1
    tool = tools[0]
    field_names = set(tool.args_schema.model_fields.keys())
    assert field_names == {"user_input"}


# ============================================================================
# Test 6：_schema_type_to_python 基础类型映射
# ============================================================================


def test_schema_type_to_python_mapping() -> None:
    assert _schema_type_to_python({"type": "string"}) is str
    assert _schema_type_to_python({"type": "integer"}) is int
    assert _schema_type_to_python({"type": "number"}) is float
    assert _schema_type_to_python({"type": "boolean"}) is bool
    # nullable union：["string", "null"] → 取非 null 首项
    assert _schema_type_to_python({"type": ["string", "null"]}) is str
    # array / object
    assert _schema_type_to_python({"type": "array"}) == list[Any]
    assert _schema_type_to_python({"type": "object"}) == dict[str, Any]
    # 未知类型 → Any
    assert _schema_type_to_python({"type": "unknown_kind"}) is Any
    # 无 type 字段 → 默认 string
    assert _schema_type_to_python({}) is str


# ============================================================================
# Test 7：_build_args_schema 处理 required / optional 字段 + model 命名
# ============================================================================


def test_build_args_schema_respects_required() -> None:
    tool_def = ToolDefinition(
        name="build_args_test",
        description="",
        category=ToolCategory.GENERAL,
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "must have"},
                "b": {"type": "string", "description": "optional"},
            },
            "required": ["a"],
        },
        func=lambda: None,  # type: ignore[arg-type]
        requires_suspension=False,
    )
    schema = _build_args_schema(tool_def, hidden_fields=set())
    fields = schema.model_fields
    assert "a" in fields and "b" in fields
    # required 字段 default 为 PydanticUndefined / is_required() True
    assert fields["a"].is_required() is True
    assert fields["b"].is_required() is False
    # 模型类名使用 CapitalCase + "Args" 后缀
    assert schema.__name__ == "BuildArgsTestArgs"


def test_build_args_schema_hidden_fields_excluded() -> None:
    tool_def = ToolDefinition(
        name="hidden_test",
        description="",
        category=ToolCategory.GENERAL,
        parameters={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["project_id", "query"],
        },
        func=lambda: None,  # type: ignore[arg-type]
        requires_suspension=False,
    )
    schema = _build_args_schema(tool_def, hidden_fields={"project_id"})
    assert set(schema.model_fields.keys()) == {"query"}
    # query 仍 required（hidden_fields 从 required 集合中剔除 project_id 后 query 保持）
    assert schema.model_fields["query"].is_required() is True


# ============================================================================
# Test 8：StructuredTool 执行时合并 injected + kwargs 传给原 func，并 to_content 序列化
# ============================================================================


@pytest.mark.asyncio
async def test_structured_tool_execution_merges_injected_and_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _record(**kwargs: Any) -> ToolResult:
        captured.update(kwargs)
        return ToolResult(success=True, output={"hit": 1})

    _register_fake_tool(
        monkeypatch,
        name="fake_merge_tool",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["project_id", "query"],
        },
        func=_record,
    )

    tools = build_langchain_tools(
        ["fake_merge_tool"],
        injected_values={"project_id": "p1"},
    )
    assert len(tools) == 1
    tool = tools[0]

    # StructuredTool.coroutine 是 adapter 内部 _execute 闭包
    assert tool.coroutine is not None
    # LLM 视角只传 query；project_id 由闭包注入
    content = await tool.coroutine(query="x")

    assert captured == {"project_id": "p1", "query": "x"}
    # 返回 to_content() 的字符串（JSON dump）
    assert isinstance(content, str)
    assert '"hit": 1' in content


@pytest.mark.asyncio
async def test_structured_tool_execution_error_path_to_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ToolResult.success=False 时返回 'Error: {error}' 字符串。"""

    async def _fail(**_kwargs: Any) -> ToolResult:
        return ToolResult(success=False, output=None, error="boom")

    _register_fake_tool(
        monkeypatch,
        name="fake_error_tool",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        func=_fail,
    )

    tools = build_langchain_tools(["fake_error_tool"])
    assert len(tools) == 1
    content = await tools[0].coroutine(q="x")
    assert content == "Error: boom"
