"""二跳邻居 ORM 扩散器（per Phase Plan / / ）。
兑现 ROADMAP 第二条 + 第三条：
- ** 二跳 ORM**：``ChunkEdge.objects.filter(repository_id__in=repo_ids,
 source_chunk_id__in=hop1_chunk_ids).only(4 字段).order_by('-weight')[:50]``
 异步 aiter 单次拉满；命中 ``(repository, source_chunk_id)`` 复合索引；不允许
 in-loop ORM。
- ** MAX_HOPS=2 硬上限**：``assert_hops_within_limit(hops)`` 在 hops > 2
 立即抛 ``ValueError``——防 LLM 通过 MCP tool 传 hops=10 引发指数级查询；
 hops < 0 同样拒绝。
- **三重去重**：``expand_hop2`` 拼装 NeighborMetadata 列表前，过滤
 ``target ∈ hop1_chunk_ids ∪ rag_chunk_ids ∪ {source}``——防 graph_context 与
 rag_context 重复消耗 token budget；保证二跳邻居总是"新增信息"。
- **TOP_NEIGHBORS_PER_HOP2=50**：DB 层 LIMIT 50（per source 总和，非 per-source
 cap，per D-Deviation 1）；超限即记录 ``capped=True`` log。
**不读** codegraph 启用开关（Pitfall 5）：本模块只做 ORM 扩散与三重去重；启停
决策由 Plan 的 ``HybridSearchService`` 通过 Provider 注入处理；CI 守护
``rg "settings\\.ENABLE_CODEGRAP[H]" services/retrieval/`` 必须 0 命中。
"""
from __future__ import annotations
from typing import Any, Literal
import structlog
from code_relations.constants import MAX_HOPS, TOP_NEIGHBORS_PER_HOP2
from services.retrieval.hop1_reader import ReasonFn, resolve_neighbor_metadata
from services.retrieval.types import NeighborMetadata
__all__ = [
 "assert_hops_within_limit",
 "expand_hop2",
 "fetch_hop2_edges",
]
logger = structlog.get_logger(__name__)
def assert_hops_within_limit(hops: int) -> None:
 """校验 ``hops`` 处于 [0, MAX_HOPS=2] 闭区间。
 Args:
 hops: 待校验跳数（由 Plan ``find_related`` API / MCP tool 透传）。
 Raises:
 ValueError: ``hops > MAX_HOPS`` 或 ``hops < 0``。错误信息同时包含
 实际值与 ``MAX_HOPS`` / ``non-negative`` 关键字便于 LLM 错误恢复。
 Examples:
 >>> assert_hops_within_limit(2) # OK
 >>> assert_hops_within_limit(3)
 Traceback (most recent call last):
 ...
 ValueError: hops=3 exceeds MAX_HOPS=2; supported range is [0, 2]
 """
 if hops < 0:
 raise ValueError(
 f"hops={hops} must be non-negative; supported range is [0, {MAX_HOPS}]"
 )
 if hops > MAX_HOPS:
 raise ValueError(
 f"hops={hops} exceeds MAX_HOPS={MAX_HOPS}; supported range is [0, {MAX_HOPS}]"
 )
async def fetch_hop2_edges(
 hop1_chunk_ids: list[str],
 repo_ids: list[str],
 *,
 relation_types: list[str] | None = None,
 direction: Literal["downstream", "upstream"] = "downstream",
) -> list[tuple[str, str, str, float, dict[str, Any]]]:
 """单次 ChunkEdge ORM 拉边，返回二跳候选 (source, target, edge_type, weight, metadata)。
 Args:
 hop1_chunk_ids: 一跳邻居 chunk_id 集合：
 - ``direction='downstream'``：作为 ``source_chunk_id__in``（默认，
 命中 ``idx_chunkedge_fanout`` 复合索引）；
 - ``direction='upstream'``：作为 ``target_chunk_id__in``（命中
 ``idx_chunkedge_target`` 反向索引），用于 ``find_related`` upstream
 hops=2 拿"调用者的调用者"（per ）。
 repo_ids: 仓库 ID 列表。
 relation_types: ``EdgeType`` 过滤列表，**ORM 层下推**（避免
 Python 端在 ``[:50]`` 之后过滤导致命中率严重下降）。``None`` 或空
 list → 不过滤。
 direction: ``"downstream"`` (默认) 或 ``"upstream"``，决定
 ``hop1_chunk_ids`` 在 ``filter`` 中的字段方向。
 Returns:
 ``list[(source, target, edge_type, weight, metadata)]``——5-tuple
 包含 ``ChunkEdge.metadata``，按 weight desc 排序，长度 ≤
 ``TOP_NEIGHBORS_PER_HOP2=50``：
 - ``hop1_chunk_ids`` 为空 或 ``repo_ids`` 为空 → 立即返回 ````，
 **零 SQL 查询**（fast-path 早返）；
 - structlog ``hop2_edges_fetched`` 事件含 ``repo_count`` / ``source_count``
 / ``edge_count`` / ``capped`` / ``direction``。
 **零 N+1**：仅一次 SQL（``CaptureQueriesContext`` 守护）。
 """
 if not hop1_chunk_ids or not repo_ids:
 return
 from code_relations.models import ChunkEdge
 base = ChunkEdge.objects.filter(repository_id__in=repo_ids)
 if direction == "upstream":
 base = base.filter(target_chunk_id__in=hop1_chunk_ids)
 else:
 base = base.filter(source_chunk_id__in=hop1_chunk_ids)
 if relation_types:
 base = base.filter(edge_type__in=relation_types)
 qs = base.only(
 "source_chunk_id", "target_chunk_id", "edge_type", "weight", "metadata"
 ).order_by("-weight")
 out: list[tuple[str, str, str, float, dict[str, Any]]] =
 async for edge in qs[:TOP_NEIGHBORS_PER_HOP2]:
 out.append(
 (
 str(edge.source_chunk_id),
 str(edge.target_chunk_id),
 str(edge.edge_type),
 float(edge.weight),
 dict(edge.metadata or {}),
 )
 )
 capped = len(out) >= TOP_NEIGHBORS_PER_HOP2
 logger.info(
 "hop2_edges_fetched",
 repo_count=len(repo_ids),
 source_count=len(hop1_chunk_ids),
 edge_count=len(out),
 capped=capped,
 direction=direction,
 )
 return out
async def expand_hop2(
 *,
 hop1_chunk_ids: set[str],
 rag_chunk_ids: set[str],
 repo_ids: list[str],
 reason_fn: ReasonFn,
) -> list[NeighborMetadata]:
 """二跳扩散主入口：fetch 边 + 三重去重 + ChunkRegistry metadata 拼装。
 Args:
 hop1_chunk_ids: 一跳邻居集合（作为二跳 source，也作为三重去重 reject set）。
 rag_chunk_ids: RAG 召回 chunk_id 集合（防 graph 与 rag 重复消耗 budget）。
 repo_ids: 候选仓库 ID 列表。
 reason_fn: ``ReasonFn`` —— ``(edge_type, source_file, target_file,
 edge_metadata) -> str``， 升级后透传完整 template 上下文。
 Returns:
 ``list[NeighborMetadata]``：
 - ``hop=2`` 固定标注；
 - 已过滤 ``target ∈ hop1_chunk_ids ∪ rag_chunk_ids ∪ {source}``；
 - 同 (target, edge_type) 跨 source 合并保 ``max(weight)``（由
 ``resolve_neighbor_metadata`` 复用逻辑覆盖）；
 - 排序与 ``resolve_neighbor_metadata`` 输出一致（不保证 weight desc——
 字典遍历顺序，由 Plan 编排器最终统一 sort）。
 **性能**：单次 ChunkEdge ORM（``fetch_hop2_edges``）+ 单次 ChunkRegistry
 ``in_bulk``（``resolve_neighbor_metadata``）= 至多 2 次 SQL。
 """
 edges = await fetch_hop2_edges(list(hop1_chunk_ids), repo_ids)
 if not edges:
 return
 # 三重去重 reject set：合并 hop1 + rag，per source 自环单独判断
 # hop1_chunk_ids / rag_chunk_ids 已是 set，直接 union 后 frozenset 一次拷贝即可
 reject: frozenset[str] = frozenset(hop1_chunk_ids | rag_chunk_ids)
 # 按 source 分组（resolve_neighbor_metadata 签名要求
 # ``dict[source_chunk_id, list[(target, edge_type, weight, metadata)]]``）
 by_source: dict[str, list[tuple[str, str, float, dict[str, Any]]]] = {}
 for src, tgt, edge_type, weight, edge_metadata in edges:
 if tgt in reject:
 continue
 if tgt == src:
 # 自环边："自环不传递信息"（per D-Deviation 3）
 continue
 by_source.setdefault(src, ).append((tgt, edge_type, weight, edge_metadata))
 if not by_source:
 return
 return await resolve_neighbor_metadata(by_source, hop=2, reason_fn=reason_fn)
