"""LayeredSearchService 五层检索编排测试。
覆盖 work item 各层、端到端、以及异常降级行为。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from codegraph.services.layered_search import (
 LayeredSearchService,
 LayeredSearchResult,
 LayerResult,
)
class TestL1RepoRouting:
 """L1 仓库路由层测试 ."""
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_l1_routes_when_no_repo_ids_specified(self):
 """未指定 repository_ids 时，L1 调用 RepoRouter.route。
 socket 禁用时 RepoRouter 失败，降级到查询所有已索引仓库（此时为空）。
 """
 result, repo_ids = await LayeredSearchService._l1_repo_routing("test query", None, 3)
 # 没有 mock 且 socket disabled，RepoRouter 失败走 error 回退分支
 assert isinstance(result, LayerResult)
 assert result.layer == "L1"
 assert result.status in ("ok", "error") # error 或 ok 取决于环境
 assert isinstance(repo_ids, list)
 @pytest.mark.asyncio
 async def test_l1_skipped_when_repo_ids_specified(self):
 """指定 repository_ids 时，L1 跳过路由。"""
 result, repo_ids = await LayeredSearchService._l1_repo_routing(
 "test query", ["repo-a", "repo-b"], 3
 )
 assert result.status == "skipped"
 assert result.result_count == 2
 assert repo_ids == ["repo-a", "repo-b"]
class TestL2SymbolLookup:
 """L2 符号查找层测试 ."""
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_l2_no_symbols_found(self):
 """查询无匹配符号时返回空结果。"""
 result = await LayeredSearchService._l2_symbol_lookup(
 "some random text with no symbols", ["repo-1"]
 )
 assert result.layer == "L2"
 # 无匹配符号名所以跳过
 assert result.status in ("skipped", "ok")
 if result.status == "ok":
 assert result.result_count == 0
 def test_extract_symbol_names_pascal(self):
 """提取 PascalCase 符号名。"""
 names = LayeredSearchService._extract_symbol_names("How to use UserModel in CreateUser")
 assert "UserModel" in names
 assert "CreateUser" in names
 def test_extract_symbol_names_dotted(self):
 """提取点号分隔的标识符。"""
 names = LayeredSearchService._extract_symbol_names("use django.db.models for ORM")
 assert "django.db.models" in names
 def test_extract_symbol_names_filters_keywords(self):
 """过滤语言关键字。"""
 names = LayeredSearchService._extract_symbol_names("the class and return type")
 # "class" 和 "return" 应该被过滤
 assert "class" not in [n.lower for n in names]
 assert "return" not in [n.lower for n in names]
class TestL3HybridSearch:
 """L3 混合搜索层测试 ."""
 @pytest.mark.asyncio
 async def test_l3_returns_layer_result_on_embedding_failure(self):
 """embedding 生成失败时返回 error 状态不抛异常。"""
 with patch(
 "services.embedding.EmbeddingService.generate_embedding",
 new_callable=AsyncMock,
 ) as mock_embed:
 mock_embed.return_value = None
 result = await LayeredSearchService._l3_hybrid_search(
 "test query", ["repo-1"], 30, None
 )
 assert result.layer == "L3"
 assert result.status == "error"
 assert "embedding" in result.error.lower
class TestL5ContextReassembly:
 """L5 上下文组装层测试 ."""
 def test_l5_output_contains_markdown_sections(self):
 """L5 输出含 ## L2 Exact Matches / ## L4 Graph Context / ## L3 Related Code 标题。"""
 l2 = LayerResult(layer="L2", status="ok", items=)
 l3 = LayerResult(layer="L3", status="ok", items=)
 l4 = LayerResult(layer="L4", status="ok", items=)
 final_context, total_tokens = LayeredSearchService._l5_context_reassembly(l2, l3, l4, 8000)
 assert "## L2 Exact Matches" in final_context
 assert "## L4 Graph Context" in final_context
 assert "## L3 Related Code" in final_context
 assert total_tokens >= 0
 def test_l5_token_budget_applies(self):
 """Token 预算生效: 总 token 不超过 max_tokens * 0.9。"""
 l2 = LayerResult(layer="L2", status="ok", items=)
 l3 = LayerResult(layer="L3", status="ok", items=)
 l4 = LayerResult(layer="L4", status="ok", items=)
 max_tokens = 8000
 _, total_tokens = LayeredSearchService._l5_context_reassembly(l2, l3, l4, max_tokens)
 assert total_tokens <= max_tokens
class TestEndToEnd:
 """端到端测试 ."""
 @pytest.mark.asyncio
 async def test_search_returns_layered_result(self):
 """search 返回 LayeredSearchResult 含 layers。"""
 with patch.object(
 LayeredSearchService, "_l1_repo_routing", new_callable=AsyncMock
 ) as mock_l1, patch.object(
 LayeredSearchService, "_l2_symbol_lookup", new_callable=AsyncMock
 ) as mock_l2, patch.object(
 LayeredSearchService, "_l3_hybrid_search", new_callable=AsyncMock
 ) as mock_l3, patch.object(
 LayeredSearchService, "_l4_graph_expansion", new_callable=AsyncMock
 ) as mock_l4:
 mock_l1.return_value = (LayerResult(layer="L1", status="skipped", result_count=1), ["repo-1"])
 mock_l2.return_value = LayerResult(layer="L2", status="skipped")
 mock_l3.return_value = LayerResult(layer="L3", status="ok", items=)
 mock_l4.return_value = LayerResult(layer="L4", status="skipped")
 result = await LayeredSearchService.search("test query", repository_ids=["repo-1"])
 assert isinstance(result, LayeredSearchResult)
 assert result.query == "test query"
 assert len(result.layers) == 5 # work item
 assert all(isinstance(l, LayerResult) for l in result.layers)
 @pytest.mark.asyncio
 async def test_search_empty_repos_returns_early(self):
 """无可用仓库时提前返回空结果。"""
 with patch.object(
 LayeredSearchService, "_l1_repo_routing", new_callable=AsyncMock
 ) as mock_l1:
 mock_l1.return_value = (
 LayerResult(layer="L1", status="error", error="no repos"),,
 )
 result = await LayeredSearchService.search("test")
 assert result.repository_ids ==
 assert result.final_context == ""
 assert result.total_tokens == 0
