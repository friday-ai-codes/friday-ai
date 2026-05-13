"""NullProvider 路径行为测试 —— per Phase / / Pitfall 5。
5 条用例覆盖 ENABLE_CODEGRAPH=False 配置下 `HybridSearchService(NullProvider)`
的核心路径行为（Phase success criteria #3 的前半部分；Phase 补完完整
pytest matrix）：
1. ``test_case_1_null_provider_returns_pure_rag`` —— 给定 repo_ids 时 NullProvider
 路径返回纯 RAG `final_context`，markdown 仅含 `## L3 Related Code`，
 不含 `## L2 Exact Matches` / `## L4 Graph Context` 标题。
2. ``test_case_2_null_provider_repo_ids_none_skips_repo_router`` —— `repository_ids=None`
 时 NullProvider 路径**不**调 `RepoRouter.route`（spy 计数 == 0），
 兜底返回空 `final_context`。
3. ``test_case_3_null_provider_empty_results_returns_empty_context`` —— query 命中
 空 L3 时返回 `final_context=""` / `total_tokens==0`，不抛错。
4. ``test_case_4_null_provider_token_overflow_triggers_trim`` —— `max_tokens=200`
 强制走 `trim_to_budget`，输出含 `(truncated:` 标记，且 `total_tokens <= 200`。
5. ``test_case_5_local_vs_null_equivalent_when_disabled`` —— 在禁用配置等价语义下
 （未知路由 query + `repository_ids=None`），LocalProvider 与 NullProvider
 两条路径产出的 `final_context` 字节一致（"零漂移"补充验证）。
依赖注入硬约束（per hard_constraint #4 + Pitfall 5）：
全部用 `HybridSearchService(NullProvider)` / `HybridSearchService(LocalProvider)`
**直接调用**，不 patch `settings.ENABLE_CODEGRAPH` —— 启用决策集中在
`CodeIntelConfig.ready` 的 Provider 注入，本测试不参与 settings 读取。
外部依赖（RepoRouter / Symbol ORM / BranchAwareSearch / Embedding /
SparseEncoder / GraphExpansion）走 Plan 的 `golden_mock_environment_context`
确定性 mock，目标 < 5 秒跑完。
"""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from tests.codegraph.conftest import golden_mock_environment_context
# ---------------------------------------------------------------------------
# Case 1: NullProvider + repo_ids → 纯 RAG final_context（per .1）
# ---------------------------------------------------------------------------
async def test_case_1_null_provider_returns_pure_rag -> None:
 """`HybridSearchService(NullProvider).search` 返回 markdown 仅含 L3 section。
 选 ``user model`` query + ``repo-a`` 仓库（L3 fixture 含 1 条命中），断言：
 - ``## L3 Related Code`` 标题存在
 - ``## L2 Exact Matches`` / ``## L4 Graph Context`` 均不存在
 （NullProvider 路径绕开 SymbolService / GraphExpansionService，
 per T-）
 - 命中的 L3 payload 内容（``src/users/models.py``）在 final_context 内
 """
 with golden_mock_environment_context:
 result = await HybridSearchService(NullProvider).search(
 "user model",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert "## L3 Related Code" in result.final_context
 assert "## L2 Exact Matches" not in result.final_context
 assert "## L4 Graph Context" not in result.final_context
 assert "src/users/models.py" in result.final_context
 assert result.total_tokens > 0
 assert result.repository_ids == ["repo-a"]
# ---------------------------------------------------------------------------
# Case 2: NullProvider + repo_ids=None → 不调 RepoRouter（per .2）
# ---------------------------------------------------------------------------
async def test_case_2_null_provider_repo_ids_none_skips_repo_router -> None:
 """`repository_ids=None` 在 NullProvider 路径下**不**触发 L1 RepoRouter。
 NullProvider 路径直接以空 repo_ids 调 ``search_rag`` 兜底返回空 final_context。
 断言 ``RepoRouter.route`` mock 调用计数为 0（per T- 防 codegraph 误调用
 泄露 ORM 数据）。
 """
 router_spy = AsyncMock(return_value=)
 with golden_mock_environment_context, patch(
 "codegraph.services.repo_router.RepoRouter.route",
 new=router_spy,
 ):
 result = await HybridSearchService(NullProvider).search(
 "user model",
 repository_ids=None,
 max_tokens=8000,
 top_k=30,
 )
 assert router_spy.call_count == 0, (
 "NullProvider 路径不应触发 RepoRouter.route (per T- + .2)"
 )
 assert result.final_context == ""
 assert result.total_tokens == 0
 assert result.repository_ids ==
# ---------------------------------------------------------------------------
# Case 3: NullProvider + 空 L3 → final_context="" 不抛错（per .3）
# ---------------------------------------------------------------------------
async def test_case_3_null_provider_empty_results_returns_empty_context -> None:
 """``zzzzzz9999`` query 在 ``repo-a`` 下 L3 fixture 为空 → 返回空 final_context。
 NullProvider 路径在 ``l3.items == `` 时早返回（per hybrid_search.py
 line work-item），不进入 trim/format → 保证空命中场景下不抛错。
 """
 with golden_mock_environment_context:
 result = await HybridSearchService(NullProvider).search(
 "zzzzzz9999",
 repository_ids=["repo-a"],
 max_tokens=8000,
 top_k=30,
 )
 assert result.final_context == ""
 assert result.total_tokens == 0
 assert result.repository_ids == ["repo-a"]
 l3_layers = [layer for layer in result.layers if layer.layer == "L3"]
 assert l3_layers and l3_layers[0].status == "ok"
 assert l3_layers[0].items ==
# ---------------------------------------------------------------------------
# Case 4: NullProvider + max_tokens=200 → trim_to_budget 截断（per .4）
# ---------------------------------------------------------------------------
async def test_case_4_null_provider_token_overflow_triggers_trim -> None:
 """``GiantSeed`` query 返回 30 个长 chunk，``max_tokens=200`` 强制截断。
 断言 ``trim_to_budget`` 行为与 L3-only 路径等价：``(truncated:`` 标记出现，
 ``total_tokens <= 200``（hybrid_search.py 走 split_budget(ratios={"rag":1.0})
 → effective = int(200 * 0.9) = 180 → trim 阈值）。
 """
 with golden_mock_environment_context:
 result = await HybridSearchService(NullProvider).search(
 "GiantSeed",
 repository_ids=["repo-a"],
 max_tokens=200,
 top_k=30,
 )
 assert "(truncated:" in result.final_context, (
 "max_tokens=200 应触发 trim_to_budget 截断标记（per .4）"
 )
 assert "## L3 Related Code" in result.final_context
 assert 0 < result.total_tokens <= 200
# ---------------------------------------------------------------------------
# Case 5: LocalProvider vs NullProvider 在禁用配置下等价（per .5）
# ---------------------------------------------------------------------------
async def test_case_5_local_vs_null_equivalent_when_disabled -> None:
 """禁用配置等价语义下两 provider 路径产出 ``final_context`` 字节一致。
 "禁用配置"在生产由 ``CODE_INTELLIGENCE_PROVIDER=NullProvider`` 切换实现；
 本测试用"未知路由 query + repository_ids=None"模拟同等"无可搜索仓库"边界：
 - NullProvider 路径：``repository_ids=None`` → ``repo_ids=`` →
 ``search_rag`` 遍历空列表 → ``final_context=""``。
 - LocalProvider 路径：``_l1_repo_routing`` 调 mock RepoRouter → 未知 query
 返回空列表 → ``_search_graph_capable`` 在 ``if not repo_ids`` 处早返回
 → ``final_context=""``。
 两路径在边界条件下 byte-level 一致 → 验证 "零漂移"硬指标。
 本断言是 case_5 在当前实现下可严格 byte-equal 的最强形式（更深 L3 命中
 场景因 LocalProvider 路径 L5 reassembly 注入 L2/L4 占位段，无法 byte-equal；
 完整等价矩阵延后 Phase 处理）。
 """
 unknown_query = "no_route_for_this_query_zzz"
 with golden_mock_environment_context:
 null_result = await HybridSearchService(NullProvider).search(
 unknown_query,
 repository_ids=None,
 max_tokens=8000,
 top_k=30,
 )
 local_result = await HybridSearchService(LocalProvider).search(
 unknown_query,
 repository_ids=None,
 max_tokens=8000,
 top_k=30,
 )
 assert null_result.final_context == local_result.final_context == "", (
 "LocalProvider 与 NullProvider 在禁用配置等价语义下 final_context 必须字节一致 "
 "(per .5 + 零漂移)"
 )
 assert null_result.total_tokens == local_result.total_tokens == 0
 assert null_result.repository_ids == local_result.repository_ids ==
