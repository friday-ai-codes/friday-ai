"""工件关联只读端点（Phase 98-03 Task 2，KDEP-09）。

``GET /api/knowledge/artifacts/{id}/associations/``：正向查询——给定工件返回相关仓库 /
能力(node_paths) / 关键词。薄委托 ``ArtifactAssociationService.get_artifact_associations``
（JWT + access_scope fail-closed）；不可见/不存在工件返回 404。反向查询留服务层供 Phase 99
消费，端点最小面积不铺开。

观测：``artifact_associations_api_started/completed``（category=caller, component=knowledge, +duration_ms）。
"""

from __future__ import annotations

import time
import uuid

import structlog
from adrf.views import APIView
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from knowledge.artifact_associations import ArtifactAssociationService

logger = structlog.get_logger(__name__)

_COMPONENT = "knowledge"


@extend_schema(tags=["knowledge"])
class ArtifactAssociationsView(APIView):
    """工件关联只读视图（JWT，access_scope fail-closed 的正向关联查询）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request, artifact_id: uuid.UUID):
        started = time.perf_counter()
        logger.info(
            "artifact_associations_api_started",
            artifact_id=str(artifact_id),
            component=_COMPONENT,
            category="caller",
        )
        result = await ArtifactAssociationService().get_artifact_associations(
            artifact_id, user=request.user
        )
        if result is None:
            return Response({"detail": "工件不存在或无权访问"}, status=404)
        logger.info(
            "artifact_associations_api_completed",
            artifact_id=str(artifact_id),
            repo_count=len(result.get("repositories", [])),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return Response(result)
