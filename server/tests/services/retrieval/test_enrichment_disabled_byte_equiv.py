"""ENABLE_GRAPHRAG_ENRICHMENT=False 路径 byte-equivalent 集成测试 ——
per Phase CONTEXT / / Plan task 2。
CONTEXT 字面承诺:
 ENABLE_GRAPHRAG_ENRICHMENT=False → HybridSearchService **强制** rag_only 路径
 （即使 provider 是 GraphCapableProvider，也 byte-equiv Phase 路径）
本套件锁定该不变量：在 ``override_settings(ENABLE_GRAPHRAG_ENRICHMENT=False)``
环境下，``LocalProvider`` (GraphCapableProvider) 与 ``NullProvider``
(BaseCodeProvider) 经 ``HybridSearchService.search(...)`` 产出的
``final_context`` **byte-for-byte** 相等——含 markdown 缩进、trailing newline
统统一致；同时 result 类型同样降级为 ``RagSearchResult``（不带
``graph_context`` / ``hop1_neighbors`` / ``hop2_neighbors`` 三字段）。
**守门对照组**（Test 4）：默认 ``settings.ENABLE_GRAPHRAG_ENRICHMENT=True``
下 LocalProvider 仍走 ``_search_graph_capable`` 路径返
``HybridSearchResult``，证明 Plan 仅锁灰度路径而非破坏默认路径。
mock 策略与 ``test_null_provider_paths.py`` 一致：patch
``services.retrieval.hybrid_search.search_rag`` 返固定 LayerSnapshot，
不触 Qdrant / ORM；LocalProvider.lookup_symbols 落在 ``_search_rag_only``
分支永不调用，故零 DB 依赖。Test 4 走 ``_search_graph_capable`` 时
asyncio.gather(return_exceptions=True) 把 lookup_symbols 的
"Database access not allowed" 降级为 ``symbol_results=``，无需 db 标记。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, patch
from django.test.utils import override_settings
from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import HybridSearchResult, LayerSnapshot, RagSearchResult
def _l3_item(file_path: str, content: str, score: float = 0.85) -> dict[str, Any]:
 """复用 ``test_null_provider_paths._l3_item`` 同形 payload（语义等价 / 字段对齐）。"""
 return {
 "score": score,
 "payload": {
 "file_path": file_path,
 "content": content,
 "language": "python",
 "chunk_index": 0,
 "start_line": 1,
 "end_line": 20,
 "repository_id": "repo-a",
 },
 }
def _make_l3_snapshot(items: list[dict[str, Any]]) -> LayerSnapshot:
 """``search_rag`` 返回值替身：固定 L3 LayerSnapshot。"""
 return LayerSnapshot(
 layer="L3", status="ok", result_count=len(items), items=items,
 )
# ---------------------------------------------------------------------------
# Test 1：单条 L3 命中 + ENABLE_GRAPHRAG_ENRICHMENT=False → byte-equiv
# ---------------------------------------------------------------------------
@override_settings(ENABLE_GRAPHRAG_ENRICHMENT=False)
async def test_byte_equiv_simple_l3_match -> None:
 """单条 L3 命中场景下 LocalProvider final_context **byte-for-byte** 相等 NullProvider。
 断言：
 - ``local_result.final_context == null_result.final_context``（含 markdown
 格式 / 换行 / 空白完全一致）
 - 双方均返 ``RagSearchResult``（settings False → 强制 rag_only 路径）
 - ``total_tokens`` 一致（来自相同 final_context 的 estimate_tokens）
 """
 items = [
 _l3_item("src/auth/login.py", "def login(req):\n return authenticate(req)"),
 ]
 snapshot = _make_l3_snapshot(items)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=snapshot),
 ):
 local_result = await HybridSearchService(LocalProvider).search(
 "user login",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 null_result = await HybridSearchService(NullProvider).search(
 "user login",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert local_result.final_context == null_result.final_context, (
 "ENABLE_GRAPHRAG_ENRICHMENT=False 下 LocalProvider/NullProvider final_context "
 "必须 byte-for-byte 相等（per CONTEXT ）"
 )
 assert isinstance(local_result, RagSearchResult)
 assert isinstance(null_result, RagSearchResult)
 assert not isinstance(local_result, HybridSearchResult)
 assert local_result.total_tokens == null_result.total_tokens
 assert "## L3 Related Code" in local_result.final_context
 assert "src/auth/login.py" in local_result.final_context
# ---------------------------------------------------------------------------
# Test 2：空 L3 → 双 provider final_context == "" byte-equiv
# ---------------------------------------------------------------------------
@override_settings(ENABLE_GRAPHRAG_ENRICHMENT=False)
async def test_byte_equiv_empty_l3_returns_empty_context -> None:
 """空 L3 集合下双 provider final_context 同为空字符串（不写空 markdown 段）。"""
 snapshot = _make_l3_snapshot
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=snapshot),
 ):
 local_result = await HybridSearchService(LocalProvider).search(
 "no_match_xyz",
 repository_ids=["repo-a"],
 )
 null_result = await HybridSearchService(NullProvider).search(
 "no_match_xyz",
 repository_ids=["repo-a"],
 )
 assert local_result.final_context == ""
 assert null_result.final_context == ""
 assert local_result.final_context == null_result.final_context
 assert local_result.total_tokens == 0 == null_result.total_tokens
# ---------------------------------------------------------------------------
# Test 3：max_tokens=200 + 长 L3 内容 → trim 路径 byte-equiv
# ---------------------------------------------------------------------------
@override_settings(ENABLE_GRAPHRAG_ENRICHMENT=False)
async def test_byte_equiv_max_tokens_trim_consistent -> None:
 """max_tokens=200 + 长 L3 内容下 trim_to_budget 切割结果 byte-equiv。
 rag_only 路径调 ``split_budget(200, ratios={"rag": 1.0})`` →
 ``trim_to_budget(l3_markdown, 200)`` —— 双 provider 共享该路径，输出
 须含 ``(truncated:`` 标记且字节级相等。
 """
 long_block = "\n".join(
 f"line {i:03d}: synthetic chunk for trim_to_budget overflow byte-equiv testing"
 for i in range(60)
 )
 items = [
 _l3_item(f"src/giant/chunk_{i:02d}.py", long_block, score=0.95 - i * 0.01)
 for i in range(20)
 ]
 snapshot = _make_l3_snapshot(items)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=snapshot),
 ):
 local_result = await HybridSearchService(LocalProvider).search(
 "GiantSeed",
 repository_ids=["repo-a"],
 max_tokens=200,
 top_k=30,
 )
 null_result = await HybridSearchService(NullProvider).search(
 "GiantSeed",
 repository_ids=["repo-a"],
 max_tokens=200,
 top_k=30,
 )
 assert local_result.final_context == null_result.final_context, (
 "max_tokens=200 trim 路径在双 provider 间必须 byte-equiv"
 )
 assert "(truncated:" in local_result.final_context
 assert local_result.total_tokens == null_result.total_tokens
# ---------------------------------------------------------------------------
# Test 4：守门对照组 —— 默认 settings True 时 LocalProvider 走 graph_capable 路径
# ---------------------------------------------------------------------------
@override_settings(ENABLE_GRAPHRAG_ENRICHMENT=True)
async def test_settings_true_local_provider_returns_graph_result_type -> None:
 """默认 settings True 下 LocalProvider 路径仍返 ``HybridSearchResult``。
 本对照组守门 Phase 灰度开关**不影响默认路径**：仅当 settings False
 时才强制 rag_only；True 时 LocalProvider (GraphCapableProvider) 走完整
 graph_capable 编排器，返带 graph_context/hop1/hop2 三字段的
 HybridSearchResult。
 Note: items 不含 ``related_chunks`` payload key → hop1/hop2 邻居均空 →
 ``graph_context == ""``，但**返回类型仍是 HybridSearchResult**（守门
 断言点）；与 Phase ``test_case_5_local_provider_equivalent_to_null``
 场景相同。
 DB 依赖：LocalProvider.lookup_symbols 真实代码路径会触
 "Database access not allowed"，asyncio.gather(return_exceptions=True)
 把异常降级为 symbol_results=——故本测试不需要 ``db`` fixture marker
 （与 Phase test_case_5 同构）。
 """
 items = [
 _l3_item("src/sentinel/probe.py", "def probe:\n return 'check'", score=0.7),
 ]
 snapshot = _make_l3_snapshot(items)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=snapshot),
 ):
 local_result = await HybridSearchService(LocalProvider).search(
 "sentinel probe",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(local_result, HybridSearchResult), (
 "settings True + LocalProvider 必须返 HybridSearchResult（graph_capable 路径）"
 )
 assert hasattr(local_result, "graph_context")
 assert hasattr(local_result, "hop1_neighbors")
 assert hasattr(local_result, "hop2_neighbors")
 # 无 related_chunks payload → 邻居空 + graph_context 空，但类型不降级。
 assert local_result.graph_context == ""
 assert local_result.hop1_neighbors ==
 assert local_result.hop2_neighbors ==
 assert "## L3 Related Code" in local_result.final_context
