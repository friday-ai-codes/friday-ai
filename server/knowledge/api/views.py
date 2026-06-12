"""内部测试 REST（Phase 15-05，Phase 16 前测试面，非 MCP 正式契约）。"""

from __future__ import annotations

from adrf.views import APIView
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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


@extend_schema(tags=["knowledge-retrieval-test"])
class KnowledgeSearchView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request):
        q = request.query_params.get("q", "")
        top_k = _parse_int_param(request.query_params.get("top_k"), 10, "top_k")
        if isinstance(top_k, Response):
            return top_k
        project_ids = _split_ids(request.query_params.get("project_ids"))
        repository_ids = _split_ids(request.query_params.get("repository_ids"))
        include_superseded = request.query_params.get("include_superseded", "").lower() == "true"
        results = await _service.search_similar(
            q,
            user=request.user,
            top_k=top_k,
            project_ids=project_ids,
            repository_ids=repository_ids,
            include_superseded=include_superseded,
        )
        return Response(
            [
                {
                    "score": r.score,
                    "entity_id": str(r.entity.entity_id),
                    "kind": r.entity.entity_kind,
                    "title": r.entity.title,
                    "llm_grade": r.llm_grade,
                    "llm_reason": r.llm_reason,
                }
                for r in results
            ]
        )


@extend_schema(tags=["knowledge-retrieval-test"])
class KnowledgeTimelineView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request, entity_id):
        include_superseded = request.query_params.get("include_superseded", "").lower() == "true"
        nodes = await _service.get_timeline(
            entity_id, user=request.user, include_superseded=include_superseded
        )
        return Response(
            [{"version": n.version, "kind": n.kind, "title": n.title, "summary": n.summary} for n in nodes]
        )


@extend_schema(tags=["knowledge-retrieval-test"])
class KnowledgeRelatedView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request, entity_id):
        direction = request.query_params.get("direction", "both")
        max_hops = _parse_int_param(request.query_params.get("max_hops"), 2, "max_hops")
        if isinstance(max_hops, Response):
            return max_hops
        related = await _service.get_related(
            entity_id, user=request.user, direction=direction, max_hops=max_hops
        )
        return Response(
            [
                {
                    "entity_id": str(r.entity_id),
                    "kind": r.entity_kind,
                    "relation": r.relation,
                    "depth": r.depth,
                }
                for r in related
            ]
        )
