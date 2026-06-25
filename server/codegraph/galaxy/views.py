"""Galaxy API REST 视图 —— 4 个 endpoint 统一聚合 L1 细粒度 + L2 仓库视图。

路由：
- GET /api/codegraph/galaxy/               → GalaxyView         (L1 细粒度)
- GET /api/codegraph/galaxy/repos/         → GalaxyReposView    (L2 仓库节点)
- GET /api/codegraph/galaxy/search/        → GalaxySearchView
- GET /api/codegraph/galaxy/nodes/<id>/    → GalaxyNodeDetailView
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from codegraph.galaxy.aggregator import GalaxyAggregator
from codegraph.galaxy.cache import GalaxyGraphCache

logger = structlog.get_logger(__name__)

# 最大允许 max_nodes 值（防 DoS）
_MAX_NODES_CEILING = 5000
# 最大允许 search limit
_MAX_SEARCH_LIMIT = 100
# 最大允许 q 长度
_MAX_Q_LEN = 200


def _safe_int(value: str | None, default: int) -> int:
    """安全转换 query param 字符串为 int。"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _parse_uuid_list(value: str | None) -> list[uuid.UUID] | None:
    """解析逗号分隔的 UUID 列表，忽略非法项。None / 空字符串 → None（全部）。"""
    if not value:
        return None
    result: list[uuid.UUID] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(uuid.UUID(part))
        except ValueError:
            pass  # 忽略非法 UUID
    return result if result else None


def _parse_str_list(value: str | None) -> list[str] | None:
    """解析逗号分隔的字符串列表。None / 空字符串 → None（全部）。"""
    if not value:
        return None
    result = [p.strip() for p in value.split(",") if p.strip()]
    return result if result else None


class GalaxyView(APIView):
    """GET /api/codegraph/galaxy/ — 聚合 5 类节点 + 7/8 类边。

    Query params:
    - repo_ids:    逗号分隔 UUID，None = 全部仓库
    - node_types:  逗号分隔节点类型，None = 全部
    - edge_types:  逗号分隔边类型，None = 全部
    - max_nodes:   int，默认 500（超出则 degree-based 采样）
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        repo_ids = _parse_uuid_list(request.query_params.get("repo_ids"))
        node_types = _parse_str_list(request.query_params.get("node_types"))
        edge_types = _parse_str_list(request.query_params.get("edge_types"))
        max_nodes = min(
            _safe_int(request.query_params.get("max_nodes"), 500),
            _MAX_NODES_CEILING,
        )

        # 文件缓存 + 签名失效（codegraph/galaxy/cache.py）；
        # GALAXY_CACHE_ENABLED=False 时内部透传实时聚合
        result = await sync_to_async(GalaxyGraphCache.aggregate_cached)(
            repo_ids=repo_ids,
            node_types=node_types,
            edge_types=edge_types,
            max_nodes=max_nodes,
        )

        logger.info(
            "galaxy_view",
            repo_ids=len(repo_ids) if repo_ids else "all",
            nodes=len(result["nodes"]),
            edges=len(result["edges"]),
            sampled=result["meta"]["sampled"],
            cache_hit=result["meta"].get("cache_hit", False),
        )
        return Response(result)


class GalaxyReposView(APIView):
    """GET /api/codegraph/galaxy/repos/ — L2 仓库节点视图。

    Query params:
    - space_id: UUID，可选；不传 = 全部仓库。给定时按 Space.repositories 过滤。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        raw_space_id = request.query_params.get("space_id")
        space_id: uuid.UUID | None = None
        if raw_space_id:
            try:
                space_id = uuid.UUID(raw_space_id)
            except ValueError:
                return Response(
                    {"detail": "space_id 必须是合法 UUID。"}, status=400
                )

        result = await sync_to_async(GalaxyAggregator.aggregate_repos)(
            space_id=space_id,
        )

        logger.info(
            "galaxy_repos_view",
            space_id=str(space_id) if space_id else "all",
            nodes=len(result["nodes"]),
            edges=len(result["edges"]),
        )
        return Response(result)


class GalaxySearchView(APIView):
    """GET /api/codegraph/galaxy/search/ — 跨 5 类节点全文搜索。

    Query params:
    - q:          搜索关键词（必填）
    - repo_ids:   逗号分隔 UUID，None = 全部仓库
    - node_types: 逗号分隔节点类型，None = 全部
    - limit:      返回条数，默认 20（max 100）
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response({"detail": "q 参数不能为空。"}, status=400)
        if len(q) > _MAX_Q_LEN:
            return Response(
                {"detail": f"q 参数过长（最大 {_MAX_Q_LEN} 字符）。"}, status=400
            )

        repo_ids = _parse_uuid_list(request.query_params.get("repo_ids"))
        node_types = _parse_str_list(request.query_params.get("node_types"))
        limit = min(
            _safe_int(request.query_params.get("limit"), 20),
            _MAX_SEARCH_LIMIT,
        )

        results = await sync_to_async(GalaxyAggregator.search)(
            q=q,
            repo_ids=repo_ids,
            node_types=node_types,
            limit=limit,
        )

        logger.info(
            "galaxy_search",
            q=q,
            repo_ids=len(repo_ids) if repo_ids else "all",
            count=len(results),
        )
        return Response({"results": results, "count": len(results), "query": q})


class GalaxyNodeDetailView(APIView):
    """GET /api/codegraph/galaxy/nodes/<str:node_id>/ — 节点详情 + 1-hop 邻居。

    node_id 格式："{type_prefix}:{uuid}"
    例如：chunk:550e8400-e29b-41d4-a716-446655440000
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, node_id: str) -> Response:
        try:
            result = await sync_to_async(GalaxyAggregator.get_node_detail)(node_id)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        if result is None:
            return Response({"detail": "节点不存在。"}, status=404)

        logger.info(
            "galaxy_node_detail",
            node_id=node_id,
            neighbors=len(result.get("neighbors", [])),
            references=len(result.get("references", [])),
        )
        return Response(result)


__all__ = [
    "GalaxyNodeDetailView",
    "GalaxyReposView",
    "GalaxySearchView",
    "GalaxyView",
]
