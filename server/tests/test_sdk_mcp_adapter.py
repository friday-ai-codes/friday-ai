"""MCP 适配层单元测试。

测试 _adapt_tool()、create_chat_tools_mcp_server()、build_allowed_tools()
的正确性，覆盖正常路径、错误路径、异常路径和 args 解包。
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.base import ToolCategory, ToolDefinition, ToolResult


def _make_tool_def(
    name: str = "test_tool",
    func: Any = None,
    parameters: dict[str, Any] | None = None,
) -> ToolDefinition:
    """创建测试用 ToolDefinition。"""
    if func is None:
        func = AsyncMock(return_value=ToolResult(success=True, output={"data": "ok"}))
    return ToolDefinition(
        name=name,
        description=f"Test tool: {name}",
        category=ToolCategory.PROJECT,
        parameters=parameters or {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
        func=func,
    )


class TestAdaptTool:
    """测试 _adapt_tool() 适配函数。"""

    @pytest.mark.asyncio
    async def test_adapt_tool_success(self) -> None:
        """ToolResult.success=True → 正确的 MCP 响应格式。"""
        from agents.sdk.mcp_adapter import _adapt_tool

        func = AsyncMock(return_value=ToolResult(success=True, output={"data": "test_value"}))
        tool_def = _make_tool_def(func=func)
        sdk_tool = _adapt_tool(tool_def)

        assert sdk_tool.name == "test_tool"
        assert sdk_tool.description == "Test tool: test_tool"
        assert sdk_tool.input_schema == tool_def.parameters

        result = await sdk_tool.handler({"q": "hello"})

        func.assert_awaited_once_with(q="hello")
        assert "content" in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert "test_value" in result["content"][0]["text"]
        assert "is_error" not in result

    @pytest.mark.asyncio
    async def test_adapt_tool_error(self) -> None:
        """ToolResult.success=False → is_error=True。"""
        from agents.sdk.mcp_adapter import _adapt_tool

        func = AsyncMock(return_value=ToolResult(success=False, error="something broke"))
        tool_def = _make_tool_def(func=func)
        sdk_tool = _adapt_tool(tool_def)

        result = await sdk_tool.handler({"q": "test"})

        assert result["is_error"] is True
        assert "something broke" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_adapt_tool_exception(self) -> None:
        """工具函数抛异常 → is_error=True + 异常信息。"""
        from agents.sdk.mcp_adapter import _adapt_tool

        func = AsyncMock(side_effect=ValueError("unexpected error"))
        tool_def = _make_tool_def(func=func)
        sdk_tool = _adapt_tool(tool_def)

        result = await sdk_tool.handler({"q": "test"})

        assert result["is_error"] is True
        assert "unexpected error" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_adapt_tool_args_unpacking_with_defaults(self) -> None:
        """验证 args dict 正确解包为命名参数，可选参数使用默认值。"""
        from agents.sdk.mcp_adapter import _adapt_tool

        call_args: dict[str, Any] = {}

        async def mock_func(query: str, limit: int = 10) -> ToolResult:
            call_args["query"] = query
            call_args["limit"] = limit
            return ToolResult(success=True, output="ok")

        tool_def = _make_tool_def(func=mock_func)
        sdk_tool = _adapt_tool(tool_def)

        # 只传 required 参数
        await sdk_tool.handler({"query": "hello"})
        assert call_args["query"] == "hello"
        assert call_args["limit"] == 10  # 使用默认值

    @pytest.mark.asyncio
    async def test_adapt_tool_args_unpacking_with_optional(self) -> None:
        """验证传入可选参数时正确覆盖默认值。"""
        from agents.sdk.mcp_adapter import _adapt_tool

        call_args: dict[str, Any] = {}

        async def mock_func(query: str, limit: int = 10) -> ToolResult:
            call_args["query"] = query
            call_args["limit"] = limit
            return ToolResult(success=True, output="ok")

        tool_def = _make_tool_def(func=mock_func)
        sdk_tool = _adapt_tool(tool_def)

        # 传入可选参数
        await sdk_tool.handler({"query": "hello", "limit": 5})
        assert call_args["limit"] == 5


class TestCreateMcpServer:
    """测试 create_chat_tools_mcp_server() 工厂函数。"""

    def test_create_mcp_server_returns_valid_config(self) -> None:
        """返回值包含 type="sdk" 和 name="chat-tools"。"""
        from agents.sdk.mcp_adapter import create_chat_tools_mcp_server

        config = create_chat_tools_mcp_server()

        assert isinstance(config, dict)
        assert config["type"] == "sdk"
        assert config["name"] == "chat-tools"
        assert "instance" in config

    def test_create_mcp_server_registers_project_tools(self) -> None:
        """验证注册了正确数量的 PROJECT 类别工具。"""
        # 确保工具已注册
        import agents.tools.chat_tools  # noqa: F401
        import agents.tools.space_tools  # noqa: F401
        from agents.tools.base import ToolCategory, _tool_registry

        expected_count = sum(
            1
            for td in _tool_registry.values()
            if td.category == ToolCategory.PROJECT
        )

        # 工厂函数内部调用 create_sdk_mcp_server(tools=sdk_tools)
        # 通过 patch 捕获传入的 tools 列表来验证
        with patch("agents.sdk.mcp_adapter.create_sdk_mcp_server") as mock_create:
            mock_create.return_value = {"type": "sdk", "name": "chat-tools", "instance": MagicMock()}

            from agents.sdk.mcp_adapter import create_chat_tools_mcp_server

            create_chat_tools_mcp_server()

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            _tools_arg = call_kwargs.kwargs.get("tools") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs.get("tools")

            # 从 call_args 获取 tools 参数
            if call_kwargs.kwargs.get("tools"):
                _tools_passed = call_kwargs.kwargs["tools"]
            else:
                # positional: name, tools
                _tools_passed = call_kwargs[1]["tools"] if isinstance(call_kwargs[1], dict) else []

        # 更简单的方式：直接检查 call 的参数
        actual_call = mock_create.call_args
        # create_sdk_mcp_server(name="chat-tools", tools=[...])
        assert actual_call.kwargs["name"] == "chat-tools"
        passed_tools = actual_call.kwargs["tools"]
        # MCP server 注册「所有 PROJECT 类工具」——数量随新增工具动态增长，
        # 因此对齐动态 expected_count，而非写死常量（历史写死 14 已随新增 PROJECT
        # 工具 associate_repos / save_project_feature_list 等漂移失效）。
        assert len(passed_tools) == expected_count

        # 核心工具必须全部暴露（子集校验，抗新增工具漂移）。
        tool_names = {t.name for t in passed_tools}
        core_tools = {
            "browse_file_content",
            "list_space_structure",
            "get_space_overview",
            "search_repository_code",
            "list_space_repositories",
            "get_repository_info",
            "find_related_code",
            "find_api_handler",
            "find_api_callers",
            "list_endpoints",
        }
        assert core_tools <= tool_names, f"缺失核心工具: {core_tools - tool_names}"


class TestBuildAllowedTools:
    """测试 build_allowed_tools() 动态过滤。"""

    @pytest.mark.asyncio
    async def test_build_allowed_tools_with_indexed_repos(self) -> None:
        """有已索引仓库时返回 MCP 格式工具名列表。"""
        from agents.sdk.mcp_adapter import build_allowed_tools

        mock_qs = MagicMock()
        mock_qs.aexists = AsyncMock(return_value=True)

        with patch("repositories.models.Repository") as mock_repo_cls:
            mock_repo_cls.objects.filter.return_value = mock_qs

            tools = await build_allowed_tools("test-project-id")

        assert len(tools) > 0
        # 验证所有工具名格式正确
        for name in tools:
            assert name.startswith("mcp__chat-tools__"), f"格式错误: {name}"

    @pytest.mark.asyncio
    async def test_build_allowed_tools_without_indexed_repos(self) -> None:
        """无已索引仓库时返回空列表。"""
        from agents.sdk.mcp_adapter import build_allowed_tools

        mock_qs = MagicMock()
        mock_qs.aexists = AsyncMock(return_value=False)

        with patch("repositories.models.Repository") as mock_repo_cls:
            mock_repo_cls.objects.filter.return_value = mock_qs

            tools = await build_allowed_tools("test-project-id")

        assert tools == []

    @pytest.mark.asyncio
    async def test_tool_name_format(self) -> None:
        """验证所有工具名遵循 mcp__chat-tools__{name} 格式。"""
        from agents.sdk.mcp_adapter import build_allowed_tools

        mock_qs = MagicMock()
        mock_qs.aexists = AsyncMock(return_value=True)

        with patch("repositories.models.Repository") as mock_repo_cls:
            mock_repo_cls.objects.filter.return_value = mock_qs

            tools = await build_allowed_tools("test-project-id")

        pattern = re.compile(r"^mcp__chat-tools__[a-z_]+$")
        for name in tools:
            assert pattern.match(name), f"工具名格式不匹配: {name}"

        # 数量等于当前注册表 PROJECT 类工具数（动态，抗新增工具漂移；历史写死 14 已失效）。
        from agents.tools.base import ToolCategory, _tool_registry

        expected_count = sum(
            1 for td in _tool_registry.values() if td.category == ToolCategory.PROJECT
        )
        assert len(tools) == expected_count
