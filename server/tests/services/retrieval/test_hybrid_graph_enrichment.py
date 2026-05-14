"""HybridSearchService 端到端图谱 enrichment 测试（per Phase Plan Task 2）。
8 条端到端断言：
1. ``test_hop1_neighbors_extracted_from_payload`` —— mock rag_items 含
 payload.related_chunks → result.hop1_neighbors 长度 > 0 + chunk_id 与
 payload 一致 + edge_type/weight 来自 payload。
2. ``test_hop2_orm_dedup_against_hop1_and_rag`` —— 构造 ChunkEdge 让 hop2
 target 一部分与 hop1 / rag 重合 → result.hop2_neighbors 仅含独立 target。
3. ``test_hop2_skipped_when_enable_graph_enrichment_false`` —— search(
 enable_graph_enrichment=False) → 走 _search_rag_only 路径 + hop2_neighbors
 字段不存在（RagSearchResult 类型）+ 不查 ChunkEdge ORM。
4. ``test_budget_allocation_default_8000`` —— max_tokens=8000 → graph_section
 token ≤ HybridBudget(8000).allocate['graph'] = 2880。
5. ``test_budget_settings_override_07`` —— override settings.GRAPHRAG_BUDGET_RATIO=0.7
 → HybridBudget.from_settings rag 比例提升到 0.7、graph 降到 0.3。
6. ``test_graph_context_markdown_format`` —— final_context 含
 ``## Graph Context`` / ``### Direct Neighbors (1-hop)`` /
 ``### Indirect Neighbors (2-hop)`` 三段头 + 邻居行格式。
7. ``test_null_provider_path_unchanged`` —— NullProvider 调 search → 返回
 RagSearchResult 类型（无 hop1/hop2 字段）且不含 ``## Graph Context`` 段。
8. ``test_no_settings_enable_codegraph_in_module`` —— rg grep gate：
 ``services/retrieval/hybrid_search.py`` 过滤注释行后不出现 settings.ENABLE_CODEGRAPH。
测试基建：
- ``ChunkRegistry`` / ``ChunkEdge`` 用 ``pytest.mark.django_db(transaction=True)`` +
 ``acreate`` / ``abulk_create``（async ORM，与 test_hop2_expander.py 同模式）。
- ``search_rag`` 用 ``unittest.mock.patch + AsyncMock`` 注入 LayerSnapshot 替身
 含 payload.related_chunks（直接绕过 embedding / Qdrant 真实路径）。
- ``LocalProvider.lookup_symbols`` 用 ``AsyncMock(return_value=)`` 注入避免
 Symbol ORM 真实查询（本测试只验图谱 enrichment 链路）。
"""
from __future__ import annotations
import pathlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
from django.test.utils import override_settings
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.budget import HybridBudget
from services.retrieval.token_budget import estimate_tokens
from services.retrieval.types import (
 HybridSearchResult,
 LayerSnapshot,
 RagSearchResult,
)
# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _rag_item(
 chunk_id: uuid.UUID,
 file_path: str,
 content: str,
 *,
 related_chunks: list[Any] | None = None,
 score: float = 0.85,
) -> dict[str, Any]:
 """构造 search_rag items[i] minimum shape，与 hop1_reader 期望一致。"""
 payload: dict[str, Any] = {
 "file_path": file_path,
 "content": content,
 "chunk_index": 0,
 "language": "python",
 }
 if related_chunks is not None:
 payload["related_chunks"] = related_chunks
 return {
 "id": str(chunk_id),
 "score": score,
 "payload": payload,
 "repository_id": "repo-a",
 }
def _snapshot(items: list[dict[str, Any]]) -> LayerSnapshot:
 return LayerSnapshot(
 layer="L3", status="ok", result_count=len(items), items=items,
 )
# ---------------------------------------------------------------------------
# case 1：hop1 邻居从 payload.related_chunks 提取（与 ChunkRegistry metadata 合并）
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_hop1_neighbors_extracted_from_payload(repository) -> None:
 """rag_items[*].payload.related_chunks → result.hop1_neighbors。
 断言：
 - hop1_neighbors 长度 > 0；
 - chunk_id / edge_type / weight 来自 payload；
 - file_path / line_start 来自 ChunkRegistry（单次 in_bulk）；
 - hop == 1。
 """
 src_id = uuid.uuid4
 h1_a = uuid.uuid4
 h1_b = uuid.uuid4
 for cid, fp in ((h1_a, "src/foo.py"), (h1_b, "src/bar.py")):
 await ChunkRegistry.objects.acreate(
 chunk_id=cid,
 content_hash=cid.hex,
 repository=repository,
 file_path=fp,
 chunk_index=0,
 line_start=10,
 line_end=20,
 )
 rag_items = [
 _rag_item(
 src_id,
 "src/source.py",
 "def source: foo; bar",
 related_chunks=[
 [str(h1_a), "CALL", 0.9],
 [str(h1_b), "IMPORT", 0.6],
 ],
 ),
 ]
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=_snapshot(rag_items)),
 ), patch.object(
 LocalProvider, "lookup_symbols", new=AsyncMock(return_value=),
 ):
 result = await HybridSearchService(LocalProvider).search(
 "source flow",
 repository_ids=[str(repository.id)],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(result, HybridSearchResult)
 assert len(result.hop1_neighbors) == 2
 by_chunk = {n.chunk_id: n for n in result.hop1_neighbors}
 assert str(h1_a) in by_chunk
 assert str(h1_b) in by_chunk
 assert by_chunk[str(h1_a)].edge_type == "CALL"
 assert by_chunk[str(h1_a)].weight == pytest.approx(0.9)
 assert by_chunk[str(h1_a)].file_path == "src/foo.py"
 assert by_chunk[str(h1_a)].line_start == 10
 assert all(n.hop == 1 for n in result.hop1_neighbors)
# ---------------------------------------------------------------------------
# case 2：hop2 ChunkEdge ORM 扩散 + 三重去重 vs hop1 / rag
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_hop2_orm_dedup_against_hop1_and_rag(repository) -> None:
 """hop2 target ∈ hop1 ∪ rag → 过滤；独立 target → 保留 + hop=2。"""
 rag_src = uuid.uuid4 # rag 召回 chunk（也是 hop2 reject 集成员）
 h1_a = uuid.uuid4 # hop1 邻居（hop2 reject 集成员）
 h1_b = uuid.uuid4 # hop1 邻居（也是 hop2 source）
 h2_independent = uuid.uuid4 # 独立 hop2 target
 for cid, fp in (
 (rag_src, "src/rag.py"),
 (h1_a, "src/h1a.py"),
 (h1_b, "src/h1b.py"),
 (h2_independent, "src/h2_indep.py"),
 ):
 await ChunkRegistry.objects.acreate(
 chunk_id=cid,
 content_hash=cid.hex,
 repository=repository,
 file_path=fp,
 chunk_index=0,
 line_start=1,
 line_end=5,
 )
 # hop1_b → h1_a (target ∈ hop1，过滤)
 # hop1_b → rag_src (target ∈ rag，过滤)
 # hop1_b → h2_independent (保留)
 await ChunkEdge.objects.abulk_create([
 ChunkEdge(
 source_chunk_id=h1_b,
 target_chunk_id=h1_a,
 edge_type=EdgeType.CALL,
 weight=0.9,
 repository=repository,
 ),
 ChunkEdge(
 source_chunk_id=h1_b,
 target_chunk_id=rag_src,
 edge_type=EdgeType.IMPORT,
 weight=0.8,
 repository=repository,
 ),
 ChunkEdge(
 source_chunk_id=h1_b,
 target_chunk_id=h2_independent,
 edge_type=EdgeType.CALL,
 weight=0.7,
 repository=repository,
 ),
 ])
 rag_items = [
 _rag_item(
 rag_src,
 "src/rag.py",
 "rag content",
 related_chunks=[
 [str(h1_a), "CALL", 0.9],
 [str(h1_b), "CALL", 0.8],
 ],
 ),
 ]
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=_snapshot(rag_items)),
 ), patch.object(
 LocalProvider, "lookup_symbols", new=AsyncMock(return_value=),
 ):
 result = await HybridSearchService(LocalProvider).search(
 "dedup probe",
 repository_ids=[str(repository.id)],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(result, HybridSearchResult)
 hop2_ids = {n.chunk_id for n in result.hop2_neighbors}
 assert str(h2_independent) in hop2_ids
 assert str(h1_a) not in hop2_ids, "hop2 target ∈ hop1 应被三重去重过滤"
 assert str(rag_src) not in hop2_ids, "hop2 target ∈ rag 应被三重去重过滤"
 assert all(n.hop == 2 for n in result.hop2_neighbors)
# ---------------------------------------------------------------------------
# case 3：enable_graph_enrichment=False → 走 _search_rag_only，不查 ChunkEdge
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_hop2_skipped_when_enable_graph_enrichment_false(repository) -> None:
 """``enable_graph_enrichment=False`` 短路到 _search_rag_only。
 断言：
 - 返回 RagSearchResult（非 HybridSearchResult，无 hop1/hop2/graph_context 字段）；
 - ChunkEdge.objects 未被查询（mock spy call_count == 0）。
 """
 src_id = uuid.uuid4
 h1 = uuid.uuid4
 await ChunkRegistry.objects.acreate(
 chunk_id=h1,
 content_hash=h1.hex,
 repository=repository,
 file_path="src/foo.py",
 chunk_index=0,
 line_start=1,
 line_end=5,
 )
 rag_items = [
 _rag_item(
 src_id,
 "src/source.py",
 "def source: foo",
 related_chunks=[[str(h1), "CALL", 0.9]],
 ),
 ]
 edge_filter_spy = AsyncMock(wraps=ChunkEdge.objects.filter)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=_snapshot(rag_items)),
 ), patch.object(
 LocalProvider, "lookup_symbols", new=AsyncMock(return_value=),
 ), patch.object(
 ChunkEdge.objects, "filter", new=edge_filter_spy,
 ):
 result = await HybridSearchService(LocalProvider).search(
 "shortcircuit probe",
 repository_ids=[str(repository.id)],
 max_tokens=8000,
 top_k=30,
 enable_graph_enrichment=False,
 )
 assert isinstance(result, RagSearchResult)
 assert not isinstance(result, HybridSearchResult), (
 "enable_graph_enrichment=False 应短路到 _search_rag_only 返回 RagSearchResult"
 )
 assert edge_filter_spy.call_count == 0, (
 "_search_rag_only 路径不应触发 ChunkEdge ORM 查询"
 )
# ---------------------------------------------------------------------------
# case 4：默认 max_tokens=8000 budget allocation（rag 4320 / graph 2880）
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_budget_allocation_default_8000(repository) -> None:
 """默认 8000 max_tokens → graph_section token ≤ 2880（HybridBudget 60/40）。
 rag_section 上限受 ``_format_l3_section`` 输入大小限制（mock items 较小所以
 实际 < 4320），仅断言 graph_section 不越界。
 """
 expected_graph_budget = HybridBudget.allocate(8000)["graph"]
 assert expected_graph_budget == 2880 # sanity: HybridBudget(0.6, 0.4) × 0.9
 # 制造一批 hop1 邻居让 graph_context 有内容
 src = uuid.uuid4
 h1_ids = [uuid.uuid4 for _ in range(8)]
 for cid in h1_ids:
 await ChunkRegistry.objects.acreate(
 chunk_id=cid,
 content_hash=cid.hex,
 repository=repository,
 file_path=f"src/h1/{cid.hex[:8]}.py",
 chunk_index=0,
 line_start=1,
 line_end=5,
 )
 rag_items = [
 _rag_item(
 src,
 "src/source.py",
 "content",
 related_chunks=[[str(cid), "CALL", 0.5 + i * 0.05] for i, cid in enumerate(h1_ids)],
 ),
 ]
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=_snapshot(rag_items)),
 ), patch.object(
 LocalProvider, "lookup_symbols", new=AsyncMock(return_value=),
 ):
 result = await HybridSearchService(LocalProvider).search(
 "budget probe",
 repository_ids=[str(repository.id)],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(result, HybridSearchResult)
 graph_tokens = estimate_tokens(result.graph_context)
 assert graph_tokens <= expected_graph_budget, (
 f"graph_section tokens={graph_tokens} 超出预算 {expected_graph_budget}"
 )
# ---------------------------------------------------------------------------
# case 5：settings.GRAPHRAG_BUDGET_RATIO=0.7 → rag 比例提升
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_budget_settings_override_07(repository) -> None:
 """settings.GRAPHRAG_BUDGET_RATIO=0.7 → HybridBudget.from_settings 比例提升。
 用 ``override_settings`` 触发 ``from_settings`` 走 0.7 分支；断言两次
 budget 分配数值符合 60/40 vs 70/30 差。
 """
 default_budgets = HybridBudget.from_settings.allocate(8000)
 assert default_budgets["rag"] == 4320 # baseline
 with override_settings(GRAPHRAG_BUDGET_RATIO=0.7):
 custom = HybridBudget.from_settings.allocate(8000)
 assert custom["rag"] > default_budgets["rag"], (
 f"GRAPHRAG_BUDGET_RATIO=0.7 应让 rag 预算 > 0.6 基线: {custom['rag']} vs {default_budgets['rag']}"
 )
 assert custom["graph"] < default_budgets["graph"]
 # math: 8000 × 0.9 × 0.7 = 5040
 assert custom["rag"] == 5040
 assert custom["graph"] == 2160
# ---------------------------------------------------------------------------
# case 6：graph_context markdown 格式三段头 + 邻居行
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_graph_context_markdown_format(repository) -> None:
 """final_context 含 ``## Graph Context`` 等三段头 + 邻居行 markdown 格式。"""
 src_id = uuid.uuid4
 h1 = uuid.uuid4
 h2 = uuid.uuid4
 # hop1: src → h1; hop2: h1 → h2
 for cid, fp in ((h1, "src/h1.py"), (h2, "src/h2.py")):
 await ChunkRegistry.objects.acreate(
 chunk_id=cid,
 content_hash=cid.hex,
 repository=repository,
 file_path=fp,
 chunk_index=0,
 line_start=42,
 line_end=58,
 )
 await ChunkEdge.objects.acreate(
 source_chunk_id=h1,
 target_chunk_id=h2,
 edge_type=EdgeType.IMPORT,
 weight=0.55,
 repository=repository,
 )
 rag_items = [
 _rag_item(
 src_id,
 "src/source.py",
 "def source: h1",
 related_chunks=[[str(h1), "CALL", 0.85]],
 ),
 ]
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=_snapshot(rag_items)),
 ), patch.object(
 LocalProvider, "lookup_symbols", new=AsyncMock(return_value=),
 ):
 result = await HybridSearchService(LocalProvider).search(
 "markdown probe",
 repository_ids=[str(repository.id)],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(result, HybridSearchResult)
 fc = result.final_context
 assert "## Graph Context" in fc
 assert "### Direct Neighbors (1-hop)" in fc
 assert "### Indirect Neighbors (2-hop)" in fc
 # 邻居行格式：- `{file_path}:{line}` ({edge_type}, w={weight:.2f}): {reason}
 assert "`src/h1.py:42` (CALL, w=0.85)" in fc, (
 f"邻居行格式错误: {fc!r}"
 )
 assert "`src/h2.py:42` (IMPORT, w=0.55)" in fc
# ---------------------------------------------------------------------------
# case 7：NullProvider 路径 byte-equivalence 保 Phase 不动
# ---------------------------------------------------------------------------
async def test_null_provider_path_unchanged -> None:
 """NullProvider 调 search → 返回 RagSearchResult（非 HybridSearchResult）
 + 不含 ``## Graph Context`` 段；与 Phase _search_rag_only 完全一致。
 """
 rag_items = [
 _rag_item(
 uuid.uuid4,
 "src/foo.py",
 "def foo: pass",
 related_chunks=[[str(uuid.uuid4), "CALL", 0.9]], # 即使 payload 有也不应被读
 ),
 ]
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=_snapshot(rag_items)),
 ):
 result = await HybridSearchService(NullProvider).search(
 "null probe",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(result, RagSearchResult)
 assert not isinstance(result, HybridSearchResult), (
 "NullProvider 路径必须返回 RagSearchResult（不进图谱编排）"
 )
 assert "## L3 Related Code" in result.final_context
 assert "## Graph Context" not in result.final_context
 assert "### Direct Neighbors" not in result.final_context
# ---------------------------------------------------------------------------
# case 8：grep gate 不 regress（settings.ENABLE_CODEGRAPH 0 命中）
# ---------------------------------------------------------------------------
def test_no_settings_enable_codegraph_in_module -> None:
 """``services/retrieval/hybrid_search.py`` 源码（过滤 ``#`` 注释行）必须不
 出现 ``settings.ENABLE_CODEGRAPH`` 字面值（per Pitfall 5 不 regress）。
 与 Plan grep gate 同 idiom；本测试做端到端复读，防 Plan 重写时不慎
 引入 settings 读取。
 """
 server_dir = pathlib.Path(__file__).resolve.parents[3]
 target = server_dir / "services" / "retrieval" / "hybrid_search.py"
 assert target.exists, f"target file missing: {target}"
 text = target.read_text(encoding="utf-8")
 non_comment_lines = [
 line for line in text.splitlines if not line.lstrip.startswith("#")
 ]
 non_comment = "\n".join(non_comment_lines)
 assert "settings.ENABLE_CODEGRAPH" not in non_comment, (
 "Pitfall 5 violation: hybrid_search.py 不应读 settings.ENABLE_CODEGRAPH; "
 "图谱启停通过 Provider 注入 + enable_graph_enrichment 参数控制"
 )
