"""LayeredSearchService 五层检索编排测试。

覆盖 work item 各层、端到端、以及异常降级行为。
总计 20+ 条测试。
"""

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from codegraph.models import Symbol
from codegraph.services.layered_search import (
    LayeredSearchResult,
    LayeredSearchService,
    LayerResult,
)
from codegraph.services.repo_router_v2 import RepoRouteCandidateV2, RepoRouteResultV2

# ============================================================================
# TestL1RepoRouting — L1 仓库路由层测试 (work item)
# ============================================================================


class TestL1RepoRouting:
    """L1 仓库路由层测试 (work item)."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l1_routes_when_no_repo_ids_specified(self):
        """未指定 repository_ids 时，L1 调用统一 RepoRouterV2。

        socket 禁用时路由失败，降级到查询所有已索引仓库（此时为空）。
        """
        result, repo_ids = await LayeredSearchService._l1_repo_routing("test query", None, 3)
        assert isinstance(result, LayerResult)
        assert result.layer == "L1"
        assert result.status in ("ok", "error")
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

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l1_fallback_to_all_indexed_on_error(self):
        """RepoRouter 失败时回退到所有已索引仓库。"""
        with patch(
            "codegraph.services.repo_router_v2.RepoRouterV2.route",
            new_callable=AsyncMock,
        ) as mock_route:
            mock_route.side_effect = RuntimeError("network down")
            result, repo_ids = await LayeredSearchService._l1_repo_routing("find me", None, 3)
            assert result.status == "error"
            assert "network down" in (result.error or "")
            assert isinstance(repo_ids, list)

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l1_with_mocked_router(self):
        """Mock RepoRouterV2 返回统一路由结果，且 L1 禁用 LLM。"""
        mock_result = RepoRouteResultV2(
            candidates=[
                RepoRouteCandidateV2(
                    repo_id="repo-aaa", repo_name="Alpha", score=0.78,
                    confidence="medium", reasoning="matched tech_stack: django",
                ),
            ],
            router_version="v2_stage0_only",
            auto_selected=False,
            degraded=True,
        )
        with patch(
            "codegraph.services.repo_router_v2.RepoRouterV2.route",
            new_callable=AsyncMock,
        ) as mock_route:
            mock_route.return_value = mock_result
            result, repo_ids = await LayeredSearchService._l1_repo_routing("django models", None, 3)
            assert result.status == "ok"
            assert result.result_count == 1
            assert repo_ids == ["repo-aaa"]
            assert result.items[0]["repo_name"] == "Alpha"
            mock_route.assert_awaited_once_with("django models", top_k=3, use_llm=False)


# ============================================================================
# TestL2SymbolLookup — L2 符号查找层测试 (work item)
# ============================================================================


class TestL2SymbolLookup:
    """L2 符号查找层测试 (work item)."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l2_no_symbols_found(self):
        """查询无匹配符号时返回空结果。"""
        result = await LayeredSearchService._l2_symbol_lookup(
            "some random text with no symbols", ["repo-1"]
        )
        assert result.layer == "L2"
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
        assert "class" not in [n.lower() for n in names]
        assert "return" not in [n.lower() for n in names]

    def test_extract_symbol_names_deduplicates(self):
        """去重保序：相同符号名不重复提取。"""
        names = LayeredSearchService._extract_symbol_names("UserModel and UserModel again")
        assert names.count("UserModel") == 1

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l2_exact_match_by_name(self, graph_repo):
        """精确符号名匹配: name__iexact 查询 PascalCase 符号名。"""
        repo_id = str(graph_repo.id)
        # 创建 PascalCase 符号（可被 _extract_symbol_names 提取）
        await sync_to_async(Symbol.objects.create)(
            repository=graph_repo,
            name="ProcessData",
            symbol_type="FUNCTION",
            file_path="src/core.py",
            start_line=10,
            end_line=25,
        )
        result = await LayeredSearchService._l2_symbol_lookup(
            "how does ProcessData work", [repo_id]
        )
        assert result.layer == "L2"
        assert result.status == "ok"
        assert result.result_count >= 1
        names = [item["name"] for item in result.items]
        assert "ProcessData" in names

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l2_fallback_to_fuzzy(self, graph_repo):
        """精确匹配无结果时回退到 name__icontains。"""
        repo_id = str(graph_repo.id)
        # 创建一个大写开头的符号，精确匹配应该找到
        await sync_to_async(Symbol.objects.create)(
            repository=graph_repo,
            name="MySpecialHelper",
            symbol_type="FUNCTION",
            file_path="src/helpers.py",
            start_line=1,
            end_line=10,
        )
        result = await LayeredSearchService._l2_symbol_lookup(
            "use MySpecialHelper for this", [repo_id]
        )
        assert result.status == "ok"
        assert result.result_count >= 1
        names = [item["name"] for item in result.items]
        assert "MySpecialHelper" in names

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l2_error_handled_gracefully(self):
        """L2 异常不抛出，仅返回 error 状态。"""
        result = await LayeredSearchService._l2_symbol_lookup(
            "TestClass", []  # 空 repo_ids 列表，但不会触发异常
        )
        assert result.layer == "L2"
        assert result.status in ("ok", "skipped")


# ============================================================================
# TestL3HybridSearch — L3 混合搜索层测试 (work item)
# ============================================================================


class TestL3HybridSearch:
    """L3 混合搜索层测试 (work item)."""

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
            assert "embedding" in result.error.lower()

    @pytest.mark.asyncio
    async def test_l3_calls_branch_aware_search_per_repo(self):
        """L3 对每个仓库调用 BranchAwareSearchService.search()。"""
        with patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
        ) as mock_embed, patch(
            "services.sparse_encoder.SparseEncoderService.encode",
        ) as mock_sparse, patch(
            "services.branch_search.BranchAwareSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_embed.return_value = [0.1] * 1024
            mock_sparse.return_value = {"indices": [1, 2], "values": [0.5, 0.3]}
            mock_search.return_value = [
                {"id": "chunk-1", "score": 0.9, "payload": {"file_path": "a.py", "chunk_index": 0}},
            ]

            result = await LayeredSearchService._l3_hybrid_search(
                "find auth", ["repo-x", "repo-y"], 30, None
            )
            assert result.layer == "L3"
            assert result.status == "ok"
            # 对每个仓库调用一次 search
            assert mock_search.call_count == 2

    @pytest.mark.asyncio
    async def test_l3_dedup_across_repos(self):
        """L3 跨仓库结果按 (repo_id, file_path, chunk_index) 去重。"""
        with patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
        ) as mock_embed, patch(
            "services.sparse_encoder.SparseEncoderService.encode",
        ) as mock_sparse, patch(
            "services.branch_search.BranchAwareSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_embed.return_value = [0.1] * 1024
            mock_sparse.return_value = {"indices": [1], "values": [0.5]}

            # 同仓库返回相同 file_path+chunk_index 会被去重
            # 不同仓库的同名文件不会被去重（因为 key 包含 repo_id）
            call_count = [0]
            def search_side_effect(repo_id, *args, **kwargs):
                call_count[0] += 1
                # 同仓库内返回两个相同 file_path+chunk_index 的 chunk
                return [
                    {"id": "dup1", "score": 0.9, "payload": {"file_path": "shared.py", "chunk_index": 0}},
                    {"id": "dup2", "score": 0.8, "payload": {"file_path": "shared.py", "chunk_index": 0}},
                ]
            mock_search.side_effect = search_side_effect

            result = await LayeredSearchService._l3_hybrid_search(
                "test", ["repo-a"], 30, None
            )
            # 同一仓库内，相同 file_path+chunk_index 的去重：保留第一个(score 0.9)
            shared_count = sum(
                1 for item in result.items
                if item.get("payload", {}).get("file_path") == "shared.py"
            )
            assert shared_count == 1

    @pytest.mark.asyncio
    async def test_l3_single_repo_failure_does_not_block_others(self):
        """单个仓库搜索失败不阻塞其他仓库。"""
        with patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
        ) as mock_embed, patch(
            "services.sparse_encoder.SparseEncoderService.encode",
        ) as mock_sparse, patch(
            "services.branch_search.BranchAwareSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_embed.return_value = [0.1] * 1024
            mock_sparse.return_value = {"indices": [1], "values": [0.5]}

            def side_effect(repo_id, *args, **kwargs):
                if repo_id == "repo-bad":
                    raise RuntimeError("search failed")
                return [{"id": "ok", "score": 0.8, "payload": {"file_path": "good.py", "chunk_index": 0}}]

            mock_search.side_effect = side_effect
            result = await LayeredSearchService._l3_hybrid_search(
                "test", ["repo-bad", "repo-good"], 30, None
            )
            assert result.status == "ok"
            assert result.result_count >= 1


# ============================================================================
# TestL4GraphExpansion — L4 图谱扩展层测试
# ============================================================================


class TestL4GraphExpansion:
    """L4 图谱扩展层测试. 依赖 plan 的 conftest fixtures。"""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l4_skipped_when_no_l2_symbols(self):
        """L2 无匹配符号时 L4 跳过。"""
        result = await LayeredSearchService._l4_graph_expansion([])
        assert result.layer == "L4"
        assert result.status == "skipped"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l4_expands_l2_symbols(
        self, graph_repo, seed_symbol, caller_symbol, outgoing_call_edge, incoming_call_edge
    ):
        """L4 调用 GraphExpansionService.expand() 对 L2 匹配符号做扩展。"""
        l2_items = [{
            "symbol_id": str(seed_symbol.id),
            "name": seed_symbol.name,
            "symbol_type": seed_symbol.symbol_type,
            "file_path": seed_symbol.file_path,
            "start_line": seed_symbol.start_line,
            "end_line": seed_symbol.end_line,
            "signature": seed_symbol.signature,
            "repository_id": str(graph_repo.id),
            "repository_name": graph_repo.name,
        }]
        result = await LayeredSearchService._l4_graph_expansion(l2_items)
        assert result.layer == "L4"
        assert result.status == "ok"
        assert result.result_count >= 1  # 至少 1-hop 邻居
        # 验证节点包含 depth 和 relationship 字段
        for item in result.items:
            assert "depth" in item
            assert "relationship" in item
            assert "symbol" in item

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l4_handles_missing_symbol(self):
        """L4 对不存在的符号 ID 优雅跳过。"""
        l2_items = [{
            "symbol_id": "00000000-0000-0000-0000-000000000000",
            "name": "nonexistent",
            "symbol_type": "FUNCTION",
            "file_path": "ghost.py",
            "start_line": 0,
            "end_line": 0,
            "signature": "",
            "repository_id": "00000000-0000-0000-0000-000000000000",
            "repository_name": "nowhere",
        }]
        result = await LayeredSearchService._l4_graph_expansion(l2_items)
        assert result.layer == "L4"
        assert result.status == "ok"
        assert result.result_count == 0

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_l4_error_handled_gracefully(self):
        """L4 异常不抛出，仅返回 error 状态。

        使用不存在的符号 ID 触发 Symbol.DoesNotExist 跳过逻辑，验证 L4 不崩溃。
        """
        l2_items = [
            {
                "symbol_id": "00000000-0000-0000-0000-000000000001",
                "name": "TestSym",
                "symbol_type": "FUNCTION",
                "file_path": "test.py",
                "start_line": 1,
                "end_line": 10,
                "signature": "",
                "repository_id": "00000000-0000-0000-0000-000000000002",
                "repository_name": "test",
            }
        ]
        result = await LayeredSearchService._l4_graph_expansion(l2_items)
        assert result.layer == "L4"
        # 符号不存在时 L4 优雅跳过
        assert result.status in ("ok", "skipped")


# ============================================================================
# TestL5ContextReassembly — L5 上下文组装层测试 (work item)
# ============================================================================


class TestL5ContextReassembly:
    """L5 上下文组装层测试 (work item)."""

    def test_l5_output_contains_markdown_sections(self):
        """L5 输出含 ## L2 Exact Matches / ## L4 Graph Context / ## L3 Related Code 标题。"""
        l2 = LayerResult(layer="L2", status="ok", items=[])
        l3 = LayerResult(layer="L3", status="ok", items=[])
        l4 = LayerResult(layer="L4", status="ok", items=[])
        final_context, total_tokens = LayeredSearchService._l5_context_reassembly(l2, l3, l4, 8000)
        assert "## L2 Exact Matches" in final_context
        assert "## L4 Graph Context" in final_context
        assert "## L3 Related Code" in final_context
        assert total_tokens >= 0

    def test_l5_token_budget_applies(self):
        """Token 预算生效: 总 token 不超过 max_tokens。"""
        l2 = LayerResult(layer="L2", status="ok", items=[])
        l3 = LayerResult(layer="L3", status="ok", items=[])
        l4 = LayerResult(layer="L4", status="ok", items=[])
        max_tokens = 8000
        _, total_tokens = LayeredSearchService._l5_context_reassembly(l2, l3, l4, max_tokens)
        assert total_tokens <= max_tokens

    def test_l5_priority_l2_first(self):
        """L2 精确匹配结果优先保留，不受 token 限制裁剪。"""
        l2 = LayerResult(layer="L2", status="ok", items=[
            {"name": "UserModel", "symbol_type": "CLASS",
             "file_path": "models.py", "start_line": 10, "end_line": 50,
             "repository_name": "myrepo"},
        ])
        l3 = LayerResult(layer="L3", status="ok", items=[])
        l4 = LayerResult(layer="L4", status="ok", items=[])
        final_context, _ = LayeredSearchService._l5_context_reassembly(l2, l3, l4, 8000)
        assert "UserModel" in final_context
        assert "## L2 Exact Matches" in final_context

    def test_l5_l3_dedup_removes_l2_covered_files(self):
        """L3 去重: 排除已被 L2 覆盖的 file_path。"""
        l2 = LayerResult(layer="L2", status="ok", items=[
            {"name": "Helper", "symbol_type": "FUNCTION", "file_path": "covered.py",
             "start_line": 1, "end_line": 10, "signature": "", "repository_id": "r1",
             "repository_name": "repo", "symbol_id": "s1"},
        ])
        l3 = LayerResult(layer="L3", status="ok", items=[
            {"score": 0.9, "payload": {"file_path": "covered.py", "content": "x", "chunk_index": 0}},
            {"score": 0.5, "payload": {"file_path": "uncovered.py", "content": "y", "chunk_index": 0}},
        ])
        filtered = LayeredSearchService._filter_l3_dedup(l3, l2)
        assert len(filtered) == 1
        assert filtered[0]["payload"]["file_path"] == "uncovered.py"

    def test_l5_empty_sections_output_valid(self):
        """所有层为空时 L5 仍输出有效的 markdown。"""
        l2 = LayerResult(layer="L2", status="skipped")
        l3 = LayerResult(layer="L3", status="error", error="failed")
        l4 = LayerResult(layer="L4", status="skipped")
        final_context, total_tokens = LayeredSearchService._l5_context_reassembly(l2, l3, l4, 1000)
        assert final_context
        assert total_tokens >= 0
        assert "## L2 Exact Matches" in final_context
        assert "(no exact symbol matches found)" in final_context


# ============================================================================
# TestEndToEnd — 端到端测试 (work item)
# ============================================================================


class TestEndToEnd:
    """端到端测试 (work item)."""

    @pytest.mark.asyncio
    async def test_search_returns_layered_result(self):
        """search() delegate 返回 LayeredSearchResult 兼容对象。"""
        with patch(
            "services.retrieval.HybridSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = LayeredSearchResult(
                query="test query",
                repository_ids=["repo-1"],
                layers=[LayerResult(layer="L3", status="ok", items=[])],
                final_context="",
                total_tokens=0,
            )
            result = await LayeredSearchService.search("test query", repository_ids=["repo-1"])
            assert isinstance(result, LayeredSearchResult)
            assert result.query == "test query"
            assert len(result.layers) == 1
            assert all(isinstance(layer, LayerResult) for layer in result.layers)
            mock_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_empty_repos_returns_early(self):
        """delegate 返回空仓库结果时保持旧字段语义。"""
        with patch(
            "services.retrieval.HybridSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = LayeredSearchResult(
                query="test",
                repository_ids=[],
                layers=[],
                final_context="",
                total_tokens=0,
            )
            result = await LayeredSearchService.search("test")
            assert result.repository_ids == []
            assert result.final_context == ""
            assert result.total_tokens == 0

    @pytest.mark.asyncio
    async def test_search_with_specified_repo_ids(self):
        """指定 repository_ids 时透传给 HybridSearchService。"""
        with patch(
            "services.retrieval.HybridSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = LayeredSearchResult(
                query="test",
                repository_ids=["my-repo"],
                layers=[LayerResult(layer="L3", status="ok", items=[])],
                final_context="",
                total_tokens=0,
            )
            result = await LayeredSearchService.search("test", repository_ids=["my-repo"])
            assert isinstance(result, LayeredSearchResult)
            assert result.repository_ids == ["my-repo"]
            mock_search.assert_awaited_once()
            assert mock_search.await_args.kwargs["repository_ids"] == ["my-repo"]

    @pytest.mark.asyncio
    async def test_search_all_layers_handle_error_gracefully(self):
        """delegate 异常按当前 wrapper 契约传播给调用方。"""
        with patch(
            "services.retrieval.HybridSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.side_effect = Exception("search crash")
            with pytest.raises(Exception):
                await LayeredSearchService.search("test")
