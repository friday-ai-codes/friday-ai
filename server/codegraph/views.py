"""codegraph REST API 视图 —— 仓库嵌套路由下的 Symbol/CallEdge/ImportEdge/Endpoint 接口。"""
from __future__ import annotations
import re
import uuid
from typing import Any
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from codegraph.models import Endpoint, ImportEdge, Symbol
from codegraph.serializers import (
 EndpointSerializer,
 ImportEdgeSerializer,
 SymbolSerializer,
)
from codegraph.services.graph_expansion import GraphExpansionService
from repositories.models import GraphBuildStatus, IndexHistory, Repository
from repositories.permissions import RepositoryPermission
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
 - limit: 默认 50，最大 200（T- DoS 防护）
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
 total = await sync_to_async(qs.count)
 items: list[Symbol] = await sync_to_async(
 lambda: list(qs.order_by("name")[offset: offset + limit])
 )
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
 调用 GraphExpansionService.expand 并用 UUID_RE 过滤非法 edge target（关键差异 3）。
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
 for node in result.get("nodes", )
 ]
 # 关键差异 3：过滤 graph_expansion L274 bug —— callee_name 字符串混入 target 位置
 raw_edges: list[dict[str, Any]] = result.get("edges", )
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
 total = await sync_to_async(qs.count)
 items: list[ImportEdge] = await sync_to_async(
 lambda: list(qs.order_by("source_file")[offset: offset + limit])
 )
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
 qs = qs.filter(http_method=http_method.upper)
 url_path = request.query_params.get("url_path")
 if url_path:
 qs = qs.filter(url_path__contains=url_path)
 total = await sync_to_async(qs.count)
 items: list[Endpoint] = await sync_to_async(
 lambda: list(qs.order_by("url_path")[offset: offset + limit])
 )
 data = EndpointSerializer(items, many=True).data
 logger.info(
 "endpoint_list",
 repository_id=str(repository_id),
 total=total,
 )
 return Response({"count": total, "offset": offset, "limit": limit, "results": data})
class CodegraphDeleteView(APIView):
 """DELETE /api/repositories/{repository_id}/codegraph/
 Phase GRAPH-：仅清图谱三件套（Symbol / ImportEdge / Endpoint），
 向量轨（FileIndex / ChunkEdge / ChunkRegistry / Qdrant collection）保持不变。
 并发保护：若该仓库存在 ``IndexHistory.graph_build_status=RUNNING`` 的活跃索
 引，返 409 + detail 含 ``running`` 关键字（per Plan must_haves）。本端点
 不引入 ``select_for_update`` lock —— per CONTEXT decisions Phase
 GRAPH- 才会落 lock，本 phase 单查 ``aexists`` 即可。
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
 # .filter(...).exists`` 同步查询返 403/404，但消耗 DB IO 且把 ASGI loop
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
 # Phase must_have：单查 aexists 短路并发保护，不依赖 select_for_update。
 graph_running = await IndexHistory.objects.filter(
 repository_id=str(repo.id),
 graph_build_status=GraphBuildStatus.RUNNING,
 ).aexists
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
__all__ = [
 "CallsForSymbolView",
 "CodegraphDeleteView",
 "EndpointListView",
 "ImportEdgeListView",
 "SymbolListView",
]
