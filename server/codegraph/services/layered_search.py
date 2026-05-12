"""五层检索编排服务 —— L1 Repo Routing → L2 Symbol Lookup → L3 Hybrid Search → L4 Graph Expansion → L5 Context Reassembly。
Per //////。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any
import structlog
from asgiref.sync import sync_to_async
logger = structlog.get_logger(__name__)
@dataclass
class LayerResult:
 """单层检索结果。"""
 layer: str # "L1", "L2", "L3", "L4", "L5"
 status: str # "ok", "skipped", "error"
 result_count: int = 0
 items: list[dict[str, Any]] = field(default_factory=list)
 error: str | None = None
 extra: dict[str, Any] | None = None
@dataclass
class LayeredSearchResult:
 """五层检索最终结果 (per )。"""
 query: str
 repository_ids: list[str]
 layers: list[LayerResult]
 final_context: str # 经 L5 裁剪后的 markdown 格式文本
 total_tokens: int # 实际使用的 token 数
class LayeredSearchService:
 """五层检索编排服务 —— per //////。
 L1: Repo Routing → L2: Symbol Lookup → L3: Hybrid Search → L4: Graph Expansion → L5: Context Reassembly
 """
 # 可配置常量
 DEFAULT_MAX_TOKENS: int = 8000 # per
 TOKEN_BUFFER_RATIO: float = 0.9 # per RESEARCH Pitfall 4
 DEFAULT_TOP_K: int = 30 # per
 L4_1HOP_TOKEN_BUDGET: int = 3000 # per
 L3_TOKEN_BUDGET: int = 3000 # per
 @classmethod
 async def search(
 cls,
 query: str,
 *,
 repository_ids: list[str] | None = None,
 project_id: str | None = None,
 branch_name: str | None = None,
 max_tokens: int = DEFAULT_MAX_TOKENS,
 top_k: int = DEFAULT_TOP_K,
 ) -> LayeredSearchResult:
 """执行五层检索流水线，返回结构化结果。"""
 layers: list[LayerResult] =
 # L1
 l1_layer, repo_ids = await cls._l1_repo_routing(query, repository_ids, top_k)
 layers.append(l1_layer)
 if not repo_ids:
 return LayeredSearchResult(
 query=query, repository_ids=, layers=layers, final_context="", total_tokens=0,
 )
 # L2
 l2_layer = await cls._l2_symbol_lookup(query, repo_ids)
 layers.append(l2_layer)
 # L3
 l3_layer = await cls._l3_hybrid_search(query, repo_ids, top_k, branch_name)
 layers.append(l3_layer)
 # L4
 l4_layer = await cls._l4_graph_expansion(l2_layer.items)
 layers.append(l4_layer)
 # L5
 final_context, total_tokens = cls._l5_context_reassembly(l2_layer, l3_layer, l4_layer, max_tokens)
 layers.append(LayerResult(layer="L5", status="ok", result_count=total_tokens))
 logger.info("layered_search_completed", query=query[:100], repo_count=len(repo_ids), total_tokens=total_tokens)
 return LayeredSearchResult(
 query=query, repository_ids=repo_ids, layers=layers,
 final_context=final_context, total_tokens=total_tokens,
 )
 # ------------------------------------------------------------------
 # L1 — Repo Routing (per )
 # ------------------------------------------------------------------
 @classmethod
 async def _l1_repo_routing(
 cls, query: str, repository_ids: list[str] | None, top_k: int,
 ) -> tuple[LayerResult, list[str]]:
 """仓库路由：确定搜索目标仓库集合。"""
 if repository_ids:
 return (
 LayerResult(layer="L1", status="skipped", result_count=len(repository_ids)),
 repository_ids,
 )
 try:
 from codegraph.services.repo_router import RepoRouter
 route_results = await RepoRouter.route(query, top_k=min(top_k, 5))
 repo_ids = [r.repo_id for r in route_results]
 items = [
 {"repo_id": r.repo_id, "repo_name": r.repo_name, "score": r.final_score, "match_reason": r.match_reason}
 for r in route_results
 ]
 return LayerResult(layer="L1", status="ok", result_count=len(repo_ids), items=items), repo_ids
 except Exception as e:
 logger.warning("l1_routing_failed", query=query[:100], error=str(e))
 # 降级: 返回所有已索引仓库
 from repositories.models import IndexStatus, Repository
 repos = await sync_to_async(list)(
 Repository.objects.filter(index_status=IndexStatus.INDEXED, is_deleted=False).values_list("id", flat=True)[:5],
 )
 repo_ids = [str(r) for r in repos]
 return LayerResult(layer="L1", status="error", result_count=len(repo_ids), error=str(e)), repo_ids
 # ------------------------------------------------------------------
 # L2 — Symbol Lookup (per )
 # ------------------------------------------------------------------
 # 语言关键字过滤集
 _KEYWORDS: set[str] = {
 "if", "for", "while", "class", "def", "function", "var", "const", "let",
 "return", "import", "from", "package", "func", "type", "interface",
 "the", "and", "not", "or", "in", "is", "as", "with",
 }
 @staticmethod
 def _extract_symbol_names(query: str) -> list[str]:
 """从查询文本中提取可能的符号名 (per RESEARCH Pitfall 3)."""
 # 大写开头词: UserModel, CreateUser
 pascal = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", query)
 # 点号分隔标识符: django.db.models
 dotted = re.findall(r"\b[a-z][a-zA-Z0-9_]*\.[a-z_][a-zA-Z0-9_.]*\b", query)
 terms = [t for t in pascal + dotted if t.lower not in LayeredSearchService._KEYWORDS]
 # 去重保序
 seen: set[str] = set
 result: list[str] =
 for t in terms:
 if t.lower not in seen:
 seen.add(t.lower)
 result.append(t)
 return result[:10] # 最多 10 个符号名
 @classmethod
 async def _l2_symbol_lookup(cls, query: str, repo_ids: list[str]) -> LayerResult:
 """符号精确匹配：大写开头的类/函数名或点号分隔的标识符。"""
 try:
 terms = cls._extract_symbol_names(query)
 if not terms:
 return LayerResult(layer="L2", status="skipped")
 from codegraph.models import Symbol
 all_symbols: list[Any] =
 seen_ids: set[str] = set
 for term in terms:
 # 精确匹配 (uses (repository, name) composite index)
 exact_matches = await sync_to_async(list)(
 Symbol.objects.filter(
 name__iexact=term, repository_id__in=repo_ids,
 ).select_related("repository"),
 )
 for sym in exact_matches:
 sid = str(sym.id)
 if sid not in seen_ids:
 seen_ids.add(sid)
 all_symbols.append(sym)
 # 回退: 模糊匹配 (仅在无精确结果时)
 if not exact_matches:
 fuzzy_matches = await sync_to_async(list)(
 Symbol.objects.filter(
 name__icontains=term, repository_id__in=repo_ids,
 ).select_related("repository")[:10],
 )
 for sym in fuzzy_matches:
 sid = str(sym.id)
 if sid not in seen_ids:
 seen_ids.add(sid)
 all_symbols.append(sym)
 items = [
 {
 "symbol_id": str(s.id), "name": s.name, "symbol_type": s.symbol_type,
 "file_path": s.file_path, "start_line": s.start_line, "end_line": s.end_line,
 "signature": s.signature, "repository_id": str(s.repository_id),
 "repository_name": s.repository.name,
 }
 for s in all_symbols
 ]
 return LayerResult(layer="L2", status="ok", result_count=len(items), items=items)
 except Exception as e:
 logger.warning("l2_symbol_lookup_failed", query=query[:100], error=str(e))
 return LayerResult(layer="L2", status="error", error=str(e))
 # ------------------------------------------------------------------
 # L3 — Hybrid Search (per )
 # ------------------------------------------------------------------
 @classmethod
 async def _l3_hybrid_search(
 cls, query: str, repo_ids: list[str], top_k: int, branch_name: str | None,
 ) -> LayerResult:
 """混合向量搜索：对每个路由仓库调用 BranchAwareSearchService。"""
 try:
 from services.branch_search import BranchAwareSearchService
 from services.embedding import EmbeddingService
 from services.sparse_encoder import SparseEncoderService
 query_dense = await EmbeddingService.generate_embedding(query)
 if not query_dense:
 return LayerResult(layer="L3", status="error", error="embedding generation failed")
 query_sparse: dict[str, Any] | None = await sync_to_async(SparseEncoderService.encode)(query)
 if not query_sparse or not query_sparse.get("indices"):
 query_sparse = None
 all_results: list[dict[str, Any]] =
 seen_keys: set[tuple[str, str, int]] = set # (repo_id, file_path, chunk_index)
 for repo_id in repo_ids:
 try:
 results = await BranchAwareSearchService.search(
 repo_id, query_dense,
 query_sparse=query_sparse,
 branch_name=branch_name,
 top_k=top_k,
 )
 for r in results:
 payload = r.get("payload", {})
 key = (repo_id, payload.get("file_path", ""), payload.get("chunk_index", 0))
 if key not in seen_keys:
 seen_keys.add(key)
 all_results.append({**r, "repository_id": repo_id})
 except Exception as e:
 logger.warning("l3_single_repo_search_failed", repo_id=repo_id, error=str(e))
 # 按 score 降序排序
 all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
 return LayerResult(layer="L3", status="ok", result_count=len(all_results), items=all_results[:top_k])
 except Exception as e:
 logger.warning("l3_hybrid_search_failed", query=query[:100], error=str(e))
 return LayerResult(layer="L3", status="error", error=str(e))
 # ------------------------------------------------------------------
 # L4 — Graph Expansion (per )
 # ------------------------------------------------------------------
 @classmethod
 async def _l4_graph_expansion(cls, l2_symbols: list[dict[str, Any]]) -> LayerResult:
 """图谱扩展：对 L2 匹配符号做图遍历，仅仓库内。"""
 try:
 if not l2_symbols:
 return LayerResult(layer="L4", status="skipped")
 from codegraph.services.graph_expansion import GraphExpansionService
 from codegraph.models import Symbol
 all_nodes: dict[str, dict[str, Any]] = {} # symbol_id -> node (保留最短 depth)
 all_edges: list[dict[str, Any]] =
 for sym_info in l2_symbols[:5]: # 最多对 5 个 L2 符号做扩展
 try:
 seed = await sync_to_async(Symbol.objects.get)(id=sym_info["symbol_id"])
 except Symbol.DoesNotExist:
 continue
 expand_result = await GraphExpansionService.expand(seed)
 for node in expand_result["nodes"]:
 nid = str(node["symbol"].id)
 if nid not in all_nodes or node["depth"] < all_nodes[nid]["depth"]:
 all_nodes[nid] = node
 for edge in expand_result["edges"]:
 all_edges.append(edge)
 items = [
 {"symbol": n["symbol"], "depth": n["depth"], "relationship": n["relationship"]}
 for n in all_nodes.values
 ]
 return LayerResult(
 layer="L4", status="ok", result_count=len(items), items=items,
 extra={"edge_count": len(all_edges)},
 )
 except Exception as e:
 logger.warning("l4_graph_expansion_failed", error=str(e))
 return LayerResult(layer="L4", status="error", error=str(e))
 # ------------------------------------------------------------------
 # L5 — Context Reassembly (per )
 # ------------------------------------------------------------------
 @classmethod
 def _l5_context_reassembly(
 cls, l2_layer: LayerResult, l3_layer: LayerResult,
 l4_layer: LayerResult, max_tokens: int,
 ) -> tuple[str, int]:
 """上下文重组：按优先级裁剪组装 markdown 格式文本。"""
 import tiktoken
 enc = tiktoken.get_encoding("cl100k_base")
 effective_budget = int(max_tokens * cls.TOKEN_BUFFER_RATIO) # 7200 for 8000
 sections: list[str] =
 # L2 节: 精确匹配 (全部保留 — per )
 l2_section = cls._format_l2_section(l2_layer)
 sections.append(l2_section)
 current_tokens = len(enc.encode("\n\n".join(sections)))
 # L4 节: 1-hop 关系 (子预算 3000)
 l4_hop1_section, l4_hop2_section = cls._format_l4_section_split(l4_layer)
 hop1_tokens = len(enc.encode(l4_hop1_section))
 if hop1_tokens <= cls.L4_1HOP_TOKEN_BUDGET:
 sections.append(l4_hop1_section)
 current_tokens = len(enc.encode("\n\n".join(sections)))
 else:
 trimmed_hop1 = cls._trim_to_token_budget(l4_hop1_section, cls.L4_1HOP_TOKEN_BUDGET, enc)
 sections.append(trimmed_hop1)
 current_tokens = len(enc.encode("\n\n".join(sections)))
 # L3 节: 去重后的 hybrid 结果 (子预算 3000, 排除已被 L2 覆盖的 file_path)
 l3_filtered = cls._filter_l3_dedup(l3_layer, l2_layer)
 l3_section = cls._format_l3_section(l3_filtered)
 l3_tokens = len(enc.encode(l3_section))
 if l3_tokens <= cls.L3_TOKEN_BUDGET:
 sections.append(l3_section)
 current_tokens = len(enc.encode("\n\n".join(sections)))
 else:
 trimmed_l3 = cls._trim_to_token_budget(l3_section, cls.L3_TOKEN_BUDGET, enc)
 sections.append(trimmed_l3)
 current_tokens = len(enc.encode("\n\n".join(sections)))
 # L4 节: 2-hop 关系 (使用剩余预算)
 remaining = effective_budget - current_tokens
 if remaining > 200 and l4_hop2_section: # 至少 200 token 才值得加
 hop2_tokens = len(enc.encode(l4_hop2_section))
 if hop2_tokens <= remaining:
 sections.append(l4_hop2_section)
 else:
 trimmed_hop2 = cls._trim_to_token_budget(l4_hop2_section, remaining, enc)
 sections.append(trimmed_hop2)
 final_context = "\n\n".join(sections)
 final_tokens = len(enc.encode(final_context))
 return final_context, final_tokens
 # ------------------------------------------------------------------
 # L5 格式化辅助方法
 # ------------------------------------------------------------------
 @staticmethod
 def _format_l2_section(layer: LayerResult) -> str:
 """格式化 L2 精确匹配 section。"""
 lines = ["## L2 Exact Matches\n"]
 if not layer.items:
 lines.append("(no exact symbol matches found)\n")
 else:
 for item in layer.items:
 lines.append(
 f"- `{item['name']}` ({item['symbol_type']}) "
 f"in {item['file_path']}:{item['start_line']}-{item['end_line']} "
 f"[{item['repository_name']}]"
 )
 return "\n".join(lines)
 @staticmethod
 def _format_l4_section_split(layer: LayerResult) -> tuple[str, str]:
 """拆分为 1-hop 和 2-hop 两个 section。"""
 hop1 = ["## L4 Graph Context (1-hop)\n"]
 hop2 = ["## L4 Graph Context (2-hop)\n"]
 if not layer.items:
 hop1.append("(no graph expansion results)")
 return "\n".join(hop1), ""
 has_hop1 = False
 has_hop2 = False
 for item in layer.items:
 sym = item["symbol"]
 depth = item["depth"]
 rel = item["relationship"]
 line = f"- `{sym.name}` ({sym.symbol_type}) depth={depth} relation={rel}\n"
 if depth == 1:
 hop1.append(line)
 has_hop1 = True
 elif depth == 2:
 hop2.append(line)
 has_hop2 = True
 if not has_hop1:
 hop1.append("(no 1-hop neighbors)")
 if not has_hop2:
 hop2.append("(no 2-hop neighbors)")
 return "\n".join(hop1), "\n".join(hop2) if has_hop2 else ""
 @staticmethod
 def _format_l3_section(items: list[dict[str, Any]]) -> str:
 """格式化 L3 混合搜索 section。"""
 lines = ["## L3 Related Code\n"]
 if not items:
 lines.append("(no hybrid search results)")
 else:
 for item in items:
 payload = item.get("payload", {})
 fp = payload.get("file_path", "unknown")
 score = item.get("score", 0.0)
 content = payload.get("content", "")
 lines.append(f"### {fp} (score: {score:.3f})\n```\n{content}\n```\n")
 return "\n".join(lines)
 @staticmethod
 def _filter_l3_dedup(l3_layer: LayerResult, l2_layer: LayerResult) -> list[dict[str, Any]]:
 """从 L3 结果中排除已被 L2 精确匹配覆盖的文件。"""
 l2_files = {item.get("file_path", "") for item in l2_layer.items}
 return [
 item for item in l3_layer.items
 if item.get("payload", {}).get("file_path", "") not in l2_files
 ]
 @staticmethod
 def _trim_to_token_budget(text: str, budget: int, enc: Any) -> str:
 """按 token 预算裁剪文本，保持 markdown 结构完整。"""
 lines = text.split("\n")
 result: list[str] =
 used = 0
 for line in lines:
 line_tokens = len(enc.encode(line + "\n"))
 if used + line_tokens > budget:
 result.append(f"(truncated: {len(lines) - len(result)} lines omitted)")
 break
 result.append(line)
 used += line_tokens
 return "\n".join(result)
__all__ = ["LayeredSearchService", "LayeredSearchResult", "LayerResult"]
