"""codegraph REST API 视图 —— 仓库嵌套路由下的 Symbol/CallEdge/ImportEdge/Endpoint 接口。"""
from __future__ import annotations
import re
import uuid
from typing import Any
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from codegraph.models import Endpoint, ImportEdge, Symbol
from codegraph.serializers import (
 EndpointSerializer,
 ImportEdgeSerializer,
 SymbolSerializer,
)
from codegraph.services.graph_expansion import GraphExpansionService
from repositories.permissions import RepositoryPermission
logger = structlog.get_logger(__name__)
# UUID 合法性校验正则（关键差异 3：过滤 graph_expansion L274 bug 产生的非 UUID target）
UUID_RE = re.compile(
 r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
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
 limit = min(int(request.query_params.get("limit", 50)), 200)
 offset = int(request.query_params.get("offset", 0))
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
 max_symbols_per_hop = int(request.query_params.get("max_per_hop", 20))
 max_total = int(request.query_params.get("max_total", 50))
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
 e
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
 limit = min(int(request.query_params.get("limit", 50)), 200)
 offset = int(request.query_params.get("offset", 0))
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
 limit = min(int(request.query_params.get("limit", 50)), 200)
 offset = int(request.query_params.get("offset", 0))
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
__all__ = [
 "CallsForSymbolView",
 "EndpointListView",
 "ImportEdgeListView",
 "SymbolListView",
]
