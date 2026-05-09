"""仓库路由 API —— Phase (per )."""
from typing import Any
import structlog
from adrf.views import APIView
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
logger = structlog.get_logger(__name__)
class RouteRequestSerializer(serializers.Serializer):
 """路由请求验证器 (per + T- mitigation).
 - query: max_length=1000 防止 DoS
 - top_k: min=1, max=10 防止资源耗尽
 """
 query = serializers.CharField(max_length=1000, required=True)
 top_k = serializers.IntegerField(default=3, min_value=1, max_value=10)
class RepoRouteView(APIView):
 """POST /api/repositories/route/ —— 仓库路由查询 ."""
 permission_classes = [IsAuthenticated]
 async def post(self, request: Any) -> Response:
 serializer = RouteRequestSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 query = serializer.validated_data["query"]
 top_k = serializer.validated_data.get("top_k", 3)
 from codegraph.services.repo_router import RepoRouter
 results = await RepoRouter.route(query, top_k=top_k)
 return Response({
 "query": query,
 "ranked_repos": [
 {
 "repo_id": r.repo_id,
 "repo_name": r.repo_name,
 "score": r.final_score,
 "bm25_score": r.bm25_score,
 "embedding_score": r.embedding_score,
 "match_reason": r.match_reason,
 }
 for r in results
 ],
 "total": len(results),
 })
