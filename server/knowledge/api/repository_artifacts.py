"""仓库→相关交付文档反查只读端点（Phase 99-02，KDEP-11 反向支撑）。

``GET /api/knowledge/repositories/{id}/artifacts/``：反向查询——给定仓库返回相关交付
文档（工件）。薄委托 ``ArtifactAssociationService.find_artifacts_by_repository``
（JWT + access_scope fail-closed）；不可见/越权仓库返回空列表。每项补确定性
``entity_id``（= document 实体 id），供前端跳知识实体详情形成双向可导航闭环。

观测：``repository_artifacts_api_started/completed``（category=caller, component=knowledge, +duration_ms）。
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
from knowledge.models import EntityKind, generate_entity_id

logger = structlog.get_logger(__name__)

_COMPONENT = "knowledge"


@extend_schema(tags=["knowledge"])
class RepositoryArtifactsView(APIView):
    """仓库→相关交付文档反查视图（JWT，access_scope fail-closed）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id: uuid.UUID):
        started = time.perf_counter()
        logger.info(
            "repository_artifacts_api_started",
            repository_id=str(repository_id),
            component=_COMPONENT,
            category="caller",
        )
        rows = await ArtifactAssociationService().find_artifacts_by_repository(
            repository_id, user=request.user
        )
        artifacts = [
            {
                **row,
                "entity_id": str(
                    generate_entity_id(
                        EntityKind.DOCUMENT, "artifact", str(row["artifact_id"])
                    )
                ),
            }
            for row in rows
        ]
        logger.info(
            "repository_artifacts_api_completed",
            repository_id=str(repository_id),
            artifact_count=len(artifacts),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return Response({"artifacts": artifacts})
