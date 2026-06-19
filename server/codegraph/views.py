"""codegraph REST API 视图 —— 仓库嵌套路由下的 Symbol/CallEdge/ImportEdge/Endpoint 接口
+ implementation 三件套（rebuild / cancel / history list）。"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol
from codegraph.serializers import (
    EndpointSerializer,
    GraphBuildHistorySerializer,
    ImportEdgeSerializer,
    SymbolSerializer,
)
from codegraph.services.dependency_aggregator import (
    component_neighbors,
    file_neighbors,
)
from codegraph.services.graph_expansion import GraphExpansionService
from repositories.index_views import (
    ServerSentEventRenderer,
    _build_graph_payload,
    _format_sse,
)
from repositories.models import (
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    GraphBuildHistoryTrigger,
    GraphBuildStatus,
    IndexHistory,
    IndexHistoryStatus,
    Repository,
    RepositoryGraphStatus,
)
from repositories.permissions import RepositoryPermission
from services.background_runner import cancel_background_task

logger = structlog.get_logger(__name__)

# UUID 合法性校验正则（关键差异 3：过滤 graph_expansion L274 bug 产生的非 UUID target）
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

def _safe_int(value: str | None, default: int) -> int:
    """将 query param 字符串安全转换为 int，无效输入返回 default。"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


# 模型短形式 → 前端期望长形式（callEdgeColors.ts key 对齐）
CALL_TYPE_API_MAP: dict[str, str] = {
    "DIRECT": "DIRECT_CALL",
    "METHOD": "METHOD_CALL",
    "ATTRIBUTE": "ATTRIBUTE_ACCESS",
}


class SymbolListView(APIView):
    """GET /api/repositories/{repository_id}/codegraph/symbols/

    返回分页过滤后的 Symbol 列表。
    过滤参数（关键差异 2：手动 query_params，不引入 django-filter）：
    - symbol_type: 可多值（getlist），匹配 FUNCTION/CLASS/METHOD/VARIABLE
    - name: name__icontains 模糊搜索
    - file_path: file_path__startswith 前缀过滤
    - limit: 默认 50，最大 200（security mitigation DoS 防护）
    - offset: 默认 0
    """

    permission_classes = [IsAuthenticated, RepositoryPermission]

    async def get(self, request: Any, repository_id: uuid.UUID) -> Response:
        limit = min(_safe_int(request.query_params.get("limit"), 50), 200)
        offset = max(_safe_int(request.query_params.get("offset"), 0), 0)

        qs = Symbol.objects.filter(repository_id=repository_id)

        symbol_types = request.query_params.getlist("symbol_type")
        if symbol_types:
            qs = qs.filter(symbol_type__in=symbol_types)

        name = request.query_params.get("name")
        if name:
            qs = qs.filter(name__icontains=name)

        file_path = request.query_params.get("file_path")
        if file_path:
            qs = qs.filter(file_path__startswith=file_path)

        total = await sync_to_async(qs.count)()
        items: list[Symbol] = await sync_to_async(
            lambda: list(qs.order_by("name")[offset : offset + limit])
        )()

        data = SymbolSerializer(items, many=True).data
        logger.info(
            "symbol_list",
            repository_id=str(repository_id),
            total=total,
            limit=limit,
            offset=offset,
        )
        return Response({"count": total, "offset": offset, "limit": limit, "results": data})


class CallsForSymbolView(APIView):
    """GET /api/repositories/{repository_id}/codegraph/symbols/{symbol_id}/calls/

    返回以 symbol_id 为种子的 2-hop 调用图 DAG。
    调用 GraphExpansionService.expand() 并用 UUID_RE 过滤非法 edge target（关键差异 3）。
    """

    permission_classes = [IsAuthenticated, RepositoryPermission]

    async def get(
        self,
        request: Any,
        repository_id: uuid.UUID,
        symbol_id: uuid.UUID,
    ) -> Response:
        try:
            seed = await Symbol.objects.aget(id=symbol_id, repository_id=repository_id)
        except Symbol.DoesNotExist:
            return Response({"detail": "Symbol 不存在。"}, status=404)

        max_symbols_per_hop = _safe_int(request.query_params.get("max_per_hop"), 20)
        max_total = _safe_int(request.query_params.get("max_total"), 50)

        result = await GraphExpansionService.expand(
            seed,
            max_symbols_per_hop=max_symbols_per_hop,
            max_total=max_total,
        )

        nodes = [
            {
                "symbol": SymbolSerializer(node["symbol"]).data,
                "depth": node["depth"],
                "relationship": node["relationship"],
            }
            for node in result.get("nodes", [])
        ]

        # 关键差异 3：过滤 graph_expansion L274 bug —— callee_name 字符串混入 target 位置
        raw_edges: list[dict[str, Any]] = result.get("edges", [])
        edges = [
            {
                **e,
                "call_type": CALL_TYPE_API_MAP.get(e.get("call_type", ""), e.get("call_type", "")),
            }
            for e in raw_edges
            if UUID_RE.match(str(e.get("source", "")))
            and UUID_RE.match(str(e.get("target", "")))
        ]

        logger.info(
            "calls_for_symbol",
            repository_id=str(repository_id),
            symbol_id=str(symbol_id),
            nodes=len(nodes),
            edges_raw=len(raw_edges),
            edges_filtered=len(edges),
        )
        return Response(
            {
                "seed_symbol_id": str(symbol_id),
                "nodes": nodes,
                "edges": edges,
            }
        )


def _basename(file_path: str) -> str:
    """取路径末段作展示 label。"""
    return file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path


class GraphNeighborsView(APIView):
    """GET /api/repositories/{repository_id}/codegraph/graph/neighbors/

    统一邻居查询接口（work item）。参数：
    - node_type: file | component | symbol
    - id: 文件路径（file）或 Symbol UUID（component/symbol）
    - direction: both | up | down（默认 both）

    返回 ``{node_type, direction, nodes:[...], edges:[...]}``，前端可直接渲染。
    file/component 走 dependency_aggregator；symbol 走符号级 CallEdge（受益 callee_symbol）。
    """

    permission_classes = [IsAuthenticated, RepositoryPermission]

    async def get(self, request: Any, repository_id: uuid.UUID) -> Response:
        node_type = request.query_params.get("node_type", "")
        node_id = request.query_params.get("id") or request.query_params.get("path")
        direction = request.query_params.get("direction", "both")

        if node_type not in ("file", "component", "symbol"):
            return Response(
                {"detail": "node_type 必须为 file | component | symbol。"}, status=400
            )
        if direction not in ("both", "up", "down"):
            return Response(
                {"detail": "direction 必须为 both | up | down。"}, status=400
            )
        if not node_id:
            return Response({"detail": "缺少 id 参数。"}, status=400)

        if node_type == "file":
            payload = await self._file_payload(str(repository_id), node_id, direction)
        elif node_type == "component":
            payload = await self._component_payload(
                str(repository_id), node_id, direction
            )
        else:
            payload = await self._symbol_payload(str(repository_id), node_id, direction)

        if payload is None:
            return Response({"detail": "节点不存在。"}, status=404)

        logger.info(
            "graph_neighbors",
            repository_id=str(repository_id),
            node_type=node_type,
            direction=direction,
            nodes=len(payload["nodes"]),
            edges=len(payload["edges"]),
        )
        return Response({"node_type": node_type, "direction": direction, **payload})

    async def _file_payload(
        self, repository_id: str, file_path: str, direction: str
    ) -> dict[str, Any]:
        agg = await sync_to_async(file_neighbors)(repository_id, file_path, direction)
        nodes: dict[str, dict[str, Any]] = {
            file_path: {"id": file_path, "type": "file", "label": _basename(file_path)}
        }
        edges: list[dict[str, Any]] = []
        for row in agg.get("downstream", []):
            nodes[row["file"]] = {
                "id": row["file"],
                "type": "file",
                "label": _basename(row["file"]),
            }
            edges.append(
                {
                    "source": file_path,
                    "target": row["file"],
                    "kind": "+".join(row["kinds"]),
                    "count": row["count"],
                }
            )
        for row in agg.get("upstream", []):
            nodes[row["file"]] = {
                "id": row["file"],
                "type": "file",
                "label": _basename(row["file"]),
            }
            edges.append(
                {
                    "source": row["file"],
                    "target": file_path,
                    "kind": "+".join(row["kinds"]),
                    "count": row["count"],
                }
            )
        return {"nodes": list(nodes.values()), "edges": edges}

    async def _component_payload(
        self, repository_id: str, symbol_id: str, direction: str
    ) -> dict[str, Any] | None:
        seed = await Symbol.objects.filter(
            id=symbol_id, repository_id=repository_id
        ).afirst()
        if seed is None:
            return None
        agg = await sync_to_async(component_neighbors)(
            repository_id, symbol_id, direction
        )
        nodes: dict[str, dict[str, Any]] = {
            str(seed.id): {
                "id": str(seed.id),
                "type": "component",
                "label": seed.name,
                "file": seed.file_path,
            }
        }
        edges: list[dict[str, Any]] = []
        for row in agg.get("downstream", []):
            nodes[row["symbol_id"]] = {
                "id": row["symbol_id"],
                "type": "component",
                "label": row["name"],
                "file": row["file"],
            }
            edges.append(
                {
                    "source": str(seed.id),
                    "target": row["symbol_id"],
                    "kind": "component",
                    "count": row["count"],
                }
            )
        for row in agg.get("upstream", []):
            nodes[row["symbol_id"]] = {
                "id": row["symbol_id"],
                "type": "component",
                "label": row["name"],
                "file": row["file"],
            }
            edges.append(
                {
                    "source": row["symbol_id"],
                    "target": str(seed.id),
                    "kind": "component",
                    "count": row["count"],
                }
            )
        return {"nodes": list(nodes.values()), "edges": edges}

    async def _symbol_payload(
        self, repository_id: str, symbol_id: str, direction: str
    ) -> dict[str, Any] | None:
        seed = await Symbol.objects.filter(
            id=symbol_id, repository_id=repository_id
        ).afirst()
        if seed is None:
            return None

        def _query() -> dict[str, Any]:
            nodes: dict[str, dict[str, Any]] = {
                str(seed.id): {
                    "id": str(seed.id),
                    "type": "symbol",
                    "label": seed.name,
                    "file": seed.file_path,
                }
            }
            edges: list[dict[str, Any]] = []
            if direction in ("both", "down"):
                down = (
                    CallEdge.objects.filter(
                        repository_id=repository_id,
                        caller_symbol=seed,
                        callee_symbol__isnull=False,
                    )
                    .select_related("callee_symbol")
                    .distinct()
                )
                for edge in down:
                    target = edge.callee_symbol
                    nodes[str(target.id)] = {
                        "id": str(target.id),
                        "type": "symbol",
                        "label": target.name,
                        "file": target.file_path,
                    }
                    edges.append(
                        {
                            "source": str(seed.id),
                            "target": str(target.id),
                            "kind": CALL_TYPE_API_MAP.get(
                                edge.call_type, edge.call_type
                            ),
                        }
                    )
            if direction in ("both", "up"):
                up = (
                    CallEdge.objects.filter(
                        repository_id=repository_id,
                        callee_symbol=seed,
                        caller_symbol__isnull=False,
                    )
                    .select_related("caller_symbol")
                    .distinct()
                )
                for edge in up:
                    source = edge.caller_symbol
                    nodes[str(source.id)] = {
                        "id": str(source.id),
                        "type": "symbol",
                        "label": source.name,
                        "file": source.file_path,
                    }
                    edges.append(
                        {
                            "source": str(source.id),
                            "target": str(seed.id),
                            "kind": CALL_TYPE_API_MAP.get(
                                edge.call_type, edge.call_type
                            ),
                        }
                    )
            return {"nodes": list(nodes.values()), "edges": edges}

        return await sync_to_async(_query)()


class ImportEdgeListView(APIView):
    """GET /api/repositories/{repository_id}/codegraph/imports/

    返回分页过滤后的 ImportEdge 列表。
    过滤参数：
    - source_file: source_file__startswith
    - target_module: target_module__icontains
    - limit / offset
    """

    permission_classes = [IsAuthenticated, RepositoryPermission]

    async def get(self, request: Any, repository_id: uuid.UUID) -> Response:
        limit = min(_safe_int(request.query_params.get("limit"), 50), 200)
        offset = max(_safe_int(request.query_params.get("offset"), 0), 0)

        qs = ImportEdge.objects.filter(repository_id=repository_id)

        source_file = request.query_params.get("source_file")
        if source_file:
            qs = qs.filter(source_file__startswith=source_file)

        target_module = request.query_params.get("target_module")
        if target_module:
            qs = qs.filter(target_module__icontains=target_module)

        total = await sync_to_async(qs.count)()
        items: list[ImportEdge] = await sync_to_async(
            lambda: list(qs.order_by("source_file")[offset : offset + limit])
        )()

        data = ImportEdgeSerializer(items, many=True).data
        logger.info(
            "import_edge_list",
            repository_id=str(repository_id),
            total=total,
        )
        return Response({"count": total, "offset": offset, "limit": limit, "results": data})


class EndpointListView(APIView):
    """GET /api/repositories/{repository_id}/codegraph/endpoints/

    返回分页过滤后的 Endpoint 列表。
    过滤参数：
    - http_method: 精确匹配（GET/POST/PUT/DELETE/PATCH）
    - url_path: url_path__contains
    - limit / offset
    """

    permission_classes = [IsAuthenticated, RepositoryPermission]

    async def get(self, request: Any, repository_id: uuid.UUID) -> Response:
        limit = min(_safe_int(request.query_params.get("limit"), 50), 200)
        offset = max(_safe_int(request.query_params.get("offset"), 0), 0)

        qs = Endpoint.objects.filter(repository_id=repository_id)

        http_method = request.query_params.get("http_method")
        if http_method:
            qs = qs.filter(http_method=http_method.upper())

        url_path = request.query_params.get("url_path")
        if url_path:
            qs = qs.filter(url_path__contains=url_path)

        total = await sync_to_async(qs.count)()
        items: list[Endpoint] = await sync_to_async(
            lambda: list(qs.order_by("url_path")[offset : offset + limit])
        )()

        data = EndpointSerializer(items, many=True).data
        logger.info(
            "endpoint_list",
            repository_id=str(repository_id),
            total=total,
        )
        return Response({"count": total, "offset": offset, "limit": limit, "results": data})


class CodegraphDeleteView(APIView):
    """DELETE /api/repositories/{repository_id}/codegraph/

    仅清图谱三件套（Symbol / ImportEdge / Endpoint），
    向量轨（FileIndex / ChunkEdge / ChunkRegistry / Qdrant collection）保持不变。

    并发保护：若该仓库存在 ``IndexHistory.graph_build_status=RUNNING`` 的活跃索
    引，返 409 + detail 含 ``running`` 关键字。本端点不引入
    ``select_for_update`` lock，单查 ``aexists`` 即可满足当前并发量。

    返回值矩阵：
        - 204：成功（含图谱原本为空的幂等场景）。
        - 401/403：未认证。
        - 404：仓库不存在或已软删。
        - 409：图谱构建并发运行中。

    与 ``IndexDeleteView`` 的边界：``IndexDeleteView`` 默认级联清向量 + 图谱；
    带 ``?keep_graph=true`` 时仅清向量。本 ``CodegraphDeleteView`` 是其互补端
    点 —— 仅清图谱保留向量，便于"重建图谱不动 embedding"的运维场景。
    """

    # NOTE：不挂 RepositoryPermission —— 该 permission 通过 ``Repository.objects
    # .filter(...).exists()`` 同步查询返 403/404，但消耗 DB IO 且把 ASGI loop
    # 内的查询提前到 permission 阶段；此处显式 ``aget`` + 404 fallback 更直接，
    # 且能区分"仓库不存在"（404）与"图谱并发运行"（409）两类返回码。
    permission_classes = [IsAuthenticated]

    async def delete(
        self, request: Any, repository_id: uuid.UUID
    ) -> Response:
        """级联清空图谱三件套；并发 RUNNING 时 409。"""

        try:
            repo = await Repository.objects.aget(
                id=repository_id, is_deleted=False
            )
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在或已删除。"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # implementation must_have：单查 aexists 短路并发保护，不依赖 select_for_update。
        graph_running = await IndexHistory.objects.filter(
            repository_id=str(repo.id),
            graph_build_status=GraphBuildStatus.RUNNING,
        ).aexists()
        if graph_running:
            logger.info(
                "codegraph_delete_conflict",
                repository_id=str(repo.id),
                reason="graph_build_running",
            )
            return Response(
                {"detail": "图谱构建正在 running，无法清理；请先取消或等待完成。"},
                status=status.HTTP_409_CONFLICT,
            )

        # 复用 cleanup_index 的私有 helper —— 单一权威入口避免重复实现 Symbol /
        # ImportEdge / Endpoint 删除顺序。helper 返回三表删除计数 dict。
        from repositories.services.index_cleanup import (
            _cleanup_graph_artifacts,
        )

        deleted = await _cleanup_graph_artifacts(str(repo.id))
        logger.info(
            "codegraph_delete_complete",
            repository_id=str(repo.id),
            symbols_deleted=deleted["symbols_deleted"],
            import_edges_deleted=deleted["import_edges_deleted"],
            endpoints_deleted=deleted["endpoints_deleted"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# implementation-04 / work item-05：REST 三件套
# ---------------------------------------------------------------------------
#
# - POST /api/repositories/<id>/codegraph/rebuild/  手动触发 graph 构建
# - POST /api/repositories/<id>/codegraph/cancel/   取消进行中 manual 构建
# - GET  /api/repositories/<id>/codegraph/history/  分页历史列表
#
# 锁策略：rebuild 在 ``transaction.atomic()`` 内 ``select_for_update(skip_locked=True)``
# 锁 Repository 行（与 ``IndexCreateView``/``IndexTriggerView`` 同模式），锁内做双子
# 查询（IndexHistory.RUNNING / GraphBuildHistory.RUNNING）；cancel 不抢锁，单查最新
# RUNNING history。错误体统一 ``{"detail": "..."}`` 含关键字便于前端 grep 与 i18n
# 替换（与 ``CodegraphDeleteView`` 一致）。


_REBUILD_INDEX_RUNNING_DETAIL = "index running, cannot rebuild graph"
_REBUILD_GRAPH_RUNNING_DETAIL = "graph already running"
_REBUILD_FEATURE_DISABLED_DETAIL = "graph feature disabled"
_CANCEL_NO_RUNNING_DETAIL = "no graph build running"


def _acquire_lock_and_create_history(
    repository_id: str,
) -> tuple[GraphBuildHistory | None, str | None]:
    """同步辅助：锁仓库行 + 子查询互斥 + 创建 RUNNING history。

    返回 ``(history_or_None, error_detail_or_None)``：

    - ``(history, None)``：成功创建 RUNNING manual history。
    - ``(None, _REBUILD_INDEX_RUNNING_DETAIL)``：向量轨 IndexHistory RUNNING。
    - ``(None, _REBUILD_GRAPH_RUNNING_DETAIL)``：图谱轨 GraphBuildHistory RUNNING
      或 ``select_for_update(skip_locked=True)`` 被并发持锁。

    与 ``repositories/index_views.py::_acquire_index_lock`` 同模式 —— sync ORM 走
    ``transaction.atomic()`` 串行，async view 通过 ``sync_to_async`` 包装调用。
    """
    with transaction.atomic():
        try:
            Repository.objects.select_for_update(skip_locked=True).get(
                id=repository_id, is_deleted=False,
            )
        except Repository.DoesNotExist:
            return None, _REBUILD_GRAPH_RUNNING_DETAIL

        if IndexHistory.objects.filter(
            repository_id=repository_id,
            status=IndexHistoryStatus.RUNNING,
        ).exists():
            return None, _REBUILD_INDEX_RUNNING_DETAIL

        if GraphBuildHistory.objects.filter(
            repository_id=repository_id,
            status=GraphBuildHistoryStatus.RUNNING,
        ).exists():
            return None, _REBUILD_GRAPH_RUNNING_DETAIL

        history = GraphBuildHistory.objects.create(
            repository_id=repository_id,
            status=GraphBuildHistoryStatus.RUNNING,
            trigger_type=GraphBuildHistoryTrigger.MANUAL,
        )
        return history, None


_acquire_lock_and_create_history_async = sync_to_async(
    _acquire_lock_and_create_history,
)


class CodegraphRebuildView(APIView):
    """POST /api/repositories/{repository_id}/codegraph/rebuild/

    手动触发图谱构建（work item-04）。空请求 body，view 内 trigger 固定
    ``manual``。流程：

    1. ``settings.ENABLE_CODEGRAPH=False`` → 403（全局硬开关，per CONTEXT Area 3 Q4）。
    2. 仓库不存在 / 已软删 → 404。
    3. ``select_for_update(skip_locked=True)`` 锁仓库行后双子查询互斥：
       - IndexHistory.status=RUNNING → 409 ``"index running, cannot rebuild graph"``
       - GraphBuildHistory.status=RUNNING → 409 ``"graph already running"``
    4. 通过则锁内创建 ``GraphBuildHistory(status=RUNNING, trigger_type=MANUAL)``，
       事务 commit 后调 ``run_in_background(..., name=f"graph-build-{repo_id}")``。
    5. 返回 ``202 {"history_id": "<uuid>"}``。

    **不读 per-repo 自动构建开关**（per CONTEXT Area 3 Q4：该字段仅控 indexer
    自动衔接路径，手动 REST 是用户 explicit intent，view 层不应读取）。
    """

    permission_classes = [IsAuthenticated]

    async def post(
        self, request: Any, repository_id: uuid.UUID
    ) -> Response:
        if not getattr(settings, "ENABLE_CODEGRAPH", False):
            return Response(
                {"detail": _REBUILD_FEATURE_DISABLED_DETAIL},
                status=status.HTTP_403_FORBIDDEN,
            )

        repo_exists = await Repository.objects.filter(
            id=repository_id, is_deleted=False,
        ).aexists()
        if not repo_exists:
            return Response(
                {"detail": "仓库不存在或已删除。"},
                status=status.HTTP_404_NOT_FOUND,
            )

        history, error_detail = await _acquire_lock_and_create_history_async(
            str(repository_id),
        )
        if error_detail is not None:
            logger.info(
                "codegraph_rebuild_conflict",
                repository_id=str(repository_id),
                reason=error_detail,
            )
            return Response(
                {"detail": error_detail},
                status=status.HTTP_409_CONFLICT,
            )
        assert history is not None  # error_detail None ⇒ history 必非空

        # contract：读可选 branch（缺省 None → base）。归一化与 history.branch_name
        # 写入统一在 service 层（build_graph_for_repository）完成——view 只透传，不在
        # 此分叉 history 创建逻辑。权限/feature flag/路由均不变。
        request_branch = request.data.get("branch") if request.data else None
        branch_arg = request_branch if isinstance(request_branch, str) else None

        # 事务已 commit（sync helper 退出 ``transaction.atomic`` block），现在
        # 安全地投递 durable 图谱任务。durable 入队 + deterministic key 去重
        # （graph:{repo_id}）；GraphBuildHistory 仍在锁内创建并作真相源，
        # GraphFileIndex checkpoint 在任务体内复用，202 响应契约（history_id）不变。
        from durable import QUEUE_GRAPH, DurableTaskService

        repo_id_str = str(repository_id)
        history_id_str = str(history.id)

        await DurableTaskService.defer(
            "durable_graph",
            {
                "repository_id": repo_id_str,
                "history_id": history_id_str,
                "branch": branch_arg,
                "trigger": GraphBuildHistoryTrigger.MANUAL.value,
            },
            queue=QUEUE_GRAPH,
            idempotency_key=f"graph:{repo_id_str}",
        )

        logger.info(
            "codegraph_rebuild_submitted",
            repository_id=repo_id_str,
            history_id=history_id_str,
            trigger=GraphBuildHistoryTrigger.MANUAL.value,
            branch=branch_arg or "",
        )

        return Response(
            {"history_id": history_id_str},
            status=status.HTTP_202_ACCEPTED,
        )


class CodegraphCancelView(APIView):
    """POST /api/repositories/{repository_id}/codegraph/cancel/

    取消最新 RUNNING GraphBuildHistory（work item-05）。流程：

    1. 仓库不存在 / 已软删 → 404。
    2. 查最新 ``GraphBuildHistory(status=RUNNING).order_by("-started_at").afirst()``：
       - ``None`` → 409 ``"no graph build running"``
       - 命中 → 调 ``cancel_background_task(f"graph-build-{repo_id}")``（不依赖返回值），
         转 history.status=CANCELLED + finished_at=now() → 204 No Content。

    **已知限制（CONTEXT 已明示）**：``auto_after_index`` 触发的 history 实际
    background task 名 ``index-{repo_id}`` 而非 ``graph-build-{repo_id}``，
    ``cancel_background_task`` 调用对其 no-op；本端点仍把 DB 行转 CANCELLED 保
    DB 一致性，但 indexer 主任务不会停止 —— 前端应禁用对
    ``trigger_type=auto_after_index`` history 的 cancel 按钮，或等 implementation
    SSE 提供准确状态。
    """

    permission_classes = [IsAuthenticated]

    async def post(
        self, request: Any, repository_id: uuid.UUID
    ) -> Response:
        repo_exists = await Repository.objects.filter(
            id=repository_id, is_deleted=False,
        ).aexists()
        if not repo_exists:
            return Response(
                {"detail": "仓库不存在或已删除。"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 取消该仓库**全部** RUNNING 历史行，而非仅最新一条：indexer 的
        # auto_after_index 路径在并发索引下可能瞬间创建多条 RUNNING 行（已观测到
        # 同一毫秒内 2 条），若只翻最新一条，较早的那条会被永久遗留成幽灵 RUNNING，
        # 永久挡住后续 rebuild（graph already running）。
        running_qs = GraphBuildHistory.objects.filter(
            repository_id=repository_id,
            status=GraphBuildHistoryStatus.RUNNING,
        )
        latest_running = await running_qs.order_by("-started_at").afirst()
        if latest_running is None:
            logger.info(
                "codegraph_cancel_conflict",
                repository_id=str(repository_id),
                reason="no_running_history",
            )
            return Response(
                {"detail": _CANCEL_NO_RUNNING_DETAIL},
                status=status.HTTP_409_CONFLICT,
            )

        cancelled = cancel_background_task(f"graph-build-{repository_id}")

        cancelled_count = await running_qs.aupdate(
            status=GraphBuildHistoryStatus.CANCELLED,
            finished_at=timezone.now(),
        )
        history = latest_running

        # implementation-01 取消出口一致性（CONTEXT Grey Area 1
        # 决议）：除 history 行转 CANCELLED 外，同步把 Repository 进度字段
        # 转 CANCELLED + 清空易失字段，让前端状态徽章 / 进度条立即归零。
        # auto_after_index 触发的 history 主任务 indexer 不会停止——本端点
        # 仍写 Repository 字段保 DB 一致性（best-effort），UI 在下一次
        # SSE 帧或 polling 拿到 cancelled 态即可。
        try:
            await Repository.objects.filter(id=repository_id).aupdate(
                graph_build_status=RepositoryGraphStatus.CANCELLED,
                graph_stage="",
                current_graph_file="",
                graph_files_processed=0,
                graph_last_built_at=timezone.now(),
            )
        except Exception as exc:
            logger.warning(
                "cancel_repository_graph_status_update_failed",
                repository_id=str(repository_id),
                error=str(exc),
            )

        logger.info(
            "codegraph_cancel_submitted",
            repository_id=str(repository_id),
            history_id=str(history.id),
            trigger_type=history.trigger_type,
            background_task_cancelled=cancelled,
            cancelled_history_rows=cancelled_count,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class _GraphBuildHistoryPagination(PageNumberPagination):
    """GraphBuildHistory list 分页（page_size=20 与 IndexHistory list 同款）。"""

    page_size = 20


class CodegraphHistoryListView(ListAPIView):
    """GET /api/repositories/{repository_id}/codegraph/history/

    GraphBuildHistory 分页列表（work item-03 list endpoint 部分）。

    - 默认排序：``-started_at`` —— 命中 plan 落地的索引 ``idx_gbh_repo_started``
      （Meta.indexes ``fields=["repository", "-started_at"]``）。
    - 分页：DRF ``PageNumberPagination(page_size=20)``。
    - 过滤：可选 ``?status=<value>``（合法值之一时生效）。
    """

    permission_classes = [IsAuthenticated]
    serializer_class = GraphBuildHistorySerializer
    pagination_class = _GraphBuildHistoryPagination

    def get_queryset(self) -> Any:
        repository_id = self.kwargs.get("repository_id")
        qs = GraphBuildHistory.objects.filter(repository_id=repository_id)

        status_filter = self.request.query_params.get("status")
        if status_filter in GraphBuildHistoryStatus.values:
            qs = qs.filter(status=status_filter)

        return qs.order_by("-started_at")

    def list(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        repository_id: uuid.UUID | str | None = kwargs.get("repository_id")
        if repository_id is None or not Repository.objects.filter(
            id=repository_id, is_deleted=False,
        ).exists():
            return Response(
                {"detail": "仓库不存在或已删除。"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().list(request, *args, **kwargs)


class CodegraphProgressStreamView(APIView):
    """SSE 端点：仅推图谱构建进度（implementation-04）。

    ``GET /api/repositories/{repository_id}/codegraph/stream/``  (text/event-stream)

    每帧形如::

        data: {"type": "progress",
               "ts": "...",
               "graph": {status, stage, files_processed, files_total,
                         percent, current_file, started_at,
                         edge_count_so_far, error_message}}

    与 ``IndexProgressStreamView`` 区别：

    - 帧 payload **只含 graph 段**——不带 ``repository`` / ``running_history``
      顶层字段（前端 ``useGraphBuildStream`` 已索引仓库单跑图谱场景不需要索引进度）
    - 终止条件**只看 graph**：``graph_build_status != RUNNING`` 即推 done idle
      （不依赖 ``index_status``）

    复用 ``IndexProgressStreamView`` 同源资产：
    - ``ServerSentEventRenderer``（绕过 DRF Accept 协商 406）
    - ``_format_sse(payload)`` data 行 helper
    - ``_build_graph_payload(repo)`` 9 字段 graph 段构造（保两端点 schema 同步）
    - ``INDEX_STREAM_TICK_INTERVAL`` / ``INDEX_STREAM_MAX_TICKS`` settings 同源
      （REQ-work item-04 字面"不引入新 settings"）
    """

    permission_classes = [IsAuthenticated]
    renderer_classes = [ServerSentEventRenderer]

    async def get(self, request: Any, repository_id: uuid.UUID) -> Any:
        try:
            await Repository.objects.aget(
                id=repository_id, is_deleted=False
            )
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在或已删除。"},
                status=status.HTTP_404_NOT_FOUND,
            )

        tick_interval = float(
            getattr(settings, "INDEX_STREAM_TICK_INTERVAL", 1.0)
        )
        max_ticks = int(getattr(settings, "INDEX_STREAM_MAX_TICKS", 300))

        async def event_stream():  # type: ignore[no-untyped-def]
            ticks = 0
            while ticks < max_ticks:
                try:
                    repo = await Repository.objects.aget(id=repository_id)
                except Repository.DoesNotExist:
                    yield _format_sse(
                        {"type": "done", "reason": "repo_deleted"}
                    )
                    return

                graph_payload = await _build_graph_payload(repo)
                yield _format_sse(
                    {
                        "type": "progress",
                        "ts": timezone.now().isoformat(),
                        "graph": graph_payload,
                    }
                )

                if repo.graph_build_status != RepositoryGraphStatus.RUNNING:
                    yield _format_sse({"type": "done", "reason": "idle"})
                    return

                ticks += 1
                if ticks >= max_ticks:
                    break
                if tick_interval > 0:
                    await asyncio.sleep(tick_interval)

            yield _format_sse({"type": "done", "reason": "max_ticks"})

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


__all__ = [
    "CallsForSymbolView",
    "CodegraphCancelView",
    "CodegraphDeleteView",
    "CodegraphHistoryListView",
    "CodegraphProgressStreamView",
    "CodegraphRebuildView",
    "EndpointListView",
    "ImportEdgeListView",
    "SymbolListView",
]
