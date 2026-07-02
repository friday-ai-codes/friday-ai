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
from django.db.models import Case, Count, IntegerField, Q, Value, When
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from knowledge.access_scope import resolve_allowed_project_ids

logger = structlog.get_logger(__name__)

_COMPONENT = "knowledge"

# 默认分页大小与上限（避免一次性拉全量交付文档）。
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100

_EMPTY = {
    "total": 0,
    "types": [],
    "items": [],
    "page": 1,
    "page_size": _DEFAULT_PAGE_SIZE,
    "has_next": False,
}


def _parse_page(raw: str | None) -> int:
    """?page= 解析，clamp 到 >=1；非法值 fail-soft 取 1。"""
    try:
        return max(1, int(raw)) if raw is not None else 1
    except (TypeError, ValueError):
        return 1


def _parse_page_size(raw: str | None) -> int:
    """?page_size= 解析，clamp 到 [1, _MAX_PAGE_SIZE]；非法值 fail-soft 取默认。"""
    if raw is None:
        return _DEFAULT_PAGE_SIZE
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PAGE_SIZE
    return max(1, min(value, _MAX_PAGE_SIZE))


# 默认展示优先级（first-match-wins，与前端标签/图标契约一致）：
# PRD > 研发 Spec > 飞书文档 > 飞书表格 > markdown > 技术方案 > 测试用例 > 复盘 > 其他。
def _rank(type_key: str, type_name: str, carrier: str) -> int:
    """纯 python 优先级（供 types 磁贴排序；与 `_rank_case` DB 版保持同序）。"""
    k = (type_key or "").lower()
    n = type_name or ""
    nl = n.lower()
    if "prd" in k or "requirement" in k or "需求" in n or "prd" in nl:
        return 0
    if "spec" in k or "spec" in nl or "研发" in n:
        return 1
    if carrier == "feishu_doc":
        return 2
    if carrier == "feishu_bitable":
        return 3
    if carrier == "markdown":
        return 4
    if "tech" in k or "solution" in k or "技术方案" in n or "方案" in n:
        return 5
    if "test" in k or "case" in k or "测试" in n or "用例" in n:
        return 6
    if "retro" in k or "复盘" in n:
        return 7
    return 8


def _rank_case() -> Case:
    """DB 侧优先级 Case（供 items 分页排序）；与 `_rank` 同序。"""
    return Case(
        When(
            Q(type__key__icontains="prd")
            | Q(type__key__icontains="requirement")
            | Q(type__name__icontains="需求")
            | Q(type__name__icontains="PRD"),
            then=Value(0),
        ),
        When(
            Q(type__key__icontains="spec") | Q(type__name__icontains="研发"),
            then=Value(1),
        ),
        When(Q(carrier="feishu_doc"), then=Value(2)),
        When(Q(carrier="feishu_bitable"), then=Value(3)),
        When(Q(carrier="markdown"), then=Value(4)),
        When(
            Q(type__key__icontains="tech")
            | Q(type__key__icontains="solution")
            | Q(type__name__icontains="技术方案")
            | Q(type__name__icontains="方案"),
            then=Value(5),
        ),
        When(
            Q(type__key__icontains="test")
            | Q(type__key__icontains="case")
            | Q(type__name__icontains="测试")
            | Q(type__name__icontains="用例"),
            then=Value(6),
        ),
        When(
            Q(type__key__icontains="retro") | Q(type__name__icontains="复盘"),
            then=Value(7),
        ),
        default=Value(8),
        output_field=IntegerField(),
    )


def _aggregate(
    allowed_space_ids: list[str], *, type_key: str | None, page: int, page_size: int
) -> dict:
    """纯 PG 聚合（sync）：类型分组计数（按优先级）+ 按优先级排序的分页条目列表。"""
    from initiatives.models import Artifact

    base = Artifact.objects.filter(project__space_id__in=allowed_space_ids)
    if type_key:
        # 非法 type_key（无匹配）自然收窄为空结果，无需额外校验（fail-soft）。
        base = base.filter(type__key=type_key)

    type_rows = list(
        base.values("type__key", "type__name", "type__carrier", "type__ragable")
        .annotate(count=Count("id"))
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
    # 磁贴按默认优先级排序（同级按数量降序）。
    types.sort(key=lambda r: (_rank(r["type_key"], r["type_name"], r["carrier"]), -r["count"]))
    total = sum(row["count"] for row in type_rows)

    offset = (page - 1) * page_size
    item_rows = list(
        base.select_related("type", "project")
        .annotate(_rank=_rank_case())
        .order_by("_rank", "-updated_at")[offset : offset + page_size]
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
        "page": page,
        "page_size": page_size,
        "has_next": offset + len(items) < total,
    }


@extend_schema(tags=["knowledge"])
class ArtifactOverviewView(APIView):
    """交付文档 / 外部依赖聚合视图（JWT，access_scope 过滤的类型分组聚合）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        started = time.perf_counter()
        type_key = request.query_params.get("type_key") or None
        page = _parse_page(request.query_params.get("page"))
        page_size = _parse_page_size(request.query_params.get("page_size"))
        logger.info(
            "artifact_overview_started",
            type_key=type_key,
            page=page,
            page_size=page_size,
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
            result = await sync_to_async(_aggregate)(
                allowed, type_key=type_key, page=page, page_size=page_size
            )
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
