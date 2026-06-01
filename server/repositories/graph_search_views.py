"""仓库级 GraphRAG 关联搜索端点（Phase / + ）。
把 Admin Playground 的 GraphRAG 扩散检索提取为带项目级 RBAC 的仓库级 branch-aware
公开端点 ``POST /repositories/{id}/graph-search/``，消费 落地的 branch-aware
``HybridSearchService.search(branch_name=)``。
RAG item chunk_id 字段核查结论（Pitfall 7 / OQ1）:
 ``BranchAwareSearchService.search`` 返回项结构为 ``{"id", "score", "payload"}``
 （见 ``services/qdrant_service.py`` search → ``{"id": str(r.id), "score": r.score,
 "payload": r.payload}``）。**chunk_id 取 item["id"]**（Qdrant point id 即 chunk_id）；
 payload 仅含 ``file_path / content / language / start_line / end_line / chunk_index /
 context_header`` 等业务字段，**不含 chunk_id**。序列化 results 时显式映射
 ``chunk_id = item.get("id") or item.get("payload", {}).get("chunk_id", "")``，
 保证非空，否则前端 extractSourceChunks 建不出扩散图起点节点（Pitfall 7）。
"""
from __future__ import annotations
import structlog
from rest_framework import serializers
logger = structlog.get_logger(__name__)
class GraphSearchRequestSerializer(serializers.Serializer):
 """graph-search 请求体校验。
 - ``query``：必填非空（空 → 400 validation error）。
 - ``branch``：可选，缺省/空 → None（端点内走 base 分支归一化）。
 - ``top_k``：可选，默认 30。
 - ``max_tokens``：可选，默认 8000。
 """
 query = serializers.CharField(required=True, allow_blank=False, max_length=1000)
 branch = serializers.CharField(
 required=False, allow_blank=True, allow_null=True, default=None
 )
 top_k = serializers.IntegerField(required=False, default=30, min_value=1)
 max_tokens = serializers.IntegerField(required=False, default=8000, min_value=1)
__all__ = ["GraphSearchRequestSerializer"]
