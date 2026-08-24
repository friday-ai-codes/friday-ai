"""HybridSearchService 编排器（per implementation）。

implementation 落地骨架（``HybridSearchService.__init__`` + ``search`` 分发入口 +
``_search_rag_only`` NullProvider 路径）保持 byte-for-byte 等价；implementation
将 ``_search_graph_capable`` 重写为真正的 GraphRAG 编排器：

- **wave 并发**：``asyncio.gather(rag_task, symbol_task, return_exceptions=True)``
  让 RAG 召回与符号查找并发执行；rag_task 失败 → 直接 raise（RAG 主线必选项），
  symbol_task 失败 → log warning + 降级到 ``symbol_results=[]``（图谱 enrichment
  是优化项，可降级）。**注意**：与 contract "return_exceptions=False" 字面冲突——本
  plan 改 True 实现差异化降级，记录在 plan deviations 中。
- **一跳 enrichment**：``extract_hop1_neighbors_raw`` 解析 RAG 命中 chunk 的 payload
  ``related_chunks`` + ``resolve_neighbor_metadata`` 单次 ORM ``in_bulk`` 拉
  metadata（plan 落）。
- **二跳 enrichment**：``expand_hop2`` 走 ChunkEdge ORM aiter + 三重去重
  （plan 落）；``enable_graph_enrichment=False`` 时强制走 ``_search_rag_only``
  路径（即使 Provider 支持图谱），完全跳过 wave/1/2 并发 + 图谱 enrichment 链路。
- **HybridBudget 60/40**：``HybridBudget.from_settings().allocate(max_tokens)``
  返回 ``{rag, graph}`` 子预算，``trim_to_budget`` 对 RAG / graph 段分别二次裁剪。
- **graph_context markdown**：``## Graph Context`` 两段（Direct/Indirect Neighbors）
  按 ``- <code>{file_path}:{line}</code> ({edge_type}, w={weight:.2f}): {reason}``
  渲染；空 neighbors → 不写空 markdown 段。
- **structlog wave 日志**：``hybrid_search_wave_started`` / ``hybrid_search_wave_done``
  与 implementation 既有 ``hybrid_search_started`` / ``hybrid_search_completed`` 共存。

**Pitfall 5 守门**：本模块**不读** codegraph 启用开关；图谱启停由
``isinstance(provider, GraphCapableProvider)`` 运行时守卫 +
``enable_graph_enrichment`` 调用方参数控制；CI grep gate
``rg "settings\\.ENABLE_CODEGRAP[H]"`` 必须 0 命中。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

import structlog
from django.conf import settings

from code_relations.cross_repo_expander import expand_cross_repo
from common.logging import redact_secrets_in_text
from services.code_intel.protocols import (
    BaseCodeProvider,
    GraphCapableProvider,
)
from services.exclusion import build_matcher_for_repo, log_exclusion_blocked
from services.retrieval._query_helpers import (
    extract_symbol_keywords,
    format_l3_section,
)
from services.retrieval.budget import HybridBudget
from services.retrieval.find_related import (
    explain_neighbor,
)
from services.retrieval.find_related import (
    find_related as _find_related_impl,
)
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


def _enrichment_reason_fn(
    edge_type: str,
    source_file: str | None,
    target_file: str | None,
    metadata: dict[str, Any],
) -> str:
    """``hop1_reader.resolve_neighbor_metadata`` / ``hop2_expander.expand_hop2``
    注入式 reason 生成器（implementation graph enrichment 路径，work item 升级）。

    完整调用 ``explain_neighbor(edge_type, source_file=..., target_file=...,
    metadata=...)`` 走完整模板路径——CALL/IMPORT 拼 target 文件，CO_CHANGED 拼
    commit_count，SEMANTIC 拼 similarity 等核心信号——与 ``find_related`` Python
    API 路径产物质量一致（work item 之前两条调用路径产物分裂）。

    Note:
        hop1 路径 ``edge_metadata`` 由 payload `related_chunks` 解析得来，当前
        payload 写入仅 3-tuple（不带 metadata），实际值为空 dict——CO_CHANGED /
        SEMANTIC 仍走"recent history" / 缺 score 的降级模板。implementation 增量同步
        若扩 payload 为 4-tuple 则自动透出。hop2 路径 ``edge_metadata`` 来自
        ``ChunkEdge.metadata``（fetch_hop2_edges 已扩 5-tuple），完整可用。
    """
    return explain_neighbor(
        edge_type,
        source_file=source_file,
        target_file=target_file,
        metadata=metadata,
    )


def _render_neighbor_line(neighbor: NeighborMetadata) -> str:
    """单个 NeighborMetadata → markdown 一行（per contract）。

    格式：``- `{file_path}:{line_start}` ({edge_type}, w={weight:.2f}): {reason}``

    - ``file_path == "<unknown>"`` → 跳过（hop1_reader ChunkRegistry 缺失 fallback）；
      调用方 ``_render_graph_context`` 负责过滤。
    - ``line_start is None`` → 省略行号（``:`` 后缀也省）。
    """
    if neighbor.line_start is None:
        location = f"`{neighbor.file_path}`"
    else:
        location = f"`{neighbor.file_path}:{neighbor.line_start}`"
    return f"- {location} ({neighbor.edge_type}, w={neighbor.weight:.2f}): {neighbor.reason}"


def _render_graph_context(
    hop1: list[NeighborMetadata],
    hop2: list[NeighborMetadata],
    cross_repo: list[NeighborMetadata] | None = None,
) -> str:
    """拼装 ``## Graph Context`` markdown（per contract + implementation cross-repo 段）。

    - 三段：``### Direct Neighbors (1-hop)`` / ``### Indirect Neighbors (2-hop)``
      / ``### Cross-Repo Neighbors (API-Calls)``（implementation 新增，per work item）
    - 邻居按 weight desc 排序
    - 过滤 ``file_path == "<unknown>"`` 的占位行（ChunkRegistry 缺失 fallback）
    - 全部空 → 返回 ``""``（**不写空 markdown 块**，避免污染 LLM 上下文）
    - 仅渲染非空段
    """

    def _filtered_sorted(items: list[NeighborMetadata]) -> list[NeighborMetadata]:
        valid = [n for n in items if n.file_path != "<unknown>"]
        return sorted(valid, key=lambda n: -n.weight)

    h1 = _filtered_sorted(hop1)
    h2 = _filtered_sorted(hop2)
    cr = _filtered_sorted(cross_repo or [])

    if not h1 and not h2 and not cr:
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
    if cr:
        sections.append("### Cross-Repo Neighbors (API-Calls)")
        sections.append("")
        sections.extend(_render_neighbor_line(n) for n in cr)
        sections.append("")
    return "\n".join(sections).rstrip()


async def _build_is_excluded_path(repo_ids: list[str]):
    """合成跨 repo 的排除判定回调（EXCL-02 图谱邻居 fail-closed 过滤）。

    邻居 metadata 不带 repository_id 归属，故对传入的 repo_ids 逐一取匹配器，
    ``is_excluded_path(file_path)`` 对任一 repo 命中即剔除（any 命中，fail-closed）。
    某 repo 匹配器构造失败 → 用 None 占位，判定时一律视为命中（fail-closed，
    宁可多排不可漏），绝不放行被排除路径。
    """
    matchers: list[Any] = []
    for rid in repo_ids:
        try:
            matchers.append(await build_matcher_for_repo(rid))
        except Exception:  # noqa: BLE001 — 构造失败一律 fail-closed
            logger.debug(
                "hybrid_search_matcher_build_failed",
                repo_id=rid,
                category="sampling",
                component="code_graph",
            )
            matchers.append(None)

    def _is_excluded(file_path: str) -> bool:
        for m in matchers:
            if m is None:
                return True  # 匹配器缺失 → fail-closed
            try:
                if m.is_excluded(file_path):
                    return True
            except Exception:  # noqa: BLE001 — 判定异常 → fail-closed
                return True
        return False

    return _is_excluded


def _filter_excluded_neighbors(
    neighbors: list[NeighborMetadata],
    is_excluded_path,
    *,
    repo_ids: list[str],
) -> list[NeighborMetadata]:
    """剔除命中排除规则的邻居（fail-closed）；命中即 log exclusion.blocked。"""
    kept: list[NeighborMetadata] = []
    for n in neighbors:
        if is_excluded_path(n.file_path):
            log_exclusion_blocked(
                surface="rag",
                repository_id=",".join(repo_ids),
                rel_path=str(n.file_path),
            )
            continue
        kept.append(n)
    return kept


class HybridSearchService:
    """RAG 主线 + 图谱编排器（per contract / contract）。

    与 ``LayeredSearchService``（@classmethod 风格）不同，本类是**实例**风格，
    通过 ``__init__(provider)`` 显式注入 ``BaseCodeProvider``（per Pitfall 5
    + contract/contract/contract：调用方负责拿 provider，本类不读 settings）。

    标准用法::

        from services.code_intel import get_provider
        from services.retrieval import HybridSearchService

        svc = HybridSearchService(get_provider())
        result = await svc.search("user login", repository_ids=["repo-a"])
    """

    def __init__(self, provider: BaseCodeProvider) -> None:
        """显式注入 Provider 实例。

        Args:
            provider: 实现 ``BaseCodeProvider`` Protocol 的实例（NullProvider /
                LocalProvider / 后续 RemoteProvider）。

        Raises:
            TypeError: provider 未实现 ``BaseCodeProvider`` Protocol（per
                security mitigation 防御任意 duck-type 对象绕过）。
        """
        if not isinstance(provider, BaseCodeProvider):
            raise TypeError(
                f"provider must implement BaseCodeProvider Protocol; got {type(provider).__name__}",
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
            project_id: 项目 id（暂未使用，保签名兼容 plan callsite）。
            branch_name: 分支名（透传到 BranchAwareSearchService）。
            max_tokens: token 预算上限（默认 8000，与 LayeredSearchService 对齐）。
            top_k: 返回的最大条数（默认 30）。
            enable_graph_enrichment: 是否启用图谱 enrichment（默认 True）。
                False 时强制走 ``_search_rag_only`` 路径，即使 Provider 支持图谱。
                供 callsite 在不需要二跳扩散时主动短路。

                **implementation contract 入口守卫**：本方法在分发前与
                ``settings.ENABLE_GRAPHRAG_ENRICHMENT`` AND 合并，任一为 False
                即强制 ``_search_rag_only``（byte-equivalent implementation 路径）。
                这是 contract / CONTEXT.md 关键不变量**唯一允许**的
                ``settings.ENABLE_GRAPHRAG_ENRICHMENT`` 直读点；新增直读点应
                在 PR review 拒绝。

        Returns:
            - GraphCapable 路径 + caller=True + settings=True → ``HybridSearchResult``
              （含 ``graph_context`` / ``hop1_neighbors`` / ``hop2_neighbors`` 三字段）
            - 其余路径 → ``RagSearchResult``（字段同名同序兼容 callsite）
        """
        # implementation contract 守卫：``settings.ENABLE_GRAPHRAG_ENRICHMENT`` 的**唯一**
        # 直读点。work item 修复（implementation REVIEW）：原本方法体内 lazy import 是冗余
        # 防御——``services.retrieval.budget`` 已在 module-level ``from django.conf
        # import settings``（且 hybrid_search 顶层 import budget），加载顺序在
        # module load 时已确定。``getattr`` 兜底保留覆盖 minimal test settings
        # 缺该 attr 的场景。
        effective_enrichment: bool = enable_graph_enrichment and bool(
            getattr(settings, "ENABLE_GRAPHRAG_ENRICHMENT", True)
        )

        if effective_enrichment and isinstance(self._provider, GraphCapableProvider):
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

    async def _run_wave_0(
        self,
        query: str,
        *,
        repo_ids: list[str],
        branch_name: str | None,
        top_k: int,
    ) -> tuple[LayerSnapshot, list[dict[str, Any]], bool, int]:
        """contract 提取：wave 并发 RAG 召回 + 符号查找 + 异常分发。

        Returns:
            ``(rag_snapshot, symbol_results, symbol_failed, wave_0_elapsed_ms)``。

        Raises:
            BaseException: rag_task 失败时直接传播（RAG 主线必选项）。
        """
        keywords: list[str] = extract_symbol_keywords(query)

        logger.debug(
            "hybrid_search_wave_started",
            wave_id=0,
            wave_0_tasks=["rag", "symbol"],
            category="sampling",
            component="code_graph",
        )
        t0 = time.perf_counter()
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
        # 透传 branch_name 让 symbol lookup 做 base/overlay 合并。
        symbol_task = asyncio.create_task(
            self._provider.lookup_symbols(  # type: ignore[attr-defined]
                keywords,
                repository_ids=repo_ids,
                branch_name=branch_name,
            ),
        )
        results = await asyncio.gather(
            rag_task,
            symbol_task,
            return_exceptions=True,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.debug(
            "hybrid_search_wave_done",
            wave_id=0,
            elapsed_ms=elapsed_ms,
            category="sampling",
            component="code_graph",
        )

        rag_result = results[0]
        if isinstance(rag_result, BaseException):
            logger.debug(
                "rag_task_failed",
                error=redact_secrets_in_text(str(rag_result)),
                error_type=type(rag_result).__name__,
                category="sampling",
                component="code_graph",
            )
            raise rag_result

        symbol_result = results[1]
        symbol_failed: bool = False
        symbol_results: list[dict[str, Any]]
        if isinstance(symbol_result, BaseException):
            logger.debug(
                "symbol_task_failed",
                error=redact_secrets_in_text(str(symbol_result)),
                error_type=type(symbol_result).__name__,
                category="sampling",
                component="code_graph",
            )
            symbol_results = []
            symbol_failed = True
        else:
            symbol_results = list(symbol_result) if symbol_result else []

        return rag_result, symbol_results, symbol_failed, elapsed_ms

    @staticmethod
    async def _run_wave_1(
        rag_snapshot: LayerSnapshot,
    ) -> tuple[list[NeighborMetadata], set[str]]:
        """contract 提取：wave 一跳 enrichment（payload 直读 + 单次 ORM in_bulk）。"""
        raw_h1 = extract_hop1_neighbors_raw(rag_snapshot.items)
        hop1_neighbors: list[NeighborMetadata] = await resolve_neighbor_metadata(
            raw_h1,
            hop=1,
            reason_fn=_enrichment_reason_fn,
        )
        hop1_chunk_ids: set[str] = {n.chunk_id for n in hop1_neighbors}
        return hop1_neighbors, hop1_chunk_ids

    @staticmethod
    async def _run_wave_2(
        *,
        hop1_chunk_ids: set[str],
        rag_chunk_ids: set[str],
        repo_ids: list[str],
        branch_name: str | None = None,
    ) -> list[NeighborMetadata]:
        """contract 提取：wave 二跳 enrichment（ChunkEdge ORM aiter + 三重去重）。

        ``branch_name`` 透传给 ``expand_hop2`` → ``fetch_hop2_edges``
        做 base/overlay 合并。注意 hop2 读**已建 ChunkEdge**（含 SEMANTIC 边），
        ``branch_name__in=["", eff]`` 合并 base+feature 已落库的边，**非重新向量
        检索**，不受 294 跨 collection 向量限制（边已落库，OQ4 裁定）。
        """
        return await expand_hop2(
            hop1_chunk_ids=hop1_chunk_ids,
            rag_chunk_ids=rag_chunk_ids,
            repo_ids=repo_ids,
            reason_fn=_enrichment_reason_fn,
            branch_name=branch_name,
        )

    @staticmethod
    async def _run_wave_3(
        *,
        rag_snapshot: LayerSnapshot,
        repo_ids: list[str],
        exclude_chunk_ids: frozenset[str],
    ) -> list[NeighborMetadata]:
        """contract 提取：wave 跨仓 API 扩散（ApiCallSite ↔ Endpoint via CrossRepoApiCall）。

        implementation 新增 wave。调用方负责 ENABLE_CROSS_REPO_ENRICHMENT 守卫——
        本方法不读 settings（per Pitfall 5 原则）。
        """
        return await expand_cross_repo(
            rag_items=rag_snapshot.items,
            repo_ids=repo_ids,
            reason_fn=_enrichment_reason_fn,
            exclude_chunk_ids=exclude_chunk_ids,
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
        warning + symbol_results=[] + 仍走 rag 路径（图谱 enrichment 降级）；
        rag_snapshot.status != "ok" → 短路返回空 HybridSearchResult（work item 与
        ``_search_rag_only`` 行为对齐）。

        contract: 拆分为 ``_run_wave_0`` / ``_run_wave_1`` / ``_run_wave_2`` 三个
        helper，让单方法关注顶层编排（短路决策 + budget 切分 + markdown 拼装）。
        """
        _ = project_id  # 保签名兼容 plan callsite

        logger.debug(
            "hybrid_search_started",
            path="graph_capable",
            category="sampling",
            component="code_graph",
        )

        repo_ids: list[str] = list(repository_ids or [])
        budgets: dict[str, int] = HybridBudget.from_settings().allocate(max_tokens)

        rag_snapshot, symbol_results, symbol_failed, wave_0_ms = await self._run_wave_0(
            query,
            repo_ids=repo_ids,
            branch_name=branch_name,
            top_k=top_k,
        )

        if rag_snapshot.status != "ok" or not rag_snapshot.items:
            logger.debug(
                "hybrid_search_completed",
                path="graph_capable",
                repo_count=len(repo_ids),
                l3_status=rag_snapshot.status,
                l3_error=redact_secrets_in_text(str(rag_snapshot.error or "")),
                total_tokens=0,
                hop1_count=0,
                hop2_count=0,
                symbol_count=len(symbol_results),
                symbol_failed=symbol_failed,
                wave_0_elapsed_ms=wave_0_ms,
                category="sampling",
                component="code_graph",
            )
            return HybridSearchResult(
                query=query,
                repository_ids=repo_ids,
                layers=[rag_snapshot],
                final_context="",
                total_tokens=0,
            )

        rag_chunk_ids: set[str] = {
            str(item.get("id")) for item in rag_snapshot.items if item.get("id")
        }

        hop1_neighbors, hop1_chunk_ids = await self._run_wave_1(rag_snapshot)
        # hop1 经 RAG collection 路由 + ChunkRegistry.in_bulk PK 命名空间隔离，已
        # 隐式 branch-aware，故 hop1_reader 不加冗余 branch 过滤（研究 §2.2 YAGNI）。
        hop2_neighbors = await self._run_wave_2(
            hop1_chunk_ids=hop1_chunk_ids,
            rag_chunk_ids=rag_chunk_ids,
            repo_ids=repo_ids,
            branch_name=branch_name,
        )

        # --- wave: 跨仓 API 扩散（implementation）---
        # ENABLE_CROSS_REPO_ENRICHMENT 唯一直读点（hybrid_search 模块）。
        enable_cross: bool = bool(getattr(settings, "ENABLE_CROSS_REPO_ENRICHMENT", True))
        if enable_cross:
            logger.debug(
                "hybrid_search_wave_started",
                wave_id=3,
                category="sampling",
                component="code_graph",
            )
            t3 = time.perf_counter()
            cross_repo_neighbors: list[NeighborMetadata] = await self._run_wave_3(
                rag_snapshot=rag_snapshot,
                repo_ids=repo_ids,
                exclude_chunk_ids=frozenset(hop1_chunk_ids | rag_chunk_ids),
            )
            elapsed_3ms = int((time.perf_counter() - t3) * 1000)
            logger.debug(
                "hybrid_search_wave_done",
                wave_id=3,
                elapsed_ms=elapsed_3ms,
                count=len(cross_repo_neighbors),
                category="sampling",
                component="code_graph",
            )
        else:
            cross_repo_neighbors = []

        # EXCL-02 fail-closed：图谱邻居（hop1/hop2/cross-repo）渲染前剔除被排除 file_path。
        # 邻居源自 Qdrant/ChunkEdge 残留数据，即便存量未清（Phase 23）读取面也绝不暴露。
        is_excluded_path = await _build_is_excluded_path(repo_ids)
        hop1_neighbors = _filter_excluded_neighbors(
            hop1_neighbors, is_excluded_path, repo_ids=repo_ids
        )
        hop2_neighbors = _filter_excluded_neighbors(
            hop2_neighbors, is_excluded_path, repo_ids=repo_ids
        )
        cross_repo_neighbors = _filter_excluded_neighbors(
            cross_repo_neighbors, is_excluded_path, repo_ids=repo_ids
        )

        graph_context_raw: str = _render_graph_context(
            hop1_neighbors, hop2_neighbors, cross_repo_neighbors
        )
        l3_markdown: str = format_l3_section(rag_snapshot.items)
        rag_section: str = trim_to_budget(l3_markdown, budgets["rag"])
        graph_section: str = (
            trim_to_budget(graph_context_raw, budgets["graph"]) if graph_context_raw else ""
        )

        # 无 graph_section 时保 rag_section 原貌（含 trim_to_budget 产出的尾换行），
        # 与 _search_rag_only 路径 byte-equal —— 兑现 implementation byte-eq 承诺（implementation 提前）
        if graph_section:
            final_context = f"{rag_section.rstrip()}\n\n{graph_section}".rstrip()
        else:
            final_context = rag_section
        total_tokens: int = estimate_tokens(final_context)

        logger.debug(
            "hybrid_search_completed",
            path="graph_capable",
            repo_count=len(repo_ids),
            total_tokens=total_tokens,
            hop1_count=len(hop1_neighbors),
            hop2_count=len(hop2_neighbors),
            cross_repo_count=len(cross_repo_neighbors),
            symbol_count=len(symbol_results),
            symbol_failed=symbol_failed,
            wave_0_elapsed_ms=wave_0_ms,
            category="sampling",
            component="code_graph",
        )
        return HybridSearchResult(
            query=query,
            repository_ids=repo_ids,
            layers=[rag_snapshot],
            final_context=final_context,
            total_tokens=total_tokens,
            graph_context=graph_section,
            hop1_neighbors=hop1_neighbors,
            hop2_neighbors=hop2_neighbors,
            cross_repo_neighbors=cross_repo_neighbors,
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

        per security mitigation：不触 SymbolService / GraphExpansionService，
        capability 守卫（``isinstance(provider, GraphCapableProvider)`` False）
        已在 search 入口完成。

        **implementation zero-drift 守门**：本方法 byte-for-byte 等价 implementation
        实现，既有 NullProvider 路径测试（test_hybrid_skeleton + test_null_provider_paths)
        必须全绿。
        """
        logger.debug(
            "hybrid_search_started",
            path="rag_only",
            category="sampling",
            component="code_graph",
        )

        repo_ids: list[str] = list(repository_ids or [])
        l3: LayerSnapshot = await search_rag(
            query,
            repo_ids=repo_ids,
            branch_name=branch_name,
            top_k=top_k,
        )

        if l3.status != "ok" or not l3.items:
            logger.debug(
                "hybrid_search_completed",
                path="rag_only",
                repo_count=len(repo_ids),
                l3_status=l3.status,
                total_tokens=0,
                category="sampling",
                component="code_graph",
            )
            return RagSearchResult(
                query=query,
                repository_ids=repo_ids,
                layers=[l3],
                final_context="",
                total_tokens=0,
            )

        # 复用 services.retrieval._query_helpers.format_l3_section 保格式 idiom 一致：
        # `## L3 Related Code\n\n### {file_path} (score: {score:.3f})\n```\n{content}\n```\n`
        l3_markdown: str = format_l3_section(l3.items)
        budgets: dict[str, int] = split_budget(max_tokens, ratios={"rag": 1.0})
        final_context: str = trim_to_budget(l3_markdown, budgets["rag"])
        total_tokens: int = estimate_tokens(final_context)

        logger.debug(
            "hybrid_search_completed",
            path="rag_only",
            repo_count=len(repo_ids),
            total_tokens=total_tokens,
            category="sampling",
            component="code_graph",
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

    async def find_related(
        self,
        start_chunk_id: str,
        *,
        repo_ids: list[str],
        relation_types: list[str] | None = None,
        hops: int = 1,
        direction: Literal["downstream", "upstream", "both"] = "both",
        limit: int = 20,
    ) -> list[NeighborMetadata]:
        """implementation MCP tool 直接调用入口（success criteria）。

        Thin wrapper：delegate 到 ``services.retrieval.find_related.find_related``
        模块级函数。**不做** ``isinstance(provider, GraphCapableProvider)`` 守卫——
        find_related 直接查 ChunkEdge ORM，不依赖 Provider；NullProvider 实例
        调本方法依然可拿到 ChunkEdge 数据（implementation notes："任何 provider
        调 find_related 都能拿到 ChunkEdge 数据"）。如需限制，implementation MCP tool
        在外层加 Pydantic schema + capability 守卫。

        Args:
            start_chunk_id: 起点 chunk_id（UUID 字符串）。
            repo_ids: 候选仓库 ID 列表；空 → ``[]``。
            relation_types: 限定 ``EdgeType`` 列表；``None`` 或 ``[]`` → 不过滤。
            hops: 跳数 0..MAX_HOPS=2；越界 → ``ValueError``。
            direction: ``"downstream"`` / ``"upstream"`` / ``"both"``。
            limit: 输出邻居数上限。

        Returns:
            ``list[NeighborMetadata]`` 按 ``(hop ASC, weight DESC)`` 排序。

        Raises:
            ValueError: ``hops`` 越界或 ``direction`` 非三选一。
        """
        return await _find_related_impl(
            start_chunk_id,
            repo_ids=repo_ids,
            relation_types=relation_types,
            hops=hops,
            direction=direction,
            limit=limit,
        )


__all__ = ["HybridSearchService"]
