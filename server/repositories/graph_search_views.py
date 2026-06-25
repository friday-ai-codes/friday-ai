"""仓库级 GraphRAG 关联搜索端点（implementation / work item + work item）。

把 Admin Playground 的 GraphRAG 扩散检索提取为带项目级 RBAC 的仓库级 branch-aware
公开端点 ``POST /repositories/{id}/graph-search/``，消费 checkpoint 落地的 branch-aware
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

from typing import TYPE_CHECKING, cast

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from permissions.services import PermissionService
from repositories.models import IndexStatus, Repository
from services.branch_utils import resolve_branch_for_query

if TYPE_CHECKING:
    from accounts.models import User

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
    # code-review 296 M1：加上界防资源滥用（已认证用户传超大值压垮 Qdrant/ORM/响应体）。
    # top_k 上界对齐 CodeSearchView（max_value=50）；max_tokens 给合理上限。
    top_k = serializers.IntegerField(
        required=False, default=30, min_value=1, max_value=50
    )
    max_tokens = serializers.IntegerField(
        required=False, default=8000, min_value=1, max_value=32000
    )


class GraphSearchView(APIView):
    """POST /api/repositories/{id}/graph-search/

    仓库级 GraphRAG 关联搜索（adrf 异步 APIView）。

    权限/状态码语义（work item 红线，三态分明）:
    - 未认证 → 401（``permission_classes=[IsAuthenticated]``）。
    - 仓库不存在 → 404。
    - 仓库存在但用户对其任一 project 无访问权 → **403**（IDOR 净新增防御，
      **不照抄** CodeSearchView / RepositoryPermission——二者均无项目级 RBAC，
      是 IDOR 反例）。
    - 仓库未建立索引（``index_status != INDEXED``）→ 400。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Request, repository_id: str) -> Response:
        # 1. 取 repo —— 不存在返 404（与 403 语义分明，避免混用泄漏存在性）。
        try:
            repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. IDOR 防御（403，净新增）：用户所属 project 与 repo 所属 project 取交集，
        #    空交集且非 superuser → 403。孤儿仓库（repo 无任何 project）对非 superuser
        #    必然空交集 → 403（符合 A3 假设：无 project 归属即无人可访问）。
        user = cast("User", request.user)
        user_project_ids = await sync_to_async(
            lambda: set(
                PermissionService.get_user_projects(user).values_list("id", flat=True)
            )
        )()
        repo_project_ids = await sync_to_async(
            lambda: set(repo.spaces.values_list("id", flat=True))
        )()
        if not user.is_superuser and not (user_project_ids & repo_project_ids):
            return Response(
                {"detail": "无权访问该仓库"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3. index 校验（400）：未索引检索无意义。
        if repo.index_status != IndexStatus.INDEXED:
            return Response(
                {"detail": "仓库尚未建立索引"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. 请求校验。
        serializer = GraphSearchRequestSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        query: str = serializer.validated_data["query"]
        branch: str | None = serializer.validated_data.get("branch")
        top_k: int = serializer.validated_data["top_k"]
        max_tokens: int = serializer.validated_data["max_tokens"]

        # 5. branch 二段归一化（Pitfall 4 最大坑）：
        #    resolve_branch_for_query 对「缺省/传 base 分支名」都返回**非空的 base 分支名**
        #    （如 "main"）。图谱层 base 行 branch_name=""（不是 "main"），feature 行才是
        #    分支名。若直接把 base 分支名当 branch_name 过滤会变 ["", "main"]，虽含 "" 不漏
        #    base 边，但语义错且与 RAG collection 路由不一致——故必须再归一化为 None
        #    （base），只有真正的 feature 分支才透传分支名。
        effective_branch, _ = await resolve_branch_for_query(str(repository_id), branch)
        base_branch_name = repo.base_branch or repo.default_branch
        graph_branch = (
            effective_branch
            if (effective_branch and effective_branch != base_branch_name)
            else None
        )

        # 6. search 编排：消费 checkpoint branch-aware 图谱层（base/overlay 合并）。
        from services.code_intel import get_provider
        from services.retrieval import HybridSearchService

        provider = get_provider()
        result = await HybridSearchService(provider).search(
            query,
            repository_ids=[str(repository_id)],
            branch_name=graph_branch,
            max_tokens=max_tokens,
            top_k=top_k,
        )

        # 7. neighbor 序列化（复用 _serialize_neighbor —— 含 edge_type/weight/reason/hop
        #    兜底；CONTEXT 锁定直接 import。Pitfall 6：若 reviewer 介意私有符号跨模块，
        #    再轻量提取到公共模块）。getattr 兜底：NullProvider 降级走 RagSearchResult
        #    时无 hop1/hop2/graph_context 字段。
        from codegraph.playground_views import _serialize_neighbor

        hop1_neighbors = [
            _serialize_neighbor(n)
            for n in (getattr(result, "hop1_neighbors", []) or [])
        ]
        hop2_neighbors = [
            _serialize_neighbor(n)
            for n in (getattr(result, "hop2_neighbors", []) or [])
        ]
        graph_context: str = getattr(result, "graph_context", "") or ""
        total_tokens: int = getattr(result, "total_tokens", 0) or 0

        # 8. results 序列化（L3 命中片段）：从 result.layers 取 L3 layer 的 items，
        #    chunk_id 显式映射（Pitfall 7：chunk_id 取 item["id"]，payload 不含 chunk_id）。
        results: list[dict[str, object]] = []
        for layer in getattr(result, "layers", []) or []:
            if getattr(layer, "layer", None) != "L3":
                continue
            for item in getattr(layer, "items", []) or []:
                payload = item.get("payload", {}) or {}
                chunk_id = item.get("id") or payload.get("chunk_id", "")
                results.append(
                    {
                        "chunk_id": chunk_id,
                        "file_path": payload.get("file_path", ""),
                        "line_start": payload.get("start_line"),
                        "line_end": payload.get("end_line"),
                        "content": payload.get("content", ""),
                        "score": item.get("score", 0.0),
                        "language": payload.get("language", ""),
                    }
                )

        logger.info(
            "graph_search_completed",
            repository_id=str(repository_id),
            query_len=len(query),
            branch=branch,
            graph_branch=graph_branch,
            results_count=len(results),
            hop1_count=len(hop1_neighbors),
            hop2_count=len(hop2_neighbors),
        )

        return Response(
            {
                "query": query,
                "results": results,
                "hop1_neighbors": hop1_neighbors,
                "hop2_neighbors": hop2_neighbors,
                "graph_context": graph_context,
                "total_tokens": total_tokens,
            },
            status=status.HTTP_200_OK,
        )


__all__ = ["GraphSearchRequestSerializer", "GraphSearchView"]
