"""LocalProvider —— 本地 codegraph 服务的 Provider 包装 (per Phase / ).
包装现有 ``codegraph`` 服务：
- ``lookup_symbols`` 对齐 ``LayeredSearchService._l2_symbol_lookup`` 的 ORM 查询
 （iexact 主路径 + icontains 回退），不暴露 Symbol ORM 对象（per T-）。
- ``expand_graph`` 沿用 ``GraphExpansionService.expand`` + LayeredSearchService L4
 的 nodes 同名去重保留最短 depth 语义；``max_hops > 2`` 直接 ValueError（per ）。
实现走 lazy import：避免 ``services`` 包在 Django app loading 早期触发 ORM 模型导入。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import structlog
from asgiref.sync import sync_to_async
logger = structlog.get_logger(__name__)
@dataclass(frozen=True, slots=True)
class LocalProvider:
 """本地 Provider：包装 codegraph SymbolService + GraphExpansionService。"""
 capabilities: frozenset[str] = frozenset({"symbol_lookup", "graph_expansion"})
 async def health_check(self) -> bool:
 """本地实现始终在线（即使图谱表为空，也只是返回空结果而非不可用）。"""
 return True
 async def lookup_symbols(
 self,
 names: list[str],
 *,
 repository_ids: list[str],
 ) -> list[dict[str, Any]]:
 """按符号名做 iexact 精确查找 + icontains 回退（与 L2 行为完全对齐）。"""
 if not names or not repository_ids:
 logger.debug("local_provider_lookup_skipped", names=names, repo_count=len(repository_ids))
 return
 from codegraph.models import Symbol
 all_symbols: list[Any] =
 seen_ids: set[str] = set
 for term in names:
 exact_matches: list[Any] = await sync_to_async(list)( # type: ignore[call-arg]
 Symbol.objects.filter(
 name__iexact=term, repository_id__in=repository_ids,
 ).select_related("repository"),
 )
 for sym in exact_matches:
 sid = str(sym.id)
 if sid not in seen_ids:
 seen_ids.add(sid)
 all_symbols.append(sym)
 if not exact_matches:
 fuzzy_matches: list[Any] = await sync_to_async(list)( # type: ignore[call-arg]
 Symbol.objects.filter(
 name__icontains=term, repository_id__in=repository_ids,
 ).select_related("repository")[:10],
 )
 for sym in fuzzy_matches:
 sid = str(sym.id)
 if sid not in seen_ids:
 seen_ids.add(sid)
 all_symbols.append(sym)
 items = [
 {
 "symbol_id": str(s.id),
 "name": s.name,
 "symbol_type": s.symbol_type,
 "file_path": s.file_path,
 "start_line": s.start_line,
 "end_line": s.end_line,
 "signature": s.signature,
 "repository_id": str(s.repository_id),
 "repository_name": s.repository.name,
 }
 for s in all_symbols
 ]
 logger.info(
 "local_provider_lookup_completed",
 term_count=len(names),
 repo_count=len(repository_ids),
 hit_count=len(items),
 )
 return items
 async def expand_graph(
 self,
 seed_symbols: list[dict[str, Any]],
 *,
 max_hops: int = 2,
 ) -> dict[str, list[dict[str, Any]]]:
 """对 L2 命中的种子做 1+2-hop 图扩展，同名节点保留最短 depth。"""
 if max_hops > 2:
 raise ValueError(f"max_hops={max_hops} exceeds the supported limit of 2 (per )")
 if max_hops < 0:
 raise ValueError(f"max_hops={max_hops} must be non-negative")
 if not seed_symbols or max_hops == 0:
 return {"nodes":, "edges": }
 from codegraph.models import Symbol
 from codegraph.services.graph_expansion import GraphExpansionService
 all_nodes: dict[str, dict[str, Any]] = {}
 all_edges: list[dict[str, Any]] =
 for seed_info in seed_symbols[:5]:
 symbol_id = seed_info.get("symbol_id")
 if not symbol_id:
 continue
 try:
 seed = await sync_to_async(Symbol.objects.get)(id=symbol_id)
 except Symbol.DoesNotExist:
 logger.debug("local_provider_seed_missing", symbol_id=symbol_id)
 continue
 expand_result = await GraphExpansionService.expand(seed)
 for node in expand_result.get("nodes", ):
 sym = node["symbol"]
 nid = str(sym.id)
 serialized = {
 "symbol_id": nid,
 "name": sym.name,
 "symbol_type": sym.symbol_type,
 "file_path": sym.file_path,
 "start_line": sym.start_line,
 "end_line": sym.end_line,
 "depth": node["depth"],
 "relationship": node["relationship"],
 }
 if nid not in all_nodes or node["depth"] < all_nodes[nid]["depth"]:
 all_nodes[nid] = serialized
 for edge in expand_result.get("edges", ):
 all_edges.append({
 "source": str(edge.get("source", "")),
 "target": str(edge.get("target", "")),
 "call_type": edge.get("call_type", ""),
 })
 nodes = list(all_nodes.values)
 logger.info(
 "local_provider_expand_completed",
 seed_count=len(seed_symbols),
 node_count=len(nodes),
 edge_count=len(all_edges),
 max_hops=max_hops,
 )
 return {"nodes": nodes, "edges": all_edges}
__all__ = ["LocalProvider"]
