"""Artifact 版本轨 / 时间线只读 REST views（Chassis v2 · P7）。

read-only 呈现（adrf，镜像 ``spec_views`` 范式，IsAuthenticated）：

- ``ArtifactListView.get``：列 artifact + 当前版本摘要；``?work_item_id=`` / ``?artifact_type=``
  / ``?space_id=`` 过滤（非 UUID 前置 400）。
- ``ArtifactTimelineView.get``：单 artifact 全版本时间线（版本号 / created_at / content_hash /
  supersedes 链 / produced_by_ref / approval_status + 当前版本 render_markdown 摘要）；不存在 404。
- ``ArtifactVersionDownstreamView.get``：聚合引用某 ArtifactVersion 的 RepoCodingTask /
  SddSpec（真实 FK）+ ArchitectMerge（软 UUID 引用）；版本不存在 404。

async 序列化纪律：``.data`` 一律 ``sync_to_async`` 包裹，关联经 select_related/prefetch 预取，
避免 async 上下文 SynchronousOnlyOperation。纯只读，无任何写入（INV-6）。
"""

from __future__ import annotations

import uuid

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.api.artifact_serializers import (
    ArchitectMergeRefSerializer,
    ArtifactListSerializer,
    ArtifactTimelineSerializer,
    RepoCodingTaskRefSerializer,
    SddSpecRefSerializer,
)
from delivery.models import (
    ArchitectMerge,
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    SddSpec,
)

logger = structlog.get_logger(__name__)


def _parse_uuid_param(value: str | None) -> tuple[str | None, bool]:
    """解析可空 UUID query param：返回 (规范化字符串|None, 是否合法)。

    未提供（None/空）视为合法且不过滤；提供但非 UUID 视为非法（调用方前置 400）。
    """
    if not value:
        return None, True
    try:
        return str(uuid.UUID(value)), True
    except (ValueError, TypeError, AttributeError):
        return None, False


class ArtifactListView(APIView):
    """artifact 列表（IsAuthenticated）：GET /api/delivery/artifacts/。

    过滤参数（均可选、可组合）：``work_item_id`` / ``space_id``（UUID，按工作项 / 所属空间）、
    ``artifact_type``（字符串，按交付物类型）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        work_item_id, ok_wi = _parse_uuid_param(
            request.query_params.get("work_item_id")
        )
        if not ok_wi:
            return Response(
                {"error": "work_item_id 格式无效（需为 UUID）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        space_id, ok_space = _parse_uuid_param(request.query_params.get("space_id"))
        if not ok_space:
            return Response(
                {"error": "space_id 格式无效（需为 UUID）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        artifact_type = request.query_params.get("artifact_type") or None

        queryset = Artifact.objects.select_related("current_version").order_by(
            "-updated_at"
        )
        if work_item_id is not None:
            queryset = queryset.filter(work_item_id=work_item_id)
        if space_id is not None:
            queryset = queryset.filter(work_item__space_id=space_id)
        if artifact_type is not None:
            queryset = queryset.filter(artifact_type=artifact_type)

        artifacts = [artifact async for artifact in queryset]
        data = await sync_to_async(
            lambda: ArtifactListSerializer(artifacts, many=True).data
        )()
        return Response(data)


class ArtifactTimelineView(APIView):
    """artifact 版本时间线详情（IsAuthenticated）：GET /api/delivery/artifacts/<uuid>/。

    不存在 → 404 中性消息。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, artifact_id):
        artifact = (
            await Artifact.objects.select_related("current_version")
            .prefetch_related("versions")
            .filter(id=artifact_id)
            .afirst()
        )
        if artifact is None:
            return Response(
                {"error": "artifact 不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        data = await sync_to_async(lambda: ArtifactTimelineSerializer(artifact).data)()
        return Response(data)


class ArtifactVersionDownstreamView(APIView):
    """某 ArtifactVersion 的下游引用聚合（IsAuthenticated）：
    GET /api/delivery/artifact-versions/<uuid>/downstream/。

    聚合三类下游：``coding_tasks``（RepoCodingTask，真实 FK）/ ``sdd_specs``（SddSpec，真实 FK）/
    ``architect_merges``（ArchitectMerge，软 UUID merged_artifact_version）。版本不存在 → 404。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, version_id):
        exists = await ArtifactVersion.objects.filter(id=version_id).aexists()
        if not exists:
            return Response(
                {"error": "artifact 版本不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        coding_tasks = [
            task
            async for task in RepoCodingTask.objects.filter(
                artifact_version_id=version_id
            ).order_by("wave", "created_at")
        ]
        sdd_specs = [
            spec
            async for spec in SddSpec.objects.filter(
                artifact_version_id=version_id
            ).order_by("created_at")
        ]
        merges = [
            merge
            async for merge in ArchitectMerge.objects.filter(
                merged_artifact_version=version_id
            ).order_by("-created_at")
        ]

        def _serialize() -> dict:
            return {
                "artifact_version_id": str(version_id),
                "coding_tasks": RepoCodingTaskRefSerializer(
                    coding_tasks, many=True
                ).data,
                "sdd_specs": SddSpecRefSerializer(sdd_specs, many=True).data,
                "architect_merges": ArchitectMergeRefSerializer(
                    merges, many=True
                ).data,
                "total": len(coding_tasks) + len(sdd_specs) + len(merges),
            }

        data = await sync_to_async(_serialize)()
        return Response(data)
