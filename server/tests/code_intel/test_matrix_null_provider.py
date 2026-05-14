"""NullProvider 关键 path 矩阵测试 —— per Phase Plan / 。
补全 ROADMAP §Phase "≥10 ``-k null_provider`` 测试" 的 code_intel 半边。
Phase 既有 5 条 ``test_null_provider_paths.py`` + Phase / 255 衍生 8 条
分布于 retrieval / agents 套件，本 plan 在 ``tests/code_intel/`` 落 4 条 Provider
能力契约层面（不再过 HybridSearchService 编排）测试，与 ``HybridSearchService``
路径测试形成 "下层 Provider 行为 → 上层编排行为" 的双层覆盖。
四条聚焦：
1. ``test_null_provider_search_returns_rag_only_result_type`` —— NullProvider
 注入 ``HybridSearchService`` 走 ``_search_rag_only`` 路径，``search`` 返回
 ``RagSearchResult``（非 ``HybridSearchResult``），且 ``getattr(result,
 "graph_context", "") == ""`` / ``getattr(result, "hop1_neighbors", ) == ``
 验证 Plan must_have "graph_context == '' + hop1_neighbors == + final_context
 非空（rag_only 路径）"。
2. ``test_null_provider_search_empty_repo_ids_no_crash`` —— ``repository_ids=``
 不抛错；``search_rag`` 仍被以 ``repo_ids=`` 调一次。
3. ``test_null_provider_health_check_returns_true`` —— ``NullProvider.health_check``
 始终 ``True``（per Phase，本测试守 NullProvider 能力契约 +
 ``BaseCodeProvider`` Protocol 兼容）。
4. ``test_null_provider_lookup_symbols_raises_not_implemented`` —— 上游
 误绕过 capability 守卫直接 ``await NullProvider.lookup_symbols(...)`` 必须
 抛 ``NotImplementedError``（per Phase / Pitfall 5 hard_constraint
 #5：NullProvider 路径不能跨界拿到 GraphCapable 数据）。
mock 模式沿用 ``tests/services/retrieval/test_null_provider_paths.py``：仅 patch
``services.retrieval.hybrid_search.search_rag`` 模块级 import；不依赖真实
ORM / Qdrant / Embedding。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import HybridSearchResult, LayerSnapshot, RagSearchResult
# ---------------------------------------------------------------------------
# Helpers（与 test_null_provider_paths.py 同模式，复制保单文件可读性）
# ---------------------------------------------------------------------------
def _l3_item(file_path: str, content: str, score: float = 0.85) -> dict[str, Any]:
 """构造 L3 命中 item，与 ``_format_l3_section`` 期望的 payload key 对齐。"""
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
# Test 1: 返回类型 + graph_context/hop1_neighbors 兜底
# ---------------------------------------------------------------------------
async def test_null_provider_search_returns_rag_only_result_type -> None:
 """NullProvider 注入 → ``search`` 返回 ``RagSearchResult``（不是 HybridSearchResult）。
 断言三点（per plan must_have "graph_context == '' + hop1_neighbors == +
 final_context 非空（rag_only 路径）"）：
 - 返回值 ``isinstance(result, RagSearchResult)`` 且 ``not isinstance(result,
 HybridSearchResult)``（NullProvider 路径走 ``_search_rag_only``）；
 - ``getattr(result, "graph_context", "") == ""``（RagSearchResult 无此字段，
 getattr 兜底空串）；
 - ``getattr(result, "hop1_neighbors", ) == ``（同上）；
 - ``result.final_context`` 含 ``## L3 Related Code`` 标题（非空）。
 """
 items = [
 _l3_item(
 "src/auth/login.py", "def login(req):\n return authenticate(req)"
 ),
 ]
 snapshot = _make_l3_snapshot(items)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=snapshot),
 ):
 result = await HybridSearchService(NullProvider).search(
 "user login flow",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert isinstance(result, RagSearchResult), (
 "NullProvider 路径必须返 RagSearchResult（_search_rag_only 路径）"
 )
 assert not isinstance(result, HybridSearchResult), (
 "RagSearchResult 与 HybridSearchResult 不存在继承关系（per Phase "
 "Plan -b：字段同名同序而非继承）；NullProvider 路径不能返 "
 "HybridSearchResult，否则 callsite 类型 narrow 失败"
 )
 assert getattr(result, "graph_context", "") == "", (
 "RagSearchResult 无 graph_context 字段；getattr 兜底空串语义稳定"
 )
 assert getattr(result, "hop1_neighbors", ) ==
 assert "## L3 Related Code" in result.final_context, (
 "rag_only 路径 final_context 仍非空（L3 RAG section 已渲染）"
 )
# ---------------------------------------------------------------------------
# Test 2: repository_ids= 不抛错
# ---------------------------------------------------------------------------
async def test_null_provider_search_empty_repo_ids_no_crash -> None:
 """``repository_ids=`` 不抛错；``search_rag`` 仍以 ``repo_ids=`` 调一次。
 ``HybridSearchService(NullProvider)`` 走 ``_search_rag_only`` 路径，传
 ``repo_ids=`` 直通 ``search_rag``——保兼容空仓库范围场景（CONTEXT.md
 与 ``test_case_2_null_provider_repo_ids_none_skips_repo_router`` 一致语义）。
 """
 rag_search_mock = AsyncMock(return_value=_make_l3_snapshot)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=rag_search_mock,
 ):
 result = await HybridSearchService(NullProvider).search(
 "empty repo probe",
 repository_ids=,
 max_tokens=8000,
 top_k=30,
 )
 rag_search_mock.assert_called_once
 call_kwargs = rag_search_mock.call_args.kwargs
 assert call_kwargs["repo_ids"] ==, (
 "repository_ids= 时 NullProvider 路径应原样以 repo_ids= 调 search_rag"
 )
 assert result.final_context == ""
 assert result.total_tokens == 0
 assert result.repository_ids ==
# ---------------------------------------------------------------------------
# Test 3: NullProvider.health_check 行为契约
# ---------------------------------------------------------------------------
async def test_null_provider_health_check_returns_true -> None:
 """``NullProvider.health_check`` 始终返回 True（per Phase）。
 NullProvider 设计上"无能力但始终在线"——后端不可用降级到本路径时，仍要让
 探活端点返 True 表示本进程是 healthy 的；区别于真后端故障的语义。
 """
 provider = NullProvider
 result = await provider.health_check
 assert result is True
 # capabilities 必须是空集合（per protocols.py BaseCodeProvider Protocol）
 assert provider.capabilities == frozenset, (
 "NullProvider 必须声明 capabilities = frozenset（per Phase "
 "+ Pitfall 5 hard_constraint #5：NullProvider 不能声明任何 capability）"
 )
# ---------------------------------------------------------------------------
# Test 4: lookup_symbols 误绕过 → NotImplementedError 含 capability 名
# ---------------------------------------------------------------------------
async def test_null_provider_lookup_symbols_raises_not_implemented -> None:
 """上游误绕过 capability 守卫直接 ``await NullProvider.lookup_symbols(...)``
 必须抛 ``NotImplementedError`` 且错误信息含 "lookup_symbols"（per ）。
 NullProvider 不在类上显式定义 ``lookup_symbols`` → ``isinstance(NullProvider,
 SymbolCapableProvider)`` False；但 ``__getattr__`` 兜底让属性可访问并返回
 一个抛 ``NotImplementedError`` 的协程，错误信息带 capability 名让 debug 容易。
 本测试是 T- Tampering 缓解的核心断言：守住 NullProvider 即使被
 误调用也必须 fail loud，不能静默返回空数据让上游误以为图谱可用但实际为空。
 """
 provider = NullProvider
 with pytest.raises(NotImplementedError, match="lookup_symbols"):
 await provider.lookup_symbols( # type: ignore[attr-defined]
 ["foo"], repository_ids=["repo-a"]
 )
 # expand_graph 同处理（Phase __getattr__ 兜底 capability 名集合）
 with pytest.raises(NotImplementedError, match="expand_graph"):
 await provider.expand_graph( # type: ignore[attr-defined]
 [{"symbol_id": "s1"}], max_hops=2
 )
