"""GalaxyAggregator —— 统一聚合 5 类节点 + 7/8 类边为 Galaxy 可视化 payload。

节点类型：
- chunk_registry  → code_relations.ChunkRegistry
- symbol          → codegraph.Symbol
- endpoint        → codegraph.Endpoint
- api_wrapper     → codegraph.ApiWrapper
- api_call_site   → codegraph.ApiCallSite

边类型：
- ChunkEdge 8 类 (CALL / IMPORT / SAME_FILE / TEST_OF / CO_CHANGED / SEMANTIC / IMPLEMENTS / API_CALLS)
- CrossRepoApiCall → API_CALLS 边（跨仓）

Node ID 格式："{prefix}:{uuid}"
prefix 映射：chunk_registry→chunk, symbol→symbol, endpoint→endpoint,
             api_wrapper→wrapper, api_call_site→callsite
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from django.conf import settings
from django.db.models import Avg, Count, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from code_relations.models import ChunkEdge, ChunkRegistry
from codegraph.models import ApiCallSite, ApiWrapper, CrossRepoApiCall, Endpoint, Symbol
from repositories.models import Repository

from .serializers import GalaxyEdge, GalaxyMeta, GalaxyNeighbor, GalaxyNode, GalaxyReference

logger = structlog.get_logger(__name__)

# 节点类型 → Node ID 前缀映射
_NODE_PREFIX: dict[str, str] = {
    "chunk_registry": "chunk",
    "symbol": "symbol",
    "endpoint": "endpoint",
    "api_wrapper": "wrapper",
    "api_call_site": "callsite",
    "repository": "repo",
}

# 全部支持的节点类型（L1 细粒度图。L2 repository 节点单独走 aggregate_repos）
ALL_NODE_TYPES = [
    "chunk_registry",
    "symbol",
    "endpoint",
    "api_wrapper",
    "api_call_site",
]

# 全部支持的边类型
ALL_EDGE_TYPES = [
    "CALL", "IMPORT", "SAME_FILE", "TEST_OF",
    "CO_CHANGED", "SEMANTIC", "IMPLEMENTS", "API_CALLS",
]


def _is_postgres() -> bool:
    """检测当前 DB 引擎是否为 Postgres（用于 pg_trgm 判断）。"""
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    return "postgresql" in engine or "postgis" in engine


def _node_id(prefix: str, obj_id: Any) -> str:
    """构造节点 ID 字符串。"""
    return f"{prefix}:{obj_id}"


def _parse_node_id(node_id: str) -> tuple[str, str]:
    """解析 '{prefix}:{uuid}' 格式，返回 (prefix, uuid_str)。

    Raises ValueError if format is invalid.
    """
    parts = node_id.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"非法 node_id 格式（期望 'prefix:uuid'）: {node_id}")
    return parts[0], parts[1]


def _prefix_to_type(prefix: str) -> str | None:
    """将 node_id 前缀转为节点类型名。"""
    return {v: k for k, v in _NODE_PREFIX.items()}.get(prefix)


# ---------------------------------------------------------------------------
# 各节点类型的聚合辅助函数
# ---------------------------------------------------------------------------


def _aggregate_chunk_registry(
    repo_ids: list[uuid.UUID] | None,
) -> list[GalaxyNode]:
    """聚合 ChunkRegistry 节点，度数用 Subquery 计算出边 + 入边之和。"""
    outgoing_count = (
        ChunkEdge.objects.filter(source_chunk_id=OuterRef("chunk_id"))
        .values("source_chunk_id")
        .annotate(c=Count("id"))
        .values("c")
    )
    incoming_count = (
        ChunkEdge.objects.filter(target_chunk_id=OuterRef("chunk_id"))
        .values("target_chunk_id")
        .annotate(c=Count("id"))
        .values("c")
    )
    qs = ChunkRegistry.objects.annotate(
        out_deg=Coalesce(Subquery(outgoing_count, output_field=IntegerField()), Value(0)),
        in_deg=Coalesce(Subquery(incoming_count, output_field=IntegerField()), Value(0)),
    ).annotate(degree=F("out_deg") + F("in_deg"))

    if repo_ids is not None:
        qs = qs.filter(repository_id__in=repo_ids)

    nodes: list[GalaxyNode] = []
    for obj in qs.order_by("-degree"):
        nodes.append(
            GalaxyNode(
                id=_node_id("chunk", obj.chunk_id),
                type="chunk_registry",
                label=f"{obj.file_path}:{obj.chunk_index}",
                repository_id=str(obj.repository_id),
                file_path=obj.file_path,
                line_start=obj.line_start,
                line_end=obj.line_end,
                metadata=None,
                degree=obj.degree,
            )
        )
    return nodes


def _aggregate_symbols(
    repo_ids: list[uuid.UUID] | None,
) -> list[GalaxyNode]:
    """聚合 Symbol 节点，度数 = 出边调用数。"""
    qs = Symbol.objects.annotate(degree=Count("outgoing_calls"))
    if repo_ids is not None:
        qs = qs.filter(repository_id__in=repo_ids)

    nodes: list[GalaxyNode] = []
    for obj in qs.order_by("-degree"):
        nodes.append(
            GalaxyNode(
                id=_node_id("symbol", obj.id),
                type="symbol",
                label=obj.name,
                repository_id=str(obj.repository_id),
                file_path=obj.file_path,
                line_start=obj.start_line,
                line_end=obj.end_line,
                metadata=None,
                degree=obj.degree,
            )
        )
    return nodes


def _aggregate_endpoints(
    repo_ids: list[uuid.UUID] | None,
) -> list[GalaxyNode]:
    """聚合 Endpoint 节点，度数 = CrossRepoApiCall 调用方数。"""
    qs = Endpoint.objects.annotate(degree=Count("cross_repo_callers"))
    if repo_ids is not None:
        qs = qs.filter(repository_id__in=repo_ids)

    nodes: list[GalaxyNode] = []
    for obj in qs.order_by("-degree"):
        nodes.append(
            GalaxyNode(
                id=_node_id("endpoint", obj.id),
                type="endpoint",
                label=f"{obj.http_method} {obj.url_path}",
                repository_id=str(obj.repository_id),
                file_path=obj.file_path,
                line_start=obj.line_number,
                line_end=None,
                metadata=obj.metadata,
                degree=obj.degree,
            )
        )
    return nodes


def _aggregate_api_wrappers(
    repo_ids: list[uuid.UUID] | None,
) -> list[GalaxyNode]:
    """聚合 ApiWrapper 节点，度数 = call_sites 数量。"""
    qs = ApiWrapper.objects.annotate(degree=Count("call_sites"))
    if repo_ids is not None:
        qs = qs.filter(repository_id__in=repo_ids)

    nodes: list[GalaxyNode] = []
    for obj in qs.order_by("-degree"):
        nodes.append(
            GalaxyNode(
                id=_node_id("wrapper", obj.id),
                type="api_wrapper",
                label=obj.function_symbol,
                repository_id=str(obj.repository_id),
                file_path=obj.file_path,
                line_start=obj.line_number,
                line_end=None,
                metadata=obj.metadata,
                degree=obj.degree,
            )
        )
    return nodes


def _aggregate_api_call_sites(
    repo_ids: list[uuid.UUID] | None,
) -> list[GalaxyNode]:
    """聚合 ApiCallSite 节点，度数 = CrossRepoApiCall 出边数。"""
    qs = ApiCallSite.objects.annotate(degree=Count("cross_repo_calls"))
    if repo_ids is not None:
        qs = qs.filter(repository_id__in=repo_ids)

    nodes: list[GalaxyNode] = []
    for obj in qs.order_by("-degree"):
        nodes.append(
            GalaxyNode(
                id=_node_id("callsite", obj.id),
                type="api_call_site",
                label=f"{obj.caller_function} in {obj.caller_file}:{obj.line_number}",
                repository_id=str(obj.repository_id),
                file_path=obj.caller_file,
                line_start=obj.line_number,
                line_end=None,
                metadata=None,
                degree=obj.degree,
            )
        )
    return nodes


def _aggregate_chunk_edges(
    repo_ids: list[uuid.UUID] | None,
    edge_types: list[str] | None,
) -> list[GalaxyEdge]:
    """聚合 ChunkEdge 边。"""
    qs = ChunkEdge.objects.all()
    if repo_ids is not None:
        qs = qs.filter(repository_id__in=repo_ids)
    if edge_types is not None:
        qs = qs.filter(edge_type__in=edge_types)

    edges: list[GalaxyEdge] = []
    for obj in qs:
        edges.append(
            GalaxyEdge(
                id=f"chunk_edge:{obj.id}",
                source=_node_id("chunk", obj.source_chunk_id),
                target=_node_id("chunk", obj.target_chunk_id),
                edge_type=obj.edge_type,
                weight=obj.weight,
                repository_id=str(obj.repository_id),
                target_repository_id=(
                    str(obj.target_repository_id) if obj.target_repository_id else None
                ),
                metadata=obj.metadata if obj.metadata else None,
            )
        )
    return edges


def _aggregate_cross_repo_edges(
    repo_ids: list[uuid.UUID] | None,
    edge_types: list[str] | None,
) -> list[GalaxyEdge]:
    """聚合 CrossRepoApiCall 作为 API_CALLS 边（callsite → endpoint 跨仓）。"""
    # 只有当 edge_types 包含 API_CALLS 时才聚合
    if edge_types is not None and "API_CALLS" not in edge_types:
        return []

    qs = CrossRepoApiCall.objects.select_related("call_site", "endpoint")
    if repo_ids is not None:
        # 以 call_site.repository 作为 source 仓库过滤
        qs = qs.filter(call_site__repository_id__in=repo_ids)

    edges: list[GalaxyEdge] = []
    for obj in qs:
        edges.append(
            GalaxyEdge(
                id=f"api_calls_edge:{obj.id}",
                source=_node_id("callsite", obj.call_site_id),
                target=_node_id("endpoint", obj.endpoint_id),
                edge_type="API_CALLS",
                weight=1.0,
                repository_id=str(obj.call_site.repository_id),
                target_repository_id=str(obj.endpoint.repository_id),
                metadata={"match_confidence": float(obj.match_confidence)},
            )
        )
    return edges


def _apply_sampling(
    nodes: list[GalaxyNode],
    edges: list[GalaxyEdge],
    max_nodes: int,
) -> tuple[list[GalaxyNode], list[GalaxyEdge], bool]:
    """degree-based top-N 采样。超过 max_nodes 时按 degree 降序保留 top-N 及其相关边。"""
    if len(nodes) <= max_nodes:
        return nodes, edges, False

    sorted_nodes = sorted(nodes, key=lambda n: n["degree"], reverse=True)
    kept = sorted_nodes[:max_nodes]
    kept_ids = {n["id"] for n in kept}
    filtered_edges = [
        e for e in edges if e["source"] in kept_ids and e["target"] in kept_ids
    ]
    return kept, filtered_edges, True


class GalaxyAggregator:
    """统一聚合 5 类节点 + 8 类边为 Galaxy 可视化 payload。"""

    @staticmethod
    def aggregate(
        repo_ids: list[uuid.UUID] | None = None,
        node_types: list[str] | None = None,
        edge_types: list[str] | None = None,
        max_nodes: int = 500,
    ) -> dict[str, Any]:
        """聚合并返回 {nodes, edges, meta}。

        Args:
            repo_ids: 仓库 UUID 列表，None = 所有仓库。
            node_types: 节点类型过滤，None = 所有类型。
            edge_types: 边类型过滤，None = 所有类型。
            max_nodes: 最大节点数，超出则 degree-based 采样。

        Returns:
            {"nodes": [...], "edges": [...], "meta": {...}}
        """
        effective_node_types = node_types or ALL_NODE_TYPES
        effective_edge_types = edge_types  # None = all

        # --- 节点聚合 ---
        all_nodes: list[GalaxyNode] = []
        type_counts: dict[str, int] = {}

        aggregators = {
            "chunk_registry": _aggregate_chunk_registry,
            "symbol": _aggregate_symbols,
            "endpoint": _aggregate_endpoints,
            "api_wrapper": _aggregate_api_wrappers,
            "api_call_site": _aggregate_api_call_sites,
        }
        for node_type in effective_node_types:
            if node_type in aggregators:
                nodes = aggregators[node_type](repo_ids)
                all_nodes.extend(nodes)
                type_counts[node_type] = len(nodes)

        # --- 边聚合 ---
        all_edges: list[GalaxyEdge] = []
        # ChunkEdge（连接 chunk_registry 节点）
        if not node_types or "chunk_registry" in effective_node_types:
            all_edges.extend(_aggregate_chunk_edges(repo_ids, effective_edge_types))
        # CrossRepoApiCall → API_CALLS 边
        if not node_types or (
            "api_call_site" in effective_node_types and "endpoint" in effective_node_types
        ):
            all_edges.extend(_aggregate_cross_repo_edges(repo_ids, effective_edge_types))

        total_nodes_before = len(all_nodes)
        total_edges_before = len(all_edges)

        # --- degree-based 采样 ---
        sampled_nodes, sampled_edges, was_sampled = _apply_sampling(
            all_nodes, all_edges, max_nodes
        )

        meta = GalaxyMeta(
            total_nodes=total_nodes_before,
            total_edges=total_edges_before,
            sampled=was_sampled,
            by_node_type=type_counts,
            per_repo_hint=was_sampled,
        )

        logger.info(
            "galaxy_aggregate",
            repo_ids=len(repo_ids) if repo_ids else "all",
            total_nodes=total_nodes_before,
            total_edges=total_edges_before,
            sampled=was_sampled,
            returned_nodes=len(sampled_nodes),
            returned_edges=len(sampled_edges),
        )

        return {
            "nodes": sampled_nodes,
            "edges": sampled_edges,
            "meta": meta,
        }

    @staticmethod
    def aggregate_repos(space_id: uuid.UUID | None = None) -> dict[str, Any]:
        """聚合仓库节点视图（L2 多仓库总览）。

        节点 = Repository（仅含未软删的仓库；如有 space_id，则限定到该 Space 关联的仓库）。
        边   = CrossRepoApiCall 按 (caller_repo, callee_repo) 聚合成单条 REPO_API_CALL 边。

        Args:
            space_id: Space UUID，None = 全部仓库。

        Returns:
            {"nodes": [...], "edges": [...], "meta": {...}}，节点 type 为 "repository"，
            边 type 为 "REPO_API_CALL"。
        """
        # ---- 仓库节点 ----
        repo_qs = Repository.objects.filter(is_deleted=False)
        if space_id is not None:
            repo_qs = repo_qs.filter(spaces__id=space_id)
        repo_qs = repo_qs.annotate(
            endpoint_count=Count("endpoints", distinct=True),
            callsite_count=Count("api_call_sites", distinct=True),
        ).prefetch_related("spaces")

        nodes: list[GalaxyNode] = []
        repo_ids_in_view: set[uuid.UUID] = set()
        for repo in repo_qs:
            repo_ids_in_view.add(repo.id)
            space_ids = [str(p.id) for p in repo.spaces.all()]
            degree = int(repo.endpoint_count) + int(repo.callsite_count)
            nodes.append(
                GalaxyNode(
                    id=_node_id("repo", repo.id),
                    type="repository",
                    label=repo.name,
                    repository_id=str(repo.id),
                    file_path="",
                    line_start=None,
                    line_end=None,
                    metadata={
                        "git_platform": repo.git_platform,
                        "space_ids": space_ids,
                        "endpoint_count": int(repo.endpoint_count),
                        "callsite_count": int(repo.callsite_count),
                    },
                    degree=degree,
                )
            )

        # ---- 仓库间边 ----
        edges: list[GalaxyEdge] = []
        if repo_ids_in_view:
            edge_qs = (
                CrossRepoApiCall.objects.values(
                    "call_site__repository_id",
                    "endpoint__repository_id",
                )
                .annotate(
                    call_count=Count("id"),
                    avg_conf=Avg("match_confidence"),
                )
                .filter(
                    call_site__repository_id__in=repo_ids_in_view,
                    endpoint__repository_id__in=repo_ids_in_view,
                )
            )

            for row in edge_qs:
                src_repo_id = row["call_site__repository_id"]
                tgt_repo_id = row["endpoint__repository_id"]
                # 自环（同仓库内的 API 调用）跳过，L2 只画跨仓边
                if src_repo_id == tgt_repo_id:
                    continue
                edges.append(
                    GalaxyEdge(
                        id=f"repo_call:{src_repo_id}:{tgt_repo_id}",
                        source=_node_id("repo", src_repo_id),
                        target=_node_id("repo", tgt_repo_id),
                        edge_type="REPO_API_CALL",
                        weight=float(row["call_count"]),
                        repository_id=str(src_repo_id),
                        target_repository_id=str(tgt_repo_id),
                        metadata={
                            "call_count": int(row["call_count"]),
                            "avg_confidence": float(row["avg_conf"] or 0.0),
                        },
                    )
                )

        meta = GalaxyMeta(
            total_nodes=len(nodes),
            total_edges=len(edges),
            sampled=False,
            by_node_type={"repository": len(nodes)},
            per_repo_hint=False,
        )

        logger.info(
            "galaxy_aggregate_repos",
            space_id=str(space_id) if space_id else "all",
            nodes=len(nodes),
            edges=len(edges),
        )

        return {"nodes": nodes, "edges": edges, "meta": meta}

    @staticmethod
    def search(
        q: str,
        repo_ids: list[uuid.UUID] | None = None,
        node_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[GalaxyNode]:
        """跨 5 类节点全文搜索，SQLite icontains + degree 排序，返回 top-{limit}。

        Args:
            q: 搜索关键词（非空）。
            repo_ids: 仓库过滤，None = 所有仓库。
            node_types: 节点类型过滤，None = 所有类型。
            limit: 返回条数上限（max=100）。

        Returns:
            按 degree 降序排列的 GalaxyNode 列表。
        """
        limit = min(limit, 100)
        effective_node_types = node_types or ALL_NODE_TYPES

        # ChunkRegistry 搜索
        chunk_nodes: list[GalaxyNode] = []
        if "chunk_registry" in effective_node_types:
            outgoing_count = (
                ChunkEdge.objects.filter(source_chunk_id=OuterRef("chunk_id"))
                .values("source_chunk_id")
                .annotate(c=Count("id"))
                .values("c")
            )
            incoming_count = (
                ChunkEdge.objects.filter(target_chunk_id=OuterRef("chunk_id"))
                .values("target_chunk_id")
                .annotate(c=Count("id"))
                .values("c")
            )
            qs = ChunkRegistry.objects.filter(
                file_path__icontains=q
            ).annotate(
                out_deg=Coalesce(Subquery(outgoing_count, output_field=IntegerField()), Value(0)),
                in_deg=Coalesce(Subquery(incoming_count, output_field=IntegerField()), Value(0)),
            ).annotate(degree=F("out_deg") + F("in_deg"))
            if repo_ids is not None:
                qs = qs.filter(repository_id__in=repo_ids)
            for obj in qs.order_by("-degree")[:limit]:
                chunk_nodes.append(
                    GalaxyNode(
                        id=_node_id("chunk", obj.chunk_id),
                        type="chunk_registry",
                        label=f"{obj.file_path}:{obj.chunk_index}",
                        repository_id=str(obj.repository_id),
                        file_path=obj.file_path,
                        line_start=obj.line_start,
                        line_end=obj.line_end,
                        metadata=None,
                        degree=obj.degree,
                    )
                )

        # Symbol 搜索
        symbol_nodes: list[GalaxyNode] = []
        if "symbol" in effective_node_types:
            qs_sym = Symbol.objects.filter(
                name__icontains=q
            ).annotate(degree=Count("outgoing_calls"))
            if repo_ids is not None:
                qs_sym = qs_sym.filter(repository_id__in=repo_ids)
            for sym_obj in qs_sym.order_by("-degree")[:limit]:
                symbol_nodes.append(
                    GalaxyNode(
                        id=_node_id("symbol", sym_obj.id),
                        type="symbol",
                        label=sym_obj.name,
                        repository_id=str(sym_obj.repository_id),
                        file_path=sym_obj.file_path,
                        line_start=sym_obj.start_line,
                        line_end=sym_obj.end_line,
                        metadata=None,
                        degree=sym_obj.degree,
                    )
                )

        # Endpoint 搜索
        endpoint_nodes: list[GalaxyNode] = []
        if "endpoint" in effective_node_types:
            qs_ep = Endpoint.objects.filter(
                Q(url_path__icontains=q) | Q(handler_name__icontains=q)
            ).annotate(degree=Count("cross_repo_callers"))
            if repo_ids is not None:
                qs_ep = qs_ep.filter(repository_id__in=repo_ids)
            for ep_obj in qs_ep.order_by("-degree")[:limit]:
                endpoint_nodes.append(
                    GalaxyNode(
                        id=_node_id("endpoint", ep_obj.id),
                        type="endpoint",
                        label=f"{ep_obj.http_method} {ep_obj.url_path}",
                        repository_id=str(ep_obj.repository_id),
                        file_path=ep_obj.file_path,
                        line_start=ep_obj.line_number,
                        line_end=None,
                        metadata=ep_obj.metadata,
                        degree=ep_obj.degree,
                    )
                )

        # ApiWrapper 搜索
        wrapper_nodes: list[GalaxyNode] = []
        if "api_wrapper" in effective_node_types:
            qs_aw = ApiWrapper.objects.filter(
                Q(function_symbol__icontains=q) | Q(url_path_pattern__icontains=q)
            ).annotate(degree=Count("call_sites"))
            if repo_ids is not None:
                qs_aw = qs_aw.filter(repository_id__in=repo_ids)
            for aw_obj in qs_aw.order_by("-degree")[:limit]:
                wrapper_nodes.append(
                    GalaxyNode(
                        id=_node_id("wrapper", aw_obj.id),
                        type="api_wrapper",
                        label=aw_obj.function_symbol,
                        repository_id=str(aw_obj.repository_id),
                        file_path=aw_obj.file_path,
                        line_start=aw_obj.line_number,
                        line_end=None,
                        metadata=aw_obj.metadata,
                        degree=aw_obj.degree,
                    )
                )

        # ApiCallSite 搜索
        callsite_nodes: list[GalaxyNode] = []
        if "api_call_site" in effective_node_types:
            qs_cs = ApiCallSite.objects.filter(
                Q(caller_function__icontains=q) | Q(caller_file__icontains=q)
            ).annotate(degree=Count("cross_repo_calls"))
            if repo_ids is not None:
                qs_cs = qs_cs.filter(repository_id__in=repo_ids)
            for cs_obj in qs_cs.order_by("-degree")[:limit]:
                callsite_nodes.append(
                    GalaxyNode(
                        id=_node_id("callsite", cs_obj.id),
                        type="api_call_site",
                        label=f"{cs_obj.caller_function} in {cs_obj.caller_file}:{cs_obj.line_number}",
                        repository_id=str(cs_obj.repository_id),
                        file_path=cs_obj.caller_file,
                        line_start=cs_obj.line_number,
                        line_end=None,
                        metadata=None,
                        degree=cs_obj.degree,
                    )
                )

        # 合并并按 degree 降序排列
        combined = chunk_nodes + symbol_nodes + endpoint_nodes + wrapper_nodes + callsite_nodes
        combined.sort(key=lambda n: n["degree"], reverse=True)
        return combined[:limit]

    @staticmethod
    def get_node_detail(node_id: str) -> dict[str, Any] | None:
        """获取单节点详情 + 1-hop 邻居 + references/called_by。

        Args:
            node_id: "{prefix}:{uuid}" 格式节点 ID。

        Returns:
            {"node": GalaxyNode, "neighbors": [...], "references": [...], "called_by": [...]}
            或 None（节点不存在）。

        Raises:
            ValueError: node_id 格式非法。
        """
        prefix, uuid_str = _parse_node_id(node_id)
        node_type = _prefix_to_type(prefix)
        if node_type is None:
            raise ValueError(f"未知节点类型前缀: {prefix}")

        # 验证 UUID 格式
        try:
            obj_id = uuid.UUID(uuid_str)
        except ValueError:
            raise ValueError(f"非法 UUID: {uuid_str}")

        if node_type == "chunk_registry":
            return _get_chunk_detail(node_id, obj_id)
        elif node_type == "symbol":
            return _get_symbol_detail(node_id, obj_id)
        elif node_type == "endpoint":
            return _get_endpoint_detail(node_id, obj_id)
        elif node_type == "api_wrapper":
            return _get_api_wrapper_detail(node_id, obj_id)
        elif node_type == "api_call_site":
            return _get_api_call_site_detail(node_id, obj_id)
        return None


# ---------------------------------------------------------------------------
# 节点详情辅助函数
# ---------------------------------------------------------------------------


def _get_chunk_detail(node_id: str, chunk_id: uuid.UUID) -> dict[str, Any] | None:
    """ChunkRegistry 详情 + ChunkEdge 1-hop 邻居。"""
    outgoing_count = (
        ChunkEdge.objects.filter(source_chunk_id=OuterRef("chunk_id"))
        .values("source_chunk_id")
        .annotate(c=Count("id"))
        .values("c")
    )
    incoming_count = (
        ChunkEdge.objects.filter(target_chunk_id=OuterRef("chunk_id"))
        .values("target_chunk_id")
        .annotate(c=Count("id"))
        .values("c")
    )
    try:
        obj = (
            ChunkRegistry.objects.annotate(
                out_deg=Coalesce(
                    Subquery(outgoing_count, output_field=IntegerField()), Value(0)
                ),
                in_deg=Coalesce(
                    Subquery(incoming_count, output_field=IntegerField()), Value(0)
                ),
            )
            .annotate(degree=F("out_deg") + F("in_deg"))
            .get(chunk_id=chunk_id)
        )
    except ChunkRegistry.DoesNotExist:
        return None

    node = GalaxyNode(
        id=node_id,
        type="chunk_registry",
        label=f"{obj.file_path}:{obj.chunk_index}",
        repository_id=str(obj.repository_id),
        file_path=obj.file_path,
        line_start=obj.line_start,
        line_end=obj.line_end,
        metadata=None,
        degree=obj.degree,
    )

    # 1-hop 邻居：出边
    neighbors: list[GalaxyNeighbor] = []
    for edge_obj in ChunkEdge.objects.filter(source_chunk_id=chunk_id):
        tgt_id = _node_id("chunk", edge_obj.target_chunk_id)
        try:
            tgt_obj = ChunkRegistry.objects.get(chunk_id=edge_obj.target_chunk_id)
            tgt_node = GalaxyNode(
                id=tgt_id,
                type="chunk_registry",
                label=f"{tgt_obj.file_path}:{tgt_obj.chunk_index}",
                repository_id=str(tgt_obj.repository_id),
                file_path=tgt_obj.file_path,
                line_start=tgt_obj.line_start,
                line_end=tgt_obj.line_end,
                metadata=None,
                degree=0,
            )
        except ChunkRegistry.DoesNotExist:
            continue
        edge = GalaxyEdge(
            id=f"chunk_edge:{edge_obj.id}",
            source=node_id,
            target=tgt_id,
            edge_type=edge_obj.edge_type,
            weight=edge_obj.weight,
            repository_id=str(edge_obj.repository_id),
            target_repository_id=(
                str(edge_obj.target_repository_id) if edge_obj.target_repository_id else None
            ),
            metadata=edge_obj.metadata if edge_obj.metadata else None,
        )
        neighbors.append(GalaxyNeighbor(node=tgt_node, edge=edge, direction="outgoing"))

    # 1-hop 邻居：入边
    for edge_obj in ChunkEdge.objects.filter(target_chunk_id=chunk_id):
        src_id = _node_id("chunk", edge_obj.source_chunk_id)
        try:
            src_obj = ChunkRegistry.objects.get(chunk_id=edge_obj.source_chunk_id)
            src_node = GalaxyNode(
                id=src_id,
                type="chunk_registry",
                label=f"{src_obj.file_path}:{src_obj.chunk_index}",
                repository_id=str(src_obj.repository_id),
                file_path=src_obj.file_path,
                line_start=src_obj.line_start,
                line_end=src_obj.line_end,
                metadata=None,
                degree=0,
            )
        except ChunkRegistry.DoesNotExist:
            continue
        edge = GalaxyEdge(
            id=f"chunk_edge:{edge_obj.id}",
            source=src_id,
            target=node_id,
            edge_type=edge_obj.edge_type,
            weight=edge_obj.weight,
            repository_id=str(edge_obj.repository_id),
            target_repository_id=(
                str(edge_obj.target_repository_id) if edge_obj.target_repository_id else None
            ),
            metadata=edge_obj.metadata if edge_obj.metadata else None,
        )
        neighbors.append(GalaxyNeighbor(node=src_node, edge=edge, direction="incoming"))

    return {"node": node, "neighbors": neighbors, "references": [], "called_by": []}


def _get_symbol_detail(node_id: str, symbol_id: uuid.UUID) -> dict[str, Any] | None:
    """Symbol 详情（called_by 因 callee_name 非 FK 返回空）。"""
    try:
        obj = Symbol.objects.annotate(degree=Count("outgoing_calls")).get(id=symbol_id)
    except Symbol.DoesNotExist:
        return None

    node = GalaxyNode(
        id=node_id,
        type="symbol",
        label=obj.name,
        repository_id=str(obj.repository_id),
        file_path=obj.file_path,
        line_start=obj.start_line,
        line_end=obj.end_line,
        metadata=None,
        degree=obj.degree,
    )
    return {"node": node, "neighbors": [], "references": [], "called_by": []}


def _get_endpoint_detail(node_id: str, endpoint_id: uuid.UUID) -> dict[str, Any] | None:
    """Endpoint 详情 + CrossRepoApiCall references（调用方 ApiCallSite）。"""
    try:
        obj = Endpoint.objects.annotate(degree=Count("cross_repo_callers")).get(id=endpoint_id)
    except Endpoint.DoesNotExist:
        return None

    node = GalaxyNode(
        id=node_id,
        type="endpoint",
        label=f"{obj.http_method} {obj.url_path}",
        repository_id=str(obj.repository_id),
        file_path=obj.file_path,
        line_start=obj.line_number,
        line_end=None,
        metadata=obj.metadata,
        degree=obj.degree,
    )

    references: list[GalaxyReference] = []
    for call in CrossRepoApiCall.objects.filter(endpoint_id=endpoint_id).select_related(
        "call_site", "call_site__repository"
    ):
        references.append(
            GalaxyReference(
                type="api_call_site",
                id=_node_id("callsite", call.call_site_id),
                label=(
                    f"{call.call_site.caller_function} in "
                    f"{call.call_site.caller_file}:{call.call_site.line_number}"
                ),
                repository_id=str(call.call_site.repository_id),
                match_confidence=float(call.match_confidence),
            )
        )

    return {"node": node, "neighbors": [], "references": references, "called_by": []}


def _get_api_wrapper_detail(node_id: str, wrapper_id: uuid.UUID) -> dict[str, Any] | None:
    """ApiWrapper 详情 + call_sites 邻居。"""
    try:
        obj = ApiWrapper.objects.annotate(degree=Count("call_sites")).get(id=wrapper_id)
    except ApiWrapper.DoesNotExist:
        return None

    node = GalaxyNode(
        id=node_id,
        type="api_wrapper",
        label=obj.function_symbol,
        repository_id=str(obj.repository_id),
        file_path=obj.file_path,
        line_start=obj.line_number,
        line_end=None,
        metadata=obj.metadata,
        degree=obj.degree,
    )

    neighbors: list[GalaxyNeighbor] = []
    for cs in ApiCallSite.objects.filter(api_wrapper_id=wrapper_id):
        cs_id = _node_id("callsite", cs.id)
        cs_node = GalaxyNode(
            id=cs_id,
            type="api_call_site",
            label=f"{cs.caller_function} in {cs.caller_file}:{cs.line_number}",
            repository_id=str(cs.repository_id),
            file_path=cs.caller_file,
            line_start=cs.line_number,
            line_end=None,
            metadata=None,
            degree=0,
        )
        # 用虚拟边表示 FK 关系
        edge = GalaxyEdge(
            id=f"wrapper_uses_{cs.id}",
            source=node_id,
            target=cs_id,
            edge_type="USES",
            weight=1.0,
            repository_id=str(obj.repository_id),
            target_repository_id=None,
            metadata=None,
        )
        neighbors.append(GalaxyNeighbor(node=cs_node, edge=edge, direction="outgoing"))

    return {"node": node, "neighbors": neighbors, "references": [], "called_by": []}


def _get_api_call_site_detail(node_id: str, call_site_id: uuid.UUID) -> dict[str, Any] | None:
    """ApiCallSite 详情 + CrossRepoApiCall → Endpoint 邻居。"""
    try:
        obj = ApiCallSite.objects.annotate(degree=Count("cross_repo_calls")).get(
            id=call_site_id
        )
    except ApiCallSite.DoesNotExist:
        return None

    node = GalaxyNode(
        id=node_id,
        type="api_call_site",
        label=f"{obj.caller_function} in {obj.caller_file}:{obj.line_number}",
        repository_id=str(obj.repository_id),
        file_path=obj.caller_file,
        line_start=obj.line_number,
        line_end=None,
        metadata=None,
        degree=obj.degree,
    )

    neighbors: list[GalaxyNeighbor] = []
    for call in CrossRepoApiCall.objects.filter(call_site_id=call_site_id).select_related(
        "endpoint", "endpoint__repository"
    ):
        ep_id = _node_id("endpoint", call.endpoint_id)
        ep_node = GalaxyNode(
            id=ep_id,
            type="endpoint",
            label=f"{call.endpoint.http_method} {call.endpoint.url_path}",
            repository_id=str(call.endpoint.repository_id),
            file_path=call.endpoint.file_path,
            line_start=call.endpoint.line_number,
            line_end=None,
            metadata=call.endpoint.metadata,
            degree=0,
        )
        edge = GalaxyEdge(
            id=f"api_calls_edge:{call.id}",
            source=node_id,
            target=ep_id,
            edge_type="API_CALLS",
            weight=1.0,
            repository_id=str(obj.repository_id),
            target_repository_id=str(call.endpoint.repository_id),
            metadata={"match_confidence": float(call.match_confidence)},
        )
        neighbors.append(GalaxyNeighbor(node=ep_node, edge=edge, direction="outgoing"))

    return {"node": node, "neighbors": neighbors, "references": [], "called_by": []}
