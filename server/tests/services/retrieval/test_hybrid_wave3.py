"""Phase wave 集成测试。"""
from __future__ import annotations
import pytest
from services.retrieval.types import HybridSearchResult, NeighborMetadata
def test_hybrid_search_result_has_cross_repo_neighbors_field -> None:
 """HybridSearchResult 新增 cross_repo_neighbors 字段（默认 ）。"""
 result = HybridSearchResult
 assert hasattr(result, "cross_repo_neighbors")
 assert result.cross_repo_neighbors ==
def test_hybrid_search_result_cross_repo_neighbors_default_empty -> None:
 """现有 callsite 构造 HybridSearchResult 不传 cross_repo_neighbors 不报错。"""
 result = HybridSearchResult(
 query="test",
 repository_ids=["repo1"],
 layers=,
 final_context="some context",
 total_tokens=100,
 )
 assert result.cross_repo_neighbors ==
def test_render_graph_context_with_cross_repo -> None:
 """_render_graph_context 渲染 Cross-Repo Neighbors 段。"""
 from services.retrieval.hybrid_search import _render_graph_context
 cr_neighbor = NeighborMetadata(
 chunk_id="abc",
 file_path="api/topic.ts",
 line_start=None,
 line_end=None,
 edge_type="API_CALLS",
 weight=1.0,
 reason="calls fetchTopic (api/topic.ts:23), via GET /topic",
 hop=3,
 )
 result = _render_graph_context(,, [cr_neighbor])
 assert "## Graph Context" in result
 assert "### Cross-Repo Neighbors (API-Calls)" in result
 assert "api/topic.ts" in result
 assert "API_CALLS" in result
def test_render_graph_context_no_cross_repo_no_section -> None:
 """无跨仓邻居时不渲染 Cross-Repo 段。"""
 from services.retrieval.hybrid_search import _render_graph_context
 h1 = NeighborMetadata(
 chunk_id="abc",
 file_path="src/file.py",
 line_start=1,
 line_end=10,
 edge_type="CALL",
 weight=0.8,
 reason="caller of target via direct call",
 hop=1,
 )
 result = _render_graph_context([h1],, )
 assert "### Cross-Repo Neighbors (API-Calls)" not in result
 assert "### Direct Neighbors (1-hop)" in result
def test_render_graph_context_all_empty_returns_empty -> None:
 from services.retrieval.hybrid_search import _render_graph_context
 result = _render_graph_context
 assert result == ""
def test_render_graph_context_backward_compat_no_cross_repo_arg -> None:
 """_render_graph_context(hop1, hop2) 不传 cross_repo 参数向后兼容。"""
 from services.retrieval.hybrid_search import _render_graph_context
 result = _render_graph_context
 assert result == ""
