"""NullProvider 路径行为测试 —— per Phase / / Pitfall 5。
5 条 case 覆盖 ROADMAP §Phase Success Criteria #3 一半（剩余完整 pytest
matrix 由 Phase 补全）：
1. ``test_case_1_null_provider_returns_pure_rag``：禁用配置 + 给定 repo_ids
 → final_context 仅含 ``## L3 Related Code``，**无** symbol / expansion 段。
2. ``test_case_2_null_provider_repo_ids_none_skips_repo_router``：repo_ids=None
 → NullProvider 路径不触发 RepoRouter（mock spy.called False），直接以空 repo
 列表调 search_rag，final_context 兜底空字符串。
3. ``test_case_3_null_provider_empty_results_does_not_raise``：query 命中空
 chunk → final_context="" + total_tokens=0，**不抛错**。
4. ``test_case_4_null_provider_token_overflow_triggers_trim``：max_tokens=200
 + 长 RAG 结果 → final_context 含 ``(truncated:`` 标记（trim_to_budget 触发，
 与 L3-only 路径等价）。
5. ``test_case_5_local_provider_equivalent_to_null_when_disabled``：
 ENABLE_CODEGRAPH=False 等价配置（L2/L4 mock 为空）下，LocalProvider 路径
 final_context 包含 NullProvider 路径的 L3 RAG 输出（"零漂移"补充验证）。
**Pitfall 5 关键约束 #4**：所有 case 用 ``HybridSearchService(NullProvider)``
直接调用，**禁止 patch settings.ENABLE_CODEGRAPH** —— Provider 注入是依赖注入，
开关语义集中在 ``CodeIntelConfig.ready``。
外部依赖（``services.retrieval.rag_search.search_rag`` /
``codegraph.services.repo_router.RepoRouter.route`` /
``LayeredSearchService._lN`` 私有 classmethod）走 ``unittest.mock.patch`` 局部
mock，不依赖真实 ORM / Qdrant / Embedding。目标 < 5 秒跑完 5 条。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, patch
from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import LayerSnapshot
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
# case 1：禁用配置 + 给定 repo_ids → 纯 RAG final_context
# ---------------------------------------------------------------------------
async def test_case_1_null_provider_returns_pure_rag -> None:
 """NullProvider 注入下 final_context 仅含 ``## L3 Related Code`` 段。
 断言四点：
 - 含 ``## L3 Related Code`` 标题与 chunk 内容；
 - **不**含 ``## L2 Exact Matches`` / ``## L4 Graph Context`` 标题（
 capability 守卫确保 NullProvider 路径不进入 L2 / L4 编排）；
 - ``total_tokens > 0``；
 - ``layers`` 至少含 1 条 ``layer="L3"``。
 """
 items = [
 _l3_item("src/auth/login.py", "def login(req):\n return authenticate(req)"),
 _l3_item("src/auth/session.py", "def make_session(user):\n return Session(user)"),
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
 assert "## L3 Related Code" in result.final_context
 assert "src/auth/login.py" in result.final_context
 assert "## L2 Exact Matches" not in result.final_context
 assert "## L4 Graph Context (1-hop)" not in result.final_context
 assert "## L4 Graph Context (2-hop)" not in result.final_context
 assert result.total_tokens > 0
 assert any(layer.layer == "L3" for layer in result.layers)
# ---------------------------------------------------------------------------
# case 2：repo_ids=None → 不调 RepoRouter，直接走 search_rag
# ---------------------------------------------------------------------------
async def test_case_2_null_provider_repo_ids_none_skips_repo_router -> None:
 """``repository_ids=None`` 时 NullProvider 路径直接传 ```` 给 search_rag。
 断言：
 - ``RepoRouter.route`` 调用次数 == 0（NullProvider 路径不触图谱编排，per T-）；
 - ``search_rag`` 被以 ``repo_ids=`` 调用一次；
 - 空命中时 final_context == ""。
 """
 from codegraph.services.repo_router import RepoRouter
 repo_router_spy = AsyncMock(return_value=)
 rag_search_mock = AsyncMock(return_value=_make_l3_snapshot)
 with patch.object(RepoRouter, "route", new=repo_router_spy), patch(
 "services.retrieval.hybrid_search.search_rag",
 new=rag_search_mock,
 ):
 result = await HybridSearchService(NullProvider).search(
 "fallback query",
 repository_ids=None,
 max_tokens=8000,
 top_k=30,
 )
 assert repo_router_spy.call_count == 0, (
 "NullProvider 路径不应触发 RepoRouter (per T- + case 2)"
 )
 rag_search_mock.assert_called_once
 call_kwargs = rag_search_mock.call_args.kwargs
 assert call_kwargs["repo_ids"] ==, (
 "repository_ids=None 时 NullProvider 路径应以 repo_ids= 调 search_rag"
 )
 assert result.final_context == ""
 assert result.total_tokens == 0
 assert result.repository_ids ==
# ---------------------------------------------------------------------------
# case 3：query 命中空结果 → final_context="" 不 raise
# ---------------------------------------------------------------------------
async def test_case_3_null_provider_empty_results_does_not_raise -> None:
 """空 chunk 返回时兜底 final_context="" + total_tokens=0，不抛错。"""
 empty_snapshot = _make_l3_snapshot
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=empty_snapshot),
 ):
 result = await HybridSearchService(NullProvider).search(
 "no_match_query_xyz_unique",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert result.final_context == ""
 assert result.total_tokens == 0
 assert result.repository_ids == ["repo-a"]
# ---------------------------------------------------------------------------
# case 4：max_tokens=200 → trim_to_budget 触发 (truncated: 标记
# ---------------------------------------------------------------------------
async def test_case_4_null_provider_token_overflow_triggers_trim -> None:
 """长 RAG 结果 + max_tokens=200 → final_context 含 ``(truncated:`` 标记。
 与 L3-only 路径等价：``_search_rag_only`` 调 ``trim_to_budget(l3_markdown,
 budgets["rag"])``，溢出时 token_budget 模块在文末附加 ``(truncated: ...)``。
 """
 long_block = "\n".join(
 f"line {i:03d}: synthetic chunk content for trim_to_budget overflow testing"
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
 result = await HybridSearchService(NullProvider).search(
 "GiantSeed",
 repository_ids=["repo-a"],
 max_tokens=200,
 top_k=30,
 )
 assert "(truncated:" in result.final_context, (
 "max_tokens=200 + 长 RAG 结果应触发 trim_to_budget 截断标记"
 )
 assert result.total_tokens > 0
 assert "## L3 Related Code" in result.final_context
# ---------------------------------------------------------------------------
# case 5：禁用配置下 LocalProvider == NullProvider 的 L3 RAG 输出（零漂移）
# ---------------------------------------------------------------------------
async def test_case_5_local_provider_equivalent_to_null_when_disabled -> None:
 """禁用配置（L2/L4 全空）下 LocalProvider 路径 RAG 输出与 NullProvider 等价。
 具体语义（per case 5 + hard_constraint #4 零漂移）：
 模拟 codegraph 关闭状态，让 LocalProvider 路径走完五层但 L2/L4 命中空，
 L3 走与 NullProvider 同一套 search_rag 数据。**当前 HybridSearchService
 实现下，LocalProvider 路径会额外渲染 L2/L4 stub 段（``(no exact symbol
 matches found)`` / ``(no graph expansion results)``）；NullProvider 路径只
 渲染 L3 段。** 因此 byte-equality 仅在 L3 段成立 —— 用 substring 包含断言
 捕获"L3 RAG 部分零漂移"语义：
 ``null_result.final_context in local_result.final_context``。
 Phase 灰度切换若让 LocalProvider 在 codegraph 禁用配置下也走
 ``_search_rag_only`` 同一路径，则 byte-equality 升级为全等。
 """
 from codegraph.services.layered_search import LayerResult, LayeredSearchService as _LS
 items = [
 _l3_item("src/equiv/foo.py", "def foo:\n return 'shared'", score=0.81),
 _l3_item("src/equiv/bar.py", "def bar:\n return 'shared'", score=0.74),
 ]
 null_snapshot = _make_l3_snapshot(items)
 with patch(
 "services.retrieval.hybrid_search.search_rag",
 new=AsyncMock(return_value=null_snapshot),
 ):
 null_result = await HybridSearchService(NullProvider).search(
 "equiv probe",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 fake_l1 = LayerResult(layer="L1", status="ok", result_count=1, items=)
 empty_l2 = LayerResult(layer="L2", status="ok", result_count=0, items=)
 l3_layer = LayerResult(layer="L3", status="ok", result_count=len(items), items=items)
 empty_l4 = LayerResult(layer="L4", status="ok", result_count=0, items=)
 async def _fake_l1(*_args: Any, **_kwargs: Any) -> tuple[LayerResult, list[str]]:
 return fake_l1, ["repo-a"]
 async def _fake_l2(*_args: Any, **_kwargs: Any) -> LayerResult:
 return empty_l2
 async def _fake_l3(*_args: Any, **_kwargs: Any) -> LayerResult:
 return l3_layer
 async def _fake_l4(*_args: Any, **_kwargs: Any) -> LayerResult:
 return empty_l4
 with patch.object(_LS, "_l1_repo_routing", new=_fake_l1), patch.object(
 _LS, "_l2_symbol_lookup", new=_fake_l2,
 ), patch.object(
 _LS, "_l3_hybrid_search", new=_fake_l3,
 ), patch.object(
 _LS, "_l4_graph_expansion", new=_fake_l4,
 ):
 local_result = await HybridSearchService(LocalProvider).search(
 "equiv probe",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert null_result.final_context, "NullProvider 路径在 case 5 应有非空 final_context"
 assert null_result.final_context in local_result.final_context, (
 "禁用配置下 LocalProvider final_context 必须完整包含 NullProvider 的 L3 输出 "
 "(零漂移补充验证 per case 5)"
 )
 assert "## L3 Related Code" in local_result.final_context
 assert "## L2 Exact Matches" in local_result.final_context, (
 "LocalProvider 路径即使 L2 空也会渲染 stub 段（实现现状，记入 case 5 文档）"
 )
