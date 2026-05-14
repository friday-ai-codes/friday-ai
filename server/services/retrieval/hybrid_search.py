"""HybridSearchService 编排器（per Phase Plan）。
Phase 落地骨架（``HybridSearchService.__init__`` + ``search`` 分发入口 +
``_search_rag_only`` NullProvider 路径）保持 byte-for-byte 等价；Phase Plan
将 ``_search_graph_capable`` 重写为真正的 GraphRAG 编排器：
- **wave 并发**：``asyncio.gather(rag_task, symbol_task, return_exceptions=True)``
 让 RAG 召回与符号查找并发执行；rag_task 失败 → 直接 raise（RAG 主线必选项），
 symbol_task 失败 → log warning + 降级到 ``symbol_results=``（图谱 enrichment
 是优化项，可降级）。**注意**：与 "return_exceptions=False" 字面冲突——本
 plan 改 True 实现差异化降级，记录在 Plan deviations 中。
- **一跳 enrichment**：``extract_hop1_neighbors_raw`` 解析 RAG 命中 chunk 的 payload
 ``related_chunks`` + ``resolve_neighbor_metadata`` 单次 ORM ``in_bulk`` 拉
 metadata（Plan 落）。
- **二跳 enrichment**：``expand_hop2`` 走 ChunkEdge ORM aiter + 三重去重
 （Plan 落）；``enable_graph_enrichment=False`` 时跳过二跳（即使 Provider
 支持图谱）。
- **HybridBudget 60/40**：``HybridBudget.from_settings.allocate(max_tokens)``
 返回 ``{rag, graph}`` 子预算，``trim_to_budget`` 对 RAG / graph 段分别二次裁剪。
- **graph_context markdown**：``## Graph Context`` 两段（Direct/Indirect Neighbors）
 按 ``- <code>{file_path}:{line}</code> ({edge_type}, w={weight:.2f}): {reason}``
 渲染；空 neighbors → 不写空 markdown 段。
- **structlog wave 日志**：``hybrid_search_wave_started`` / ``hybrid_search_wave_done``
 与 Phase 既有 ``hybrid_search_started`` / ``hybrid_search_completed`` 共存。
**Pitfall 5 守门**：本模块**不读** codegraph 启用开关；图谱启停由
``isinstance(provider, GraphCapableProvider)`` 运行时守卫 +
``enable_graph_enrichment`` 调用方参数控制；CI grep gate
``rg "settings\\.ENABLE_CODEGRAP[H]"`` 必须 0 命中。
"""
from __future__ import annotations
import asyncio
import time
from typing import Any
import structlog
from services.code_intel.protocols import (
 BaseCodeProvider,
 GraphCapableProvider,
)
from services.retrieval.budget import HybridBudget
from services.retrieval.hop1_reader import (
 extract_hop1_neighbors_raw,
 resolve_neighbor_metadata,
)
from services.retrieval.hop2_expander import expand_hop2
from services.retrieval.rag_search import search_rag
from services.retrieval.token_budget import (
 estimate_tokens,
 split_budget,
 trim_to_budget,
)
from services.retrieval.types import (
 HybridSearchResult,
 LayerSnapshot,
 NeighborMetadata,
 RagSearchResult,
)
logger = structlog.get_logger(__name__)
DEFAULT_MAX_TOKENS: int = 8000
DEFAULT_TOP_K: int = 30
def _stub_reason_fn(edge_type: str, source_chunk_id: str) -> str:
 """reason 字段 stub —— 仅返回 "via {edge_type}" 简单形式。
 Plan ``_explain_neighbor`` 落地后替换为完整模板（含 metadata 解析、
 co-change 次数、test 关系等）；本 plan 用 stub 占位保 markdown 渲染非空。
 """
 return f"via {edge_type}"
def _render_neighbor_line(neighbor: NeighborMetadata) -> str:
 """单个 NeighborMetadata → markdown 一行（per ）。
 格式：``- `{file_path}:{line_start}` ({edge_type}, w={weight:.2f}): {reason}``
 - ``file_path == "<unknown>"`` → 跳过（hop1_reader ChunkRegistry 缺失 fallback）；
 调用方 ``_render_graph_context`` 负责过滤。
 - ``line_start is None`` → 省略行号（``:`` 后缀也省）。
 """
 if neighbor.line_start is None:
 location = f"`{neighbor.file_path}`"
 else:
 location = f"`{neighbor.file_path}:{neighbor.line_start}`"
 return (
 f"- {location} ({neighbor.edge_type}, w={neighbor.weight:.2f}): "
 f"{neighbor.reason}"
 )
def _render_graph_context(
 hop1: list[NeighborMetadata],
 hop2: list[NeighborMetadata],
) -> str:
 """拼装 ``## Graph Context`` markdown（per ）。
 - 两段：``### Direct Neighbors (1-hop)`` / ``### Indirect Neighbors (2-hop)``
 - 邻居按 weight desc 排序
 - 过滤 ``file_path == "<unknown>"`` 的占位行（ChunkRegistry 缺失 fallback）
 - 两段均空 → 返回 ``""``（**不写空 markdown 块**，避免污染 LLM 上下文）
 - 仅一段空 → 仅渲染非空段
 """
 def _filtered_sorted(items: list[NeighborMetadata]) -> list[NeighborMetadata]:
 valid = [n for n in items if n.file_path != "<unknown>"]
 return sorted(valid, key=lambda n: -n.weight)
 h1 = _filtered_sorted(hop1)
 h2 = _filtered_sorted(hop2)
 if not h1 and not h2:
 return ""
 sections: list[str] = ["## Graph Context", ""]
 if h1:
 sections.append("### Direct Neighbors (1-hop)")
 sections.append("")
 sections.extend(_render_neighbor_line(n) for n in h1)
 sections.append("")
 if h2:
 sections.append("### Indirect Neighbors (2-hop)")
 sections.append("")
 sections.extend(_render_neighbor_line(n) for n in h2)
 sections.append("")
 return "\n".join(sections).rstrip
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
 enable_graph_enrichment: bool = True,
 ) -> RagSearchResult | HybridSearchResult:
 """两路径分发入口：GraphCapableProvider → 编排器；其余 → 纯 RAG。
 Args:
 query: 查询文本（来自 chat / agent / workflow，非可信输入）。
 repository_ids: 限定仓库列表；None 时 NullProvider 路径直接以空列表
 调 ``search_rag``，GraphCapable 路径同样以空列表传给 RAG/symbol task。
 project_id: 项目 id（暂未使用，保签名兼容 Plan callsite）。
 branch_name: 分支名（透传到 BranchAwareSearchService）。
 max_tokens: token 预算上限（默认 8000，与 LayeredSearchService 对齐）。
 top_k: 返回的最大条数（默认 30）。
 enable_graph_enrichment: 是否启用图谱 enrichment（默认 True）。
 False 时强制走 ``_search_rag_only`` 路径，即使 Provider 支持图谱。
 供 callsite 在不需要二跳扩散时主动短路（不与 settings flag 重复）。
 Returns:
 - GraphCapable 路径 + ``enable_graph_enrichment=True`` → ``HybridSearchResult``
 （含 ``graph_context`` / ``hop1_neighbors`` / ``hop2_neighbors`` 三字段）
 - 其余路径 → ``RagSearchResult``（字段同名同序兼容 callsite）
 """
 if enable_graph_enrichment and isinstance(self._provider, GraphCapableProvider):
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
 ) -> HybridSearchResult:
 """GraphCapableProvider 路径：asyncio.gather 并发 + 图谱 enrichment。
 wave：``rag_task = search_rag(...)`` ‖ ``symbol_task = provider.lookup_symbols(...)``。
 wave：``hop1_neighbors = resolve_neighbor_metadata(extract_hop1_neighbors_raw(...))``。
 wave：``hop2_neighbors = expand_hop2(...)``。
 rag_task 失败 → 直接 raise（RAG 主线必选项）；symbol_task 失败 → log
 warning + symbol_results= + 仍走 rag 路径（图谱 enrichment 降级）。
 """
 # lazy import：保模块加载顺序 + 复用 Phase 既有 idiom，不重复造关键词抽取
 from codegraph.services.layered_search import LayeredSearchService as _LS
 logger.info(
 "hybrid_search_started",
 path="graph_capable",
 query=query[:100],
 )
 repo_ids: list[str] = list(repository_ids or )
 budgets: dict[str, int] = HybridBudget.from_settings.allocate(max_tokens)
 keywords: list[str] = _LS._extract_symbol_names(query)
 # ---- wave：rag_task ‖ symbol_task --------------------------------
 logger.info(
 "hybrid_search_wave_started",
 wave_id=0,
 wave_0_tasks=["rag", "symbol"],
 )
 t0 = time.perf_counter
 rag_task = asyncio.create_task(
 search_rag(
 query,
 repo_ids=repo_ids,
 branch_name=branch_name,
 top_k=top_k,
 ),
 )
 # GraphCapableProvider 已守卫；mypy 不识别 isinstance + create_task 闭合，
 # 用 self._provider 直接调，运行时由 isinstance(GraphCapableProvider) 保证。
 symbol_task = asyncio.create_task(
 self._provider.lookup_symbols( # type: ignore[attr-defined]
 keywords,
 repository_ids=repo_ids,
 ),
 )
 results = await asyncio.gather(
 rag_task, symbol_task, return_exceptions=True,
 )
 elapsed_ms = int((time.perf_counter - t0) * 1000)
 logger.info(
 "hybrid_search_wave_done",
 wave_id=0,
 elapsed_ms=elapsed_ms,
 )
 # rag 失败 → 直接传播（RAG 主线必选项，per Discretion）
 rag_result = results[0]
 if isinstance(rag_result, BaseException):
 logger.warning(
 "rag_task_failed",
 error=str(rag_result),
 error_type=type(rag_result).__name__,
 )
 raise rag_result
 # symbol 失败 → log warning + 降级 symbol_results=（图谱 enrichment 可降级）
 symbol_result = results[1]
 symbol_failed: bool = False
 symbol_results: list[dict[str, Any]]
 if isinstance(symbol_result, BaseException):
 logger.warning(
 "symbol_task_failed",
 error=str(symbol_result),
 error_type=type(symbol_result).__name__,
 )
 symbol_results =
 symbol_failed = True
 else:
 symbol_results = list(symbol_result) if symbol_result else
 rag_snapshot: LayerSnapshot = rag_result
 rag_chunk_ids: set[str] = {
 str(item.get("id"))
 for item in rag_snapshot.items
 if item.get("id")
 }
 # ---- wave：一跳 enrichment（payload 直读 + 单次 ORM in_bulk）------
 raw_h1 = extract_hop1_neighbors_raw(rag_snapshot.items)
 hop1_neighbors: list[NeighborMetadata] = await resolve_neighbor_metadata(
 raw_h1,
 hop=1,
 reason_fn=_stub_reason_fn,
 )
 hop1_chunk_ids: set[str] = {n.chunk_id for n in hop1_neighbors}
 # ---- wave：二跳 enrichment（ChunkEdge ORM aiter + 三重去重）------
 hop2_neighbors: list[NeighborMetadata] = await expand_hop2(
 hop1_chunk_ids=hop1_chunk_ids,
 rag_chunk_ids=rag_chunk_ids,
 repo_ids=repo_ids,
 reason_fn=_stub_reason_fn,
 )
 # ---- graph_context markdown 拼装 + 双段 trim_to_budget --------------
 graph_context_raw: str = _render_graph_context(hop1_neighbors, hop2_neighbors)
 # RAG section 复用 LayeredSearchService._format_l3_section 保格式 idiom 一致
 l3_markdown: str = _LS._format_l3_section(rag_snapshot.items)
 rag_section: str = trim_to_budget(l3_markdown, budgets["rag"])
 graph_section: str = (
 trim_to_budget(graph_context_raw, budgets["graph"])
 if graph_context_raw
 else ""
 )
 # 无 graph_section 时保 rag_section 原貌（含 trim_to_budget 产出的尾换行），
 # 与 _search_rag_only 路径 byte-equal —— 兑现 Phase byte-eq 承诺（Phase 提前）
 if graph_section:
 final_context = f"{rag_section.rstrip}\n\n{graph_section}".rstrip
 else:
 final_context = rag_section
 total_tokens: int = estimate_tokens(final_context)
 logger.info(
 "hybrid_search_completed",
 path="graph_capable",
 repo_count=len(repo_ids),
 total_tokens=total_tokens,
 hop1_count=len(hop1_neighbors),
 hop2_count=len(hop2_neighbors),
 symbol_count=len(symbol_results),
 symbol_failed=symbol_failed,
 wave_0_elapsed_ms=elapsed_ms,
 )
 # project_id 暂未参与编排（保签名兼容 Plan callsite）
 _ = project_id
 return HybridSearchResult(
 query=query,
 repository_ids=repo_ids,
 layers=[rag_snapshot],
 final_context=final_context,
 total_tokens=total_tokens,
 graph_context=graph_section,
 hop1_neighbors=hop1_neighbors,
 hop2_neighbors=hop2_neighbors,
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
 **Phase zero-drift 守门**：本方法 byte-for-byte 等价 Phase
 实现，既有 NullProvider 路径测试（test_hybrid_skeleton + test_null_provider_paths）
 必须全绿。
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
__all__ = ["HybridSearchService"]
