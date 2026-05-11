"""codegraph Playground 视图 —— 仅供管理员调试的五层检索测试面板。"""
from __future__ import annotations
from typing import Any
import structlog
from adrf.views import APIView
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from codegraph.services.layered_search import LayerResult, LayeredSearchService
logger = structlog.get_logger(__name__)
def _serialize_layer(layer: LayerResult) -> dict[str, Any]:
 """将 LayerResult 转换为可序列化的 dict。
 关键差异 5（T-）：L4 items 包含 Symbol ORM 对象，
 必须手动序列化为 dict，仅暴露必要字段，不序列化完整 ORM 对象。
 """
 if layer.layer != "L4":
 return {
 "layer": layer.layer,
 "status": layer.status,
 "result_count": layer.result_count,
 "items": layer.items,
 "error": layer.error,
 "extra": layer.extra,
 }
 # L4 items: [{"symbol": Symbol_ORM, "depth": int, "relationship": str}]
 # 手动序列化，不暴露完整 ORM 对象（T- 信息披露防护）
 serialized_items: list[dict[str, Any]] =
 for item in layer.items:
 sym = item.get("symbol")
 if sym is None:
 continue
 serialized_items.append(
 {
 "symbol_id": str(sym.id),
 "name": sym.name,
 "symbol_type": sym.symbol_type,
 "file_path": sym.file_path,
 "depth": item.get("depth"),
 "relationship": item.get("relationship"),
 }
 )
 return {
 "layer": layer.layer,
 "status": layer.status,
 "result_count": layer.result_count,
 "items": serialized_items,
 "error": layer.error,
 "extra": layer.extra,
 }
class PlaygroundSearchView(APIView):
 """POST /api/codegraph/playground/search/
 五层检索测试面板（仅 admin 可访问，T- 权限防护）。
 请求体：
 - query (str, required): 检索查询
 - repository_ids (list[str], optional): 指定仓库 ID 列表；为空时自动路由
 - max_tokens (int, optional): 最大 token 数，默认 8000
 返回：
 - query, repository_ids, layers (L1~L5), final_context, total_tokens
 """
 permission_classes = [IsAdminUser]
 async def post(self, request: Any) -> Response:
 query: str = request.data.get("query", "").strip
 if not query:
 return Response({"detail": "query 参数不能为空。"}, status=400)
 repository_ids: list[str] | None = request.data.get("repository_ids") or None
 max_tokens: int = int(request.data.get("max_tokens", LayeredSearchService.DEFAULT_MAX_TOKENS))
 logger.info(
 "playground_search",
 query=query[:100],
 repository_ids=repository_ids,
 max_tokens=max_tokens,
 )
 result = await LayeredSearchService.search(
 query,
 repository_ids=repository_ids,
 max_tokens=max_tokens,
 )
 layers_data = [_serialize_layer(layer) for layer in result.layers]
 return Response(
 {
 "query": result.query,
 "repository_ids": result.repository_ids,
 "layers": layers_data,
 "final_context": result.final_context,
 "total_tokens": result.total_tokens,
 }
 )
__all__ = ["PlaygroundSearchView"]
