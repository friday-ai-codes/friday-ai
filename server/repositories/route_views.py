"""仓库路由 API —— implementation (per contract)."""

from typing import Any

import structlog
from adrf.views import APIView
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = structlog.get_logger(__name__)


class RouteRequestSerializer(serializers.Serializer):
    """路由请求验证器 (per contract + security mitigation mitigation).

    - query: max_length=1000 防止 DoS
    - top_k: min=1, max=10 防止资源耗尽
    """

    query = serializers.CharField(max_length=1000, required=True)
    top_k = serializers.IntegerField(default=3, min_value=1, max_value=10)


class RepoRouteView(APIView):
    """POST /api/repositories/route/ —— 仓库路由查询 (work item)."""

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any) -> Response:
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["query"]
        top_k = serializer.validated_data.get("top_k", 3)

        from codegraph.services.repo_router_v2 import RepoRouterV2

        result = await RepoRouterV2.route(query, top_k=top_k)

        return Response({
            "query": query,
            "router_version": result.router_version,
            "auto_selected": result.auto_selected,
            "ranked_repos": [
                {
                    "repo_id": c.repo_id,
                    "repo_name": c.repo_name,
                    "score": c.score,
                    "confidence": c.confidence,
                    "match_reason": c.reasoning,
                    "sub_project": c.sub_project,
                    "sub_project_paths": c.sub_project_paths,
                    "matched_node_paths": c.matched_node_paths,
                }
                for c in result.candidates
            ],
            "total": len(result.candidates),
        })
