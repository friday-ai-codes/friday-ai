"""交付知识 JWT REST API（Phase 16-05 ENH-03/04）。"""

from __future__ import annotations

import uuid

from adrf.views import APIView
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from knowledge.access_scope import resolve_allowed_project_ids
from knowledge.exposure import (
    parse_as_of,
    serialize_entity_metadata,
    serialize_related,
    serialize_search_results,
    serialize_timeline,
)
from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion
from knowledge.retrieval import DeliveryKnowledgeSearchService

_service = DeliveryKnowledgeSearchService()


def _split_ids(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def _parse_int_param(raw: str | None, default: int, name: str) -> int | Response:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return Response({"detail": f"{name} must be integer"}, status=400)


def _parse_as_of_param(request) -> tuple[object | None, Response | None]:
    raw = request.query_params.get("as_of")
    if not raw:
        return None, None
    try:
        return parse_as_of(raw), None
    except ValueError as exc:
        return None, Response({"detail": str(exc)}, status=400)


async def _entity_visible_metadata(entity_id: uuid.UUID, *, user, as_of=None, include_superseded=False):
    try:
        entity = await KnowledgeEntity.objects.aget(id=entity_id)
    except KnowledgeEntity.DoesNotExist:
        return None
    if entity.space_id is None:
        return None
    allowed = await resolve_allowed_project_ids(user)
    if str(entity.space_id) not in allowed:
        return None

    from django.db.models import Q

    qs = KnowledgeEntityVersion.objects.filter(entity_id=entity_id)
    if as_of is not None:
        qs = qs.filter(
            Q(valid_at__lte=as_of) & (Q(invalid_at__isnull=True) | Q(invalid_at__gt=as_of))
        )
    elif not include_superseded:
        qs = qs.filter(Q(is_latest=True) | Q(invalid_at__isnull=True))
    version_row = await qs.order_by("-version").afirst()
    if version_row is None:
        return None
    return await hydrate_entity_metadata(
        entity_id, version_row.version, include_superseded=include_superseded or as_of is not None
    )


@extend_schema(tags=["knowledge"])
class KnowledgeSearchView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request):
        as_of, err = _parse_as_of_param(request)
        if err is not None:
            return err
        q = request.query_params.get("q", "")
        top_k = _parse_int_param(request.query_params.get("top_k"), 10, "top_k")
        if isinstance(top_k, Response):
            return top_k
        project_ids = _split_ids(request.query_params.get("project_ids"))
        repository_ids = _split_ids(request.query_params.get("repository_ids"))
        include_superseded = request.query_params.get("include_superseded", "").lower() == "true"
        # KDEP-02：工件是 kind=document 实体，默认被过滤故搜索看不到——启用 document 召回。
        # 权限不放宽：recall 的 include_document_kind=True 仍受 allowed_project_ids/
        # allowed_repository_ids 收口（见 vector_recall docstring），access_scope 不被破坏。
        # 取舍：此改动同时让 feishu_document/project_doc/project_memory 等 document 实体进入
        # 全局搜索（属预期，均受权限过滤，非泄漏）。
        results = await _service.search_similar(
            q,
            user=request.user,
            top_k=top_k,
            project_ids=project_ids,
            repository_ids=repository_ids,
            include_superseded=include_superseded,
            include_document_kind=True,
            as_of=as_of,
        )
        return Response(serialize_search_results(results))


@extend_schema(tags=["knowledge"])
class KnowledgeEntityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request, entity_id: uuid.UUID):
        as_of, err = _parse_as_of_param(request)
        if err is not None:
            return err
        meta = await _entity_visible_metadata(entity_id, user=request.user, as_of=as_of)
        if meta is None:
            return Response({"detail": "实体不存在或无权访问"}, status=404)
        return Response(serialize_entity_metadata(meta))


@extend_schema(tags=["knowledge"])
class KnowledgeTimelineView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request, entity_id):
        as_of, err = _parse_as_of_param(request)
        if err is not None:
            return err
        include_superseded = request.query_params.get("include_superseded", "").lower() == "true"
        nodes = await _service.get_timeline(
            entity_id,
            user=request.user,
            include_superseded=include_superseded,
            as_of=as_of,
        )
        if not nodes:
            meta = await _entity_visible_metadata(entity_id, user=request.user, as_of=as_of)
            if meta is None:
                return Response({"detail": "实体不存在或无权访问"}, status=404)
        return Response(serialize_timeline(nodes))


@extend_schema(tags=["knowledge"])
class KnowledgeRelatedView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request, entity_id):
        as_of, err = _parse_as_of_param(request)
        if err is not None:
            return err
        direction = request.query_params.get("direction", "both")
        if direction not in ("both", "out", "in"):
            return Response(
                {"detail": "direction must be one of: both, out, in"},
                status=400,
            )
        max_hops = _parse_int_param(request.query_params.get("max_hops"), 2, "max_hops")
        if isinstance(max_hops, Response):
            return max_hops
        meta = await _entity_visible_metadata(entity_id, user=request.user, as_of=as_of)
        if meta is None:
            return Response({"detail": "实体不存在或无权访问"}, status=404)
        related = await _service.get_related(
            entity_id,
            user=request.user,
            direction=direction,
            max_hops=max_hops,
            as_of=as_of,
        )
        return Response(serialize_related(related))
