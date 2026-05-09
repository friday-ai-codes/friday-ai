"""Integration tests for Agent tool framework."""
import pytest
from agents.tools import ToolRegistry, ToolResult, tool
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
async def test_tool_registration:
 """Test that @tool decorator registers tools."""
 tools = ToolRegistry.get_all_tools
 tool_names = [t.name for t in tools]
 assert "echo" in tool_names
@pytest.mark.asyncio
async def test_tool_schema_generation:
 """Test that tool schemas are generated correctly."""
 schemas = ToolRegistry.get_tool_schemas(["echo"])
 assert len(schemas) == 1
 assert schemas[0]["name"] == "echo"
 assert "input_schema" in schemas[0]
@pytest.mark.asyncio
async def test_tool_validation:
 """Test tool argument validation."""
 valid, err = ToolRegistry.validate_tool_arguments("echo", {"message": "hello"})
 assert valid is True
 valid, err = ToolRegistry.validate_tool_arguments("echo", {})
 assert valid is False
 assert "message" in err.lower
@pytest.mark.asyncio
async def test_search_repository_code_hybrid_search:
 """: search_repository_code 调用 BranchAwareSearchService.search 时传入 query_sparse 参数。"""
 from unittest.mock import AsyncMock, patch
 from services.embedding import EmbeddingService
 mock_search_result = [
 {
 "score": 0.95,
 "payload": {
 "file_path": "src/utils.py",
 "content": "def helper: pass",
 "language": "python",
 },
 }
 ]
 with (
 patch.object(
 EmbeddingService, "generate_embedding", new_callable=AsyncMock
 ) as mock_embed,
 patch(
 "services.sparse_encoder.SparseEncoderService.encode",
 return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]},
 ) as mock_sparse_encode,
 patch(
 "services.branch_search.BranchAwareSearchService.search",
 new_callable=AsyncMock,
 ) as mock_search,
 patch(
 "repositories.models.Repository.objects.filter",
 ) as mock_repo_filter,
 patch(
 "repositories.models.Repository.objects.aget",
 new_callable=AsyncMock,
 ) as mock_aget,
 ):
 mock_embed.return_value = [0.1] * 1536
 mock_search.return_value = mock_search_result
 # Mock Repository QuerySet 返回一个有索引的仓库
 mock_repo = AsyncMock
 mock_repo.id = "repo-1"
 mock_repo.default_branch = "main"
 # 需要让 repository 查找成功 (aget 返回 repo 对象)
 mock_aget.return_value = mock_repo
 from agents.tools import ToolRegistry
 tool_fn = ToolRegistry.get_tool("search_repository_code")
 assert tool_fn is not None
 result = await tool_fn.func(query="find helper function", repository_id="repo-1")
 # 验证 sparse encode 被调用
 mock_sparse_encode.assert_called_once_with("find helper function")
 # 验证 search 被调用时传入了 query_sparse
 call_kwargs = mock_search.call_args.kwargs
 assert "query_sparse" in call_kwargs
 assert call_kwargs["query_sparse"] == {"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}
@pytest.mark.asyncio
async def test_search_repository_code_empty_query_dense_only:
 """: 空 sparse 向量时退化为 dense-only，不传 query_sparse 或传 None。"""
 from unittest.mock import AsyncMock, patch
 from services.embedding import EmbeddingService
 mock_search_result = [
 {
 "score": 0.85,
 "payload": {
 "file_path": "src/main.py",
 "content": "def main: pass",
 "language": "python",
 },
 }
 ]
 with (
 patch.object(
 EmbeddingService, "generate_embedding", new_callable=AsyncMock
 ) as mock_embed,
 patch(
 "services.sparse_encoder.SparseEncoderService.encode",
 return_value={"indices":, "values": }, # 空 sparse 向量
 ) as mock_sparse_encode,
 patch(
 "services.branch_search.BranchAwareSearchService.search",
 new_callable=AsyncMock,
 ) as mock_search,
 patch(
 "repositories.models.Repository.objects.filter",
 ) as mock_repo_filter,
 patch(
 "repositories.models.Repository.objects.aget",
 new_callable=AsyncMock,
 ) as mock_aget,
 ):
 mock_embed.return_value = [0.1] * 1536
 mock_search.return_value = mock_search_result
 mock_repo = AsyncMock
 mock_repo.id = "repo-1"
 mock_repo.default_branch = "main"
 mock_aget.return_value = mock_repo
 from agents.tools import ToolRegistry
 tool_fn = ToolRegistry.get_tool("search_repository_code")
 assert tool_fn is not None
 result = await tool_fn.func(query="x", repository_id="repo-1")
 # 验证 search 被调用时 query_sparse 为 None（降级）
 call_kwargs = mock_search.call_args.kwargs
 assert call_kwargs.get("query_sparse") is None
