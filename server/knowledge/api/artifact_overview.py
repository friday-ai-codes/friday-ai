"""交付文档 / 外部依赖聚合接口（KDEP-03）。

`GET /api/knowledge/artifacts/overview/`：按当前用户**可见 Space** 聚合 `initiatives.Artifact`，
返回按 `ArtifactType` 分组的计数 + 一份截断的工件条目列表（供前端总览区块即时搜索），
带 `access_scope` 权限过滤（fail-closed）与截断保护（避免跨项目全量拉取）。

权限收口：`resolve_allowed_project_ids` 返回**可见 Space id**（membership ∪ public_org），
工件按 `project__space_id__in=allowed` 过滤（Artifact → initiatives.Project → Space）。

观测：`artifact_overview_started/completed`（category=caller, component=knowledge, duration_ms）；
聚合异常 best-effort 捕获返回空结构 + `artifact_overview_failed` warning，绝不 500 反噬。
"""

from __future__ import annotations

import time

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from knowledge.access_scope import resolve_allowed_project_ids

logger = structlog.get_logger(__name__)

_COMPONENT = "knowledge"

# 跨项目聚合截断保护（沿用 max_nodes 思路）：items 最多返回条数。
_ITEM_LIMIT = 500

_EMPTY = {"total": 0, "types": [], "items": [], "truncated": False}


def _parse_limit(raw: str | None) -> int:
    """可选 ?limit= 收窄，clamp 到 [1, _ITEM_LIMIT]；非法值 fail-soft 取默认。"""
    if raw is None:
        return _ITEM_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _ITEM_LIMIT
    return max(1, min(value, _ITEM_LIMIT))


def _aggregate(allowed_space_ids: list[str], *, type_key: str | None, limit: int) -> dict:
    """纯 PG 聚合（sync，经 sync_to_async 调用）：类型分组计数 + 截断条目列表。"""
    from initiatives.models import Artifact

    base = Artifact.objects.filter(project__space_id__in=allowed_space_ids)
    if type_key:
        # 非法 type_key（无匹配）自然收窄为空结果，无需额外校验（fail-soft）。
        base = base.filter(type__key=type_key)

    type_rows = list(
        base.values("type__key", "type__name", "type__carrier", "type__ragable")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    types = [
        {
            "type_key": row["type__key"],
            "type_name": row["type__name"],
            "carrier": row["type__carrier"],
            "ragable": row["type__ragable"],
            "count": row["count"],
        }
        for row in type_rows
    ]
    total = sum(row["count"] for row in type_rows)

    item_rows = list(
        base.select_related("type", "project").order_by("-updated_at")[:limit]
    )
    items = [
        {
            "artifact_id": str(a.id),
            "title": a.title,
            "type_key": a.type.key,
            "type_name": a.type.name,
            "carrier": a.carrier,
            "url": a.url,
            "project_id": str(a.project_id),
            "project_name": a.project.name,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in item_rows
    ]

    return {
        "total": total,
        "types": types,
        "items": items,
        "truncated": total > limit,
    }


@extend_schema(tags=["knowledge"])
class ArtifactOverviewView(APIView):
    """交付文档 / 外部依赖聚合视图（JWT，access_scope 过滤的类型分组聚合）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        started = time.perf_counter()
        type_key = request.query_params.get("type_key") or None
        limit = _parse_limit(request.query_params.get("limit"))
        logger.info(
            "artifact_overview_started",
            type_key=type_key,
            limit=limit,
            component=_COMPONENT,
            category="caller",
        )

        allowed = await resolve_allowed_project_ids(request.user)
        if not allowed:
            # fail-closed：无可见 Space → 空结构，零 DB 越权。
            logger.info(
                "artifact_overview_completed",
                allowed_space_count=0,
                type_group_count=0,
                item_count=0,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return Response(dict(_EMPTY))

        try:
            result = await sync_to_async(_aggregate)(allowed, type_key=type_key, limit=limit)
        except Exception as exc:  # noqa: BLE001 — 聚合/观测永不反噬请求（返回空结构不 500）
            logger.warning(
                "artifact_overview_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return Response(dict(_EMPTY))

        logger.info(
            "artifact_overview_completed",
            allowed_space_count=len(allowed),
            type_group_count=len(result["types"]),
            item_count=len(result["items"]),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return Response(result)
