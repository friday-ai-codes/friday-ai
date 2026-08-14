"""``LayeredSearchService`` — implementation deprecated thin wrapper（contract / contract）。

implementation 之前本模块承载五层检索（L1 RepoRouting → L5 ContextReassembly）的完整编排
逻辑；implementation 解耦后业务入口统一改为 :class:`services.retrieval.HybridSearchService`。
为保 contract 保留组旧测试（``tests/codegraph/test_layered_search.py`` 等 5 个文件）
**零修改**继续全绿、并锁 golden snapshot 20/20 零漂移，本文件物理保留：

1. 公共符号 ``LayeredSearchService`` / ``LayeredSearchResult`` / ``LayerResult``
   - ``LayerResult`` / ``LayeredSearchResult`` 改为 :mod:`services.retrieval.types`
     的 ``LayerSnapshot`` / ``RagSearchResult`` **别名**（同一 class，``isinstance``
     检查零修改通过；字段完全 1:1）。
2. 5 个私有 ``_l1_repo_routing`` / ``_l2_symbol_lookup`` / ``_l3_hybrid_search`` /
   ``_l4_graph_expansion`` / ``_l5_context_reassembly`` classmethod **行为不变**，
   ``services.retrieval.hybrid_search.HybridSearchService`` GraphCapable 路径**内联**
   调用它们（断开 ``LayeredSearchService.search`` ↔ ``HybridSearchService.search``
   循环 delegate；CI gate ``rg "LayeredSearchService\\.search" server/services/retrieval/``
   必须 0 命中）。
3. 全部格式化辅助方法 + ``_KEYWORDS`` + ``_extract_symbol_names`` 不动（contract 测试
   直接 patch/调用，且 ``HybridSearchService`` NullProvider 路径也复用 ``_format_l3_section``）。

**入口 thin delegate**：``LayeredSearchService.search()`` 改为单行
``HybridSearchService(get_provider()).search(...)``；模块加载即触发
``DeprecationWarning``（``stacklevel=2`` 指向 importer），下个 checkpoint 物理删除。

Per contract / contract / contract / implementation Success Criteria #1。
"""

from __future__ import annotations

import re
import time
import warnings
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.retrieval.token_budget import estimate_tokens, trim_to_budget
from services.retrieval.types import LayerSnapshot as LayerResult
from services.retrieval.types import RagSearchResult as LayeredSearchResult

logger = structlog.get_logger(__name__)

warnings.warn(
    "codegraph.services.layered_search.LayeredSearchService is deprecated; "
    "use services.retrieval.HybridSearchService(get_provider()).search(...) instead. "
    "Will be removed next checkpoint (per implementation contract / contract).",
    DeprecationWarning,
    stacklevel=2,
)


class LayeredSearchService:
    """五层检索 deprecated thin wrapper —— per contract / contract。

    ``search()`` 入口直接 delegate 到 :class:`services.retrieval.HybridSearchService`；
    5 个私有 classmethod 物理保留为 module-internal helper，``HybridSearchService``
    GraphCapable 路径内联调用，避免循环回路（per hard_constraint #2 + security mitigation）。
    """

    DEFAULT_MAX_TOKENS: int = 8000
    TOKEN_BUFFER_RATIO: float = 0.9
    DEFAULT_TOP_K: int = 30
    L4_1HOP_TOKEN_BUDGET: int = 3000
    L3_TOKEN_BUDGET: int = 3000

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
        """Thin delegate 到 ``HybridSearchService(get_provider()).search(...)``.

        Deprecated wrapper 保持旧返回类型：Hybrid 路径显式 downcast 为
        ``LayeredSearchResult``，避免旧 callsite 误消费 graph-only 字段。
        """
        from services.code_intel import get_provider
        from services.retrieval import HybridSearchService
        from services.retrieval.types import HybridSearchResult

        result = await HybridSearchService(get_provider()).search(
            query,
            repository_ids=repository_ids,
            project_id=project_id,
            branch_name=branch_name,
            max_tokens=max_tokens,
            top_k=top_k,
        )
        if isinstance(result, HybridSearchResult):
            return result.to_rag_result()
        return result

    # ------------------------------------------------------------------
    # L1 — Repo Routing (per contract)
    # ------------------------------------------------------------------

    @classmethod
    async def _l1_repo_routing(
        cls, query: str, repository_ids: list[str] | None, top_k: int,
    ) -> tuple[LayerResult, list[str]]:
        """经统一仓库路由服务确定搜索目标仓库集合。"""
        if repository_ids:
            return (
                LayerResult(layer="L1", status="skipped", result_count=len(repository_ids)),
                repository_ids,
            )
        started = time.perf_counter()
        try:
            from codegraph.services.repo_router_v2 import RepoRouterV2

            route_result = await RepoRouterV2.route(
                query, top_k=min(top_k, 5), use_llm=False,
            )
            repo_ids = [candidate.repo_id for candidate in route_result.candidates]
            items = [
                {
                    "repo_id": candidate.repo_id,
                    "repo_name": candidate.repo_name,
                    "score": candidate.score,
                    "match_reason": candidate.reasoning,
                    "router_version": route_result.router_version,
                    "degraded": route_result.degraded,
                }
                for candidate in route_result.candidates
            ]
            try:
                logger.debug(
                    "layered_search_l1_routed",
                    category="sampling",
                    component="retrieval",
                    result_count=len(repo_ids),
                    router_version=route_result.router_version,
                    degraded=route_result.degraded,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            except Exception:  # noqa: BLE001
                pass
            return LayerResult(layer="L1", status="ok", result_count=len(repo_ids), items=items), repo_ids
        except Exception as e:
            from common.logging import redact_secrets_in_text

            logger.warning(
                "layered_search_l1_routing_failed",
                category="sampling",
                component="retrieval",
                query_len=len(query or ""),
                error=redact_secrets_in_text(str(e)),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            # 降级: 返回所有已索引仓库
            from repositories.models import IndexStatus, Repository

            repos = await sync_to_async(list)(
                Repository.objects.filter(index_status=IndexStatus.INDEXED, is_deleted=False).values_list("id", flat=True)[:5],
            )
            repo_ids = [str(r) for r in repos]
            return LayerResult(layer="L1", status="error", result_count=len(repo_ids), error=str(e)), repo_ids

    # ------------------------------------------------------------------
    # L2 — Symbol Lookup (per contract)
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
        terms = [t for t in pascal + dotted if t.lower() not in LayeredSearchService._KEYWORDS]
        # 去重保序
        seen: set[str] = set()
        result: list[str] = []
        for t in terms:
            if t.lower() not in seen:
                seen.add(t.lower())
                result.append(t)
        return result[:10]  # 最多 10 个符号名

    @classmethod
    async def _l2_symbol_lookup(cls, query: str, repo_ids: list[str]) -> LayerResult:
        """符号精确匹配：大写开头的类/函数名或点号分隔的标识符。"""
        try:
            terms = cls._extract_symbol_names(query)
            if not terms:
                return LayerResult(layer="L2", status="skipped")

            from codegraph.models import Symbol

            all_symbols: list[Any] = []
            seen_ids: set[str] = set()

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
    # L3 — Hybrid Search (per contract)
    # ------------------------------------------------------------------

    @classmethod
    async def _l3_hybrid_search(
        cls, query: str, repo_ids: list[str], top_k: int, branch_name: str | None,
    ) -> LayerResult:
        """混合向量搜索：对每个路由仓库调用 BranchAwareSearchService。"""
        try:
            from services.branch_search import BranchAwareSearchService

            # 查询收口：长文本切块后取首块向量。BranchAwareSearchService.search
            # 目前只收单向量（分支 overlay/base 扇出后各自查询），多探针需先扩它的
            # 签名——本处至少保证「超长文本不再静默判失败」。
            from services.query_embedding import embed_query
            from services.sparse_encoder import SparseEncoderService

            embedded = await embed_query(query)
            query_dense = embedded.primary
            if not query_dense:
                return LayerResult(layer="L3", status="error", error="embedding generation failed")

            query_sparse: dict[str, Any] | None = await sync_to_async(SparseEncoderService.encode)(query)
            if not query_sparse or not query_sparse.get("indices"):
                query_sparse = None

            all_results: list[dict[str, Any]] = []
            seen_keys: set[tuple[str, str, int]] = set()  # (repo_id, file_path, chunk_index)

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
    # L4 — Graph Expansion (per contract)
    # ------------------------------------------------------------------

    @classmethod
    async def _l4_graph_expansion(cls, l2_symbols: list[dict[str, Any]]) -> LayerResult:
        """图谱扩展：对 L2 匹配符号做图遍历，仅仓库内。"""
        try:
            if not l2_symbols:
                return LayerResult(layer="L4", status="skipped")

            from codegraph.models import Symbol
            from codegraph.services.graph_expansion import GraphExpansionService

            all_nodes: dict[str, dict[str, Any]] = {}  # symbol_id -> node (保留最短 depth)
            all_edges: list[dict[str, Any]] = []

            for sym_info in l2_symbols[:5]:  # 最多对 5 个 L2 符号做扩展
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
                for n in all_nodes.values()
            ]
            return LayerResult(
                layer="L4", status="ok", result_count=len(items), items=items,
                extra={"edge_count": len(all_edges)},
            )
        except Exception as e:
            logger.warning("l4_graph_expansion_failed", error=str(e))
            return LayerResult(layer="L4", status="error", error=str(e))

    # ------------------------------------------------------------------
    # L5 — Context Reassembly (per contract)
    # ------------------------------------------------------------------

    @classmethod
    def _l5_context_reassembly(
        cls, l2_layer: LayerResult, l3_layer: LayerResult,
        l4_layer: LayerResult, max_tokens: int,
    ) -> tuple[str, int]:
        """上下文重组：按优先级裁剪组装 markdown 格式文本。"""
        effective_budget = int(max_tokens * cls.TOKEN_BUFFER_RATIO)  # 7200 for 8000

        sections: list[str] = []

        # L2 节: 精确匹配 (全部保留 — per contract)
        l2_section = cls._format_l2_section(l2_layer)
        sections.append(l2_section)
        current_tokens = estimate_tokens("\n\n".join(sections))

        # L4 节: 1-hop 关系 (子预算 3000)
        l4_hop1_section, l4_hop2_section = cls._format_l4_section_split(l4_layer)
        hop1_tokens = estimate_tokens(l4_hop1_section)
        if hop1_tokens <= cls.L4_1HOP_TOKEN_BUDGET:
            sections.append(l4_hop1_section)
            current_tokens = estimate_tokens("\n\n".join(sections))
        else:
            trimmed_hop1 = trim_to_budget(
                l4_hop1_section, cls.L4_1HOP_TOKEN_BUDGET
            )
            sections.append(trimmed_hop1)
            current_tokens = estimate_tokens("\n\n".join(sections))

        # L3 节: 去重后的 hybrid 结果 (子预算 3000, 排除已被 L2 覆盖的 file_path)
        l3_filtered = cls._filter_l3_dedup(l3_layer, l2_layer)
        l3_section = cls._format_l3_section(l3_filtered)
        l3_tokens = estimate_tokens(l3_section)
        if l3_tokens <= cls.L3_TOKEN_BUDGET:
            sections.append(l3_section)
            current_tokens = estimate_tokens("\n\n".join(sections))
        else:
            trimmed_l3 = trim_to_budget(l3_section, cls.L3_TOKEN_BUDGET)
            sections.append(trimmed_l3)
            current_tokens = estimate_tokens("\n\n".join(sections))

        # L4 节: 2-hop 关系 (使用剩余预算)
        remaining = effective_budget - current_tokens
        if remaining > 200 and l4_hop2_section:  # 至少 200 token 才值得加
            hop2_tokens = estimate_tokens(l4_hop2_section)
            if hop2_tokens <= remaining:
                sections.append(l4_hop2_section)
            else:
                trimmed_hop2 = trim_to_budget(l4_hop2_section, remaining)
                sections.append(trimmed_hop2)

        final_context = "\n\n".join(sections)
        final_tokens = estimate_tokens(final_context)
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
        result: list[str] = []
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
