"""Integration tests for Agent tool framework."""

import uuid

import pytest

from agents.tools import ToolRegistry, ToolResult, tool

# search_repository_code 对非 UUID 的 scope 直接判空（避免 ORM ValidationError → 500），
# 因此这里必须用合法 UUID 才能走到 HybridSearchService。
_REPO_ID = str(uuid.uuid4())


# Test tool
@tool(
    name="echo",
    description="Echo the input message",
    category="GENERAL",
    parameters={
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    },
)
async def echo_tool(message: str) -> ToolResult:
    return ToolResult(success=True, output=f"Echo: {message}")


@pytest.mark.asyncio
async def test_tool_registration():
    """Test that @tool decorator registers tools."""
    tools = ToolRegistry.get_all_tools()
    tool_names = [t.name for t in tools]
    assert "echo" in tool_names


@pytest.mark.asyncio
async def test_tool_schema_generation():
    """Test that tool schemas are generated correctly."""
    schemas = ToolRegistry.get_tool_schemas(["echo"])
    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"
    assert "input_schema" in schemas[0]


@pytest.mark.asyncio
async def test_tool_validation():
    """Test tool argument validation."""
    valid, err = ToolRegistry.validate_tool_arguments("echo", {"message": "hello"})
    assert valid is True

    valid, err = ToolRegistry.validate_tool_arguments("echo", {})
    assert valid is False
    assert "message" in err.lower()


@pytest.mark.asyncio
async def test_search_repository_code_hybrid_search():
    """search_repository_code 统一经 HybridSearchService.search 检索（query + repo + top_k）。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_result = SimpleNamespace(final_context="", layers=[])
    mock_service = MagicMock()
    mock_service.search = AsyncMock(return_value=mock_result)

    with (
        patch(
            "services.retrieval.HybridSearchService",
            return_value=mock_service,
        ),
        patch("services.code_intel.get_provider", return_value=MagicMock()),
        patch(
            "repositories.models.Repository.objects.aget",
            new_callable=AsyncMock,
        ) as mock_aget,
    ):
        mock_repo = AsyncMock()
        mock_repo.id = _REPO_ID
        mock_repo.default_branch = "main"
        mock_aget.return_value = mock_repo

        from agents.tools import ToolRegistry

        tool_fn = ToolRegistry.get_tool("search_repository_code")
        assert tool_fn is not None

        result = await tool_fn.func(query="find helper function", repository_id=_REPO_ID)

        assert result.success is True
        # 验证统一经 HybridSearchService.search 检索，带上目标仓库 + top_k
        mock_service.search.assert_awaited_once()
        call = mock_service.search.call_args
        assert call.args[0] == "find helper function"
        assert call.kwargs["repository_ids"] == [_REPO_ID]
        assert call.kwargs["top_k"] == 20


@pytest.mark.asyncio
async def test_search_repository_code_empty_query_dense_only():
    """指定 repository_id 时 HybridSearchService.search 收到该仓库与 branch=None。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_result = SimpleNamespace(final_context="", layers=[])
    mock_service = MagicMock()
    mock_service.search = AsyncMock(return_value=mock_result)

    with (
        patch(
            "services.retrieval.HybridSearchService",
            return_value=mock_service,
        ),
        patch("services.code_intel.get_provider", return_value=MagicMock()),
        patch(
            "repositories.models.Repository.objects.aget",
            new_callable=AsyncMock,
        ) as mock_aget,
    ):
        mock_repo = AsyncMock()
        mock_repo.id = _REPO_ID
        mock_repo.default_branch = "main"
        mock_aget.return_value = mock_repo

        from agents.tools import ToolRegistry

        tool_fn = ToolRegistry.get_tool("search_repository_code")
        assert tool_fn is not None

        result = await tool_fn.func(query="x", repository_id=_REPO_ID)

        assert result.success is True
        call = mock_service.search.call_args
        assert call.kwargs["repository_ids"] == [_REPO_ID]
        assert call.kwargs["branch_name"] is None
