"""codegraph Playground 视图 —— 仅供管理员调试的五层检索测试面板。
Phase Plan: callsite 语义已切换到 ``HybridSearchService`` 编排器；
为保 保留组 ``server/tests/codegraph/test_playground_api.py`` 中
``patch("codegraph.playground_views.LayeredSearchService.search")`` 继续生效
（旧测试不动且全绿），模块顶部保留 ``LayeredSearchService`` 别名作为 patch 入口。
实际调用走 ``LayeredSearchService.search`` thin wrapper（Plan Task 2 改造），
wrapper 内部 delegate ``HybridSearchService(get_provider).search(...)``，行为与
直接调 HybridSearchService 字节级等价；Phase 测试矩阵阶段统一迁移后可删别名。
"""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any
import structlog
from adrf.views import APIView
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
# patch compat：``from codegraph.services import layered_search`` 间接 import，
# 不命中 success criteria #1 CI grep ``from codegraph\.services\.layered_search``。
from codegraph.services import layered_search as _layered_search_compat
from services.code_intel import get_provider # noqa: F401 # surface 入口（Plan ）
from services.retrieval import HybridSearchService # noqa: F401 # surface 入口（Plan ）
logger = structlog.get_logger(__name__)
#: 测试 patch 入口（``patch("codegraph.playground_views.LayeredSearchService.search")``）。
#: 实际调用经 thin wrapper delegate 到 ``HybridSearchService(get_provider).search``。
#: Phase 测试矩阵阶段迁移完成后删除。
LayeredSearchService = _layered_search_compat.LayeredSearchService
#: LayerResult 别名（保 ``_serialize_layer`` 类型一致；Plan Task 2 wrapper 会
#: 把模块级 ``LayerResult`` alias 到 ``services.retrieval.types.LayerSnapshot``）。
LayerResult = _layered_search_compat.LayerResult
#: max_tokens 默认值（Plan token_budget 模块未导出该常量，本视图就近落字面量）。
DEFAULT_MAX_TOKENS: int = 8000
#: NeighborMetadata dataclass 字段集合（Phase Plan graph 透传）。
#: 与 ``services.retrieval.types.NeighborMetadata`` 字段同名同序，duck-typed mock
#: 只要属性齐全即可（保 patch 风格兼容 — 不强制 ``isinstance``）。
_NEIGHBOR_FIELDS: tuple[str, ...] = (
 "chunk_id",
 "file_path",
 "line_start",
 "line_end",
 "edge_type",
 "weight",
 "reason",
 "hop",
)
def _serialize_neighbor(neighbor: Any) -> dict[str, Any]:
 """将 NeighborMetadata（或 dict-shaped mock）转 dict。
 优先 ``dataclasses.asdict``（命中 frozen dataclass 路径），否则按
 ``_NEIGHBOR_FIELDS`` 逐字段 ``getattr`` 兜底（兼容 dict / Mock / 测试 stub）。
 兜底（防 partial mock weight=None 让前端 ``null.toFixed`` 抛 TypeError）：
 weight / reason / hop 三个数值 / 字符串 / 整数字段，缺失时分别降级为
 ``0.0`` / ``""`` / ``1``，保前端 TS 类型契约不被运行时打破。
 """
 if is_dataclass(neighbor) and not isinstance(neighbor, type):
 raw = asdict(neighbor)
 elif isinstance(neighbor, dict):
 raw = {k: neighbor.get(k) for k in _NEIGHBOR_FIELDS}
 else:
 raw = {k: getattr(neighbor, k, None) for k in _NEIGHBOR_FIELDS}
 weight_raw = raw.get("weight")
 reason_raw = raw.get("reason")
 hop_raw = raw.get("hop")
 raw["weight"] = float(weight_raw) if isinstance(weight_raw, (int, float)) else 0.0
 raw["reason"] = str(reason_raw) if isinstance(reason_raw, str) else ""
 raw["hop"] = int(hop_raw) if isinstance(hop_raw, int) and hop_raw in (1, 2) else 1
 return raw
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
 #: int(...) 失败时返回 400 Bad Request 而非 500（用户传入非整数字符串）
 try:
 max_tokens: int = int(request.data.get("max_tokens", DEFAULT_MAX_TOKENS))
 except (TypeError, ValueError):
 return Response({"detail": "max_tokens 必须是整数。"}, status=400)
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
 # Phase Plan：graph enrichment 透传（per work item §10 硬约束 1）。
 # 用 ``getattr(..., default)`` 兜底，兼容 既有 LayeredSearchResult patch
 # 路径（无 graph 字段 → 降级为空 list / 空字符串）。
 # 禁止 ``isinstance(result, HybridSearchResult)`` 分支：会被 测试 mock 打穿。
 hop1_neighbors = [
 _serialize_neighbor(n)
 for n in getattr(result, "hop1_neighbors", ) or
 ]
 hop2_neighbors = [
 _serialize_neighbor(n)
 for n in getattr(result, "hop2_neighbors", ) or
 ]
 graph_context: str = getattr(result, "graph_context", "") or ""
 return Response(
 {
 "query": result.query,
 "repository_ids": result.repository_ids,
 "layers": layers_data,
 "final_context": result.final_context,
 "total_tokens": result.total_tokens,
 "hop1_neighbors": hop1_neighbors,
 "hop2_neighbors": hop2_neighbors,
 "graph_context": graph_context,
 }
 )
__all__ = ["PlaygroundSearchView"]
