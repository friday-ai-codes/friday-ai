"""HybridSearchService 编排器骨架 —— per Phase / 。
本 phase 只搭骨架，**不重写五层编排逻辑**：
- LocalProvider 路径（``isinstance(provider, GraphCapableProvider)`` True）：
 内联调用现状 ``LayeredSearchService._l1.._l5`` 五个私有 classmethod，
 保 final_context 与 ``LayeredSearchService.search`` **字节级等价**
 （per hard_constraint #4 + #7，golden snapshot zero-drift acceptance gate）。
 *不调用 ``LayeredSearchService.search`` 入口*，避免 Plan thin-wrapper
 反向 delegate 后形成循环（per hard_constraint break circular delegate）。
- NullProvider 路径（无 ``graph_expansion`` capability）：
 仅走 ``services.retrieval.search_rag`` + L5 ``trim_to_budget`` 一刀切裁剪，
 不触碰 symbol / expansion（per T- + hard_constraint #5）。
**禁读 codegraph 启用开关**（per Pitfall 5）：开关语义集中在
``CodeIntelConfig.ready`` 的 Provider 注入；本类 ``__init__(provider)``
显式持有 provider 实例，class 主体不出现 ``settings.``，CI grep gate
（``rg settings\\.ENABLE_CODEGRAP[H]`` 必须 0 命中）。
Phase 将本路径替换为 ``asyncio.gather`` 并发编排 + 图谱 enrichment 叠加；
Phase/252 才落 ChunkRegistry / EdgeBuilder。本 phase 显式排除这些工作。
"""
from __future__ import annotations
from typing import Any
import structlog
from services.code_intel.protocols import (
 BaseCodeProvider,
 GraphCapableProvider,
)
from services.retrieval.rag_search import search_rag
from services.retrieval.token_budget import (
 estimate_tokens,
 split_budget,
 trim_to_budget,
)
from services.retrieval.types import LayerSnapshot, RagSearchResult
logger = structlog.get_logger(__name__)
DEFAULT_MAX_TOKENS: int = 8000
DEFAULT_TOP_K: int = 30
class HybridSearchService:
 """RAG 主线 + 图谱编排器（per / ）。
 与 ``LayeredSearchService``（@classmethod 风格）不同，本类是**实例**风格，
 通过 ``__init__(provider)`` 显式注入 ``BaseCodeProvider``（per Pitfall 5
 + //：调用方负责拿 provider，本类不读 settings）。
 标准用法:
 from services.code_intel import get_provider
 from services.retrieval import HybridSearchService
 svc = HybridSearchService(get_provider)
 result = await svc.search("user login", repository_ids=["repo-a"])
 """
 def __init__(self, provider: BaseCodeProvider) -> None:
 """显式注入 Provider 实例。
 Args:
 provider: 实现 ``BaseCodeProvider`` Protocol 的实例（NullProvider /
 LocalProvider / 后续 RemoteProvider）。
 Raises:
 TypeError: provider 未实现 ``BaseCodeProvider`` Protocol（per
 T- 防御任意 duck-type 对象绕过）。
 """
 if not isinstance(provider, BaseCodeProvider):
 raise TypeError(
 "provider must implement BaseCodeProvider Protocol; "
 f"got {type(provider).__name__}",
 )
 self._provider: BaseCodeProvider = provider
 async def search(
 self,
 query: str,
 *,
 repository_ids: list[str] | None = None,
 project_id: str | None = None,
 branch_name: str | None = None,
 max_tokens: int = DEFAULT_MAX_TOKENS,
 top_k: int = DEFAULT_TOP_K,
 ) -> RagSearchResult:
 """两路径分发入口：GraphCapableProvider → 图谱等价委托；其余 → 纯 RAG。
 Args:
 query: 查询文本（来自 chat / agent / workflow，非可信输入）。
 repository_ids: 限定仓库列表；None 时 GraphCapable 路径走 L1 RepoRouter，
 NullProvider 路径直接以空列表调 ``search_rag``。
 project_id: 项目 id（暂未使用，保签名兼容 Plan callsite）。
 branch_name: 分支名（透传到 BranchAwareSearchService）。
 max_tokens: token 预算上限（默认 8000，与 LayeredSearchService 对齐）。
 top_k: 返回的最大条数（默认 30）。
 Returns:
 ``RagSearchResult``，字段语义与 ``LayeredSearchResult`` 1:1 兼容。
 """
 if isinstance(self._provider, GraphCapableProvider):
 return await self._search_graph_capable(
 query,
 repository_ids=repository_ids,
 project_id=project_id,
 branch_name=branch_name,
 max_tokens=max_tokens,
 top_k=top_k,
 )
 return await self._search_rag_only(
 query,
 repository_ids=repository_ids,
 branch_name=branch_name,
 max_tokens=max_tokens,
 top_k=top_k,
 )
 async def _search_graph_capable(
 self,
 query: str,
 *,
 repository_ids: list[str] | None,
 project_id: str | None,
 branch_name: str | None,
 max_tokens: int,
 top_k: int,
 ) -> RagSearchResult:
 """GraphCapableProvider 路径：内联调 LayeredSearchService 五个私有
 classmethod 保 final_context 字节级等价。
 本 phase 故意不重写五层逻辑（保 zero-drift）；Plan 让
 ``LayeredSearchService.search`` 反向 delegate 到本类时，仍能保私有
 classmethod 模块级 helper 保留为 internal 状态。
 """
 from codegraph.services.layered_search import LayeredSearchService as _LS
 logger.info(
 "hybrid_search_started",
 path="graph_capable",
 query=query[:100],
 )
 layers: list[LayerSnapshot] =
 l1, repo_ids = await _LS._l1_repo_routing(query, repository_ids, top_k)
 layers.append(_layer_to_snapshot(l1))
 if not repo_ids:
 logger.info(
 "hybrid_search_completed",
 path="graph_capable",
 repo_count=0,
 total_tokens=0,
 )
 return RagSearchResult(
 query=query,
 repository_ids=,
 layers=layers,
 final_context="",
 total_tokens=0,
 )
 l2 = await _LS._l2_symbol_lookup(query, repo_ids)
 layers.append(_layer_to_snapshot(l2))
 l3 = await _LS._l3_hybrid_search(query, repo_ids, top_k, branch_name)
 layers.append(_layer_to_snapshot(l3))
 l4 = await _LS._l4_graph_expansion(l2.items)
 layers.append(_layer_to_snapshot(l4))
 final_context, total_tokens = _LS._l5_context_reassembly(
 l2, l3, l4, max_tokens,
 )
 layers.append(LayerSnapshot(layer="L5", status="ok", result_count=total_tokens))
 logger.info(
 "hybrid_search_completed",
 path="graph_capable",
 repo_count=len(repo_ids),
 total_tokens=total_tokens,
 )
 return RagSearchResult(
 query=query,
 repository_ids=repo_ids,
 layers=layers,
 final_context=final_context,
 total_tokens=total_tokens,
 )
 async def _search_rag_only(
 self,
 query: str,
 *,
 repository_ids: list[str] | None,
 branch_name: str | None,
 max_tokens: int,
 top_k: int,
 ) -> RagSearchResult:
 """NullProvider 路径：仅走 search_rag + L5 token 裁剪。
 per T-：不触 SymbolService / GraphExpansionService，
 capability 守卫（``isinstance(provider, GraphCapableProvider)`` False）
 已在 search 入口完成。
 """
 from codegraph.services.layered_search import LayeredSearchService as _LS
 logger.info(
 "hybrid_search_started",
 path="rag_only",
 query=query[:100],
 )
 repo_ids: list[str] = list(repository_ids or )
 l3: LayerSnapshot = await search_rag(
 query,
 repo_ids=repo_ids,
 branch_name=branch_name,
 top_k=top_k,
 )
 if l3.status != "ok" or not l3.items:
 logger.info(
 "hybrid_search_completed",
 path="rag_only",
 repo_count=len(repo_ids),
 l3_status=l3.status,
 total_tokens=0,
 )
 return RagSearchResult(
 query=query,
 repository_ids=repo_ids,
 layers=[l3],
 final_context="",
 total_tokens=0,
 )
 # 复用 LayeredSearchService._format_l3_section 保格式 idiom 一致：
 # `## L3 Related Code\n\n### {file_path} (score: {score:.3f})\n```\n{content}\n```\n`
 l3_markdown: str = _LS._format_l3_section(l3.items)
 budgets: dict[str, int] = split_budget(max_tokens, ratios={"rag": 1.0})
 final_context: str = trim_to_budget(l3_markdown, budgets["rag"])
 total_tokens: int = estimate_tokens(final_context)
 logger.info(
 "hybrid_search_completed",
 path="rag_only",
 repo_count=len(repo_ids),
 total_tokens=total_tokens,
 )
 return RagSearchResult(
 query=query,
 repository_ids=repo_ids,
 layers=[
 l3,
 LayerSnapshot(layer="L5", status="ok", result_count=total_tokens),
 ],
 final_context=final_context,
 total_tokens=total_tokens,
 )
def _layer_to_snapshot(layer: Any) -> LayerSnapshot:
 """``LayerResult`` → ``LayerSnapshot`` 字段 1:1 拷贝。
 显式枚举字段（不用 ``**__dict__``）以保 mypy 类型友好；两者 dataclass
 字段同名同序，零拷贝语义。
 """
 return LayerSnapshot(
 layer=layer.layer,
 status=layer.status,
 result_count=layer.result_count,
 items=list(layer.items),
 error=layer.error,
 extra=dict(layer.extra) if layer.extra else None,
 )
__all__ = ["HybridSearchService"]
