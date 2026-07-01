"""交付文档知识树接口（KDEP-06）。

`GET /api/knowledge/artifacts/tree/`：按当前用户**可见 Space** 聚合 `initiatives.Artifact`，
直接返回**嵌套树**（项目 → 工件类型 → 工件叶子），供前端一次加载后做客户端搜索/展开/查看，
**零拼装**。带 `access_scope` 权限过滤（fail-closed）、三级节点上限 clamp + `truncated` 标记、
结构化观测。范式 100% 镜像 Phase 96 已上线的 `artifact_overview.py`（同一 access_scope 口径、
同一截断保护思路、同一 best-effort 观测）。

权限收口：`resolve_allowed_project_ids` 返回**可见 Space id**（membership ∪ public_org），
工件按 `project__space_id__in=allowed` 过滤（Artifact → initiatives.Project → Space）；
无可见 Space 直接返回空结构、零 DB 越权（fail-closed）。

截断保护：全局硬顶 `_GLOBAL_FETCH_CAP` 切片防病态规模；三级 clamp（项目/每项目类型/每类型工件），
任一 clamp 触发或命中全局硬顶时 `truncated=True`。

观测：`artifact_tree_started/completed`（category=caller, component=knowledge, duration_ms）；
`_build_tree` 聚合异常 best-effort 捕获返回空结构 + `artifact_tree_failed` warning，绝不 500 反噬。
"""

from __future__ import annotations

import time

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from knowledge.access_scope import resolve_allowed_project_ids

logger = structlog.get_logger(__name__)

_COMPONENT = "knowledge"

# 全局硬顶：跨 Space 聚合最多拉取的工件数，防病态规模拖垮请求（命中即 truncated）。
_GLOBAL_FETCH_CAP = 5000

# 三级节点上限（clamp 列表长度，count 字段仍记桶内真实计数）。
_MAX_PROJECTS = 200
_MAX_TYPES_PER_PROJECT = 50
_MAX_ARTIFACTS_PER_TYPE = 100

_EMPTY = {"total": 0, "projects": [], "truncated": False}


def _build_tree(allowed_space_ids: list[str]) -> dict:
    """单遍聚合为嵌套树（sync，经 sync_to_async 调用）。

    `项目 → 类型 → 工件` 三级有序结构：项目按 name、类型按 name、叶子按 -updated_at。
    `count` 记桶内真实计数（随遍历累加），列表按三级 clamp 截断，任一截断置 `truncated`。
    `total` 记本次可见拉取的工件真实总数（= trim 后 rows 数），与 `truncated` 自洽：
    即便三级 clamp 裁掉项目/类型/叶子尾部，`total` 仍反映真实可见数，`truncated` 标记有裁剪。
    """
    from initiatives.models import Artifact

    # 多取一行哨兵：仅当哨兵行真实存在（> 硬顶）时才判定全局截断，避免恰好等于硬顶的假阳性。
    rows = list(
        Artifact.objects.filter(project__space_id__in=allowed_space_ids)
        .select_related("type", "project")
        .order_by("project__name", "type__name", "-updated_at")[: _GLOBAL_FETCH_CAP + 1]
    )
    truncated = len(rows) > _GLOBAL_FETCH_CAP
    rows = rows[:_GLOBAL_FETCH_CAP]
    total = len(rows)

    # dict 保序分组（order_by 已排序 → 插入序即展示序）。
    projects_map: dict[str, dict] = {}
    for a in rows:
        pid = str(a.project_id)
        proj = projects_map.get(pid)
        if proj is None:
            proj = {
                "project_id": pid,
                "project_name": a.project.name,
                "count": 0,
                "_types_map": {},
            }
            projects_map[pid] = proj
        proj["count"] += 1

        tkey = a.type.key
        types_map = proj["_types_map"]
        tnode = types_map.get(tkey)
        if tnode is None:
            tnode = {
                "type_key": tkey,
                "type_name": a.type.name,
                "carrier": a.type.carrier,
                "ragable": a.type.ragable,
                "count": 0,
                "artifacts": [],
            }
            types_map[tkey] = tnode
        tnode["count"] += 1

        if len(tnode["artifacts"]) < _MAX_ARTIFACTS_PER_TYPE:
            tnode["artifacts"].append(
                {
                    "artifact_id": str(a.id),
                    "title": a.title,
                    "carrier": a.carrier,
                    "url": a.url,
                    "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                }
            )
        else:
            truncated = True

    projects: list[dict] = []
    for proj in projects_map.values():
        if len(projects) >= _MAX_PROJECTS:
            truncated = True
            break
        types_map = proj.pop("_types_map")
        types: list[dict] = []
        for tnode in types_map.values():
            if len(types) >= _MAX_TYPES_PER_PROJECT:
                truncated = True
                break
            types.append(tnode)
        proj["types"] = types
        projects.append(proj)

    return {"total": total, "projects": projects, "truncated": truncated}


@extend_schema(tags=["knowledge"])
class ArtifactTreeView(APIView):
    """交付文档知识树视图（JWT，access_scope 过滤的嵌套树聚合）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        started = time.perf_counter()
        logger.info(
            "artifact_tree_started",
            component=_COMPONENT,
            category="caller",
        )

        allowed = await resolve_allowed_project_ids(request.user)
        if not allowed:
            # fail-closed：无可见 Space → 空结构，零 DB 越权。
            logger.info(
                "artifact_tree_completed",
                allowed_space_count=0,
                project_count=0,
                total=0,
                truncated=False,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return Response(dict(_EMPTY))

        try:
            result = await sync_to_async(_build_tree)(allowed)
        except Exception as exc:  # noqa: BLE001 — 聚合/观测永不反噬请求（返回空结构不 500）
            logger.warning(
                "artifact_tree_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return Response(dict(_EMPTY))

        logger.info(
            "artifact_tree_completed",
            allowed_space_count=len(allowed),
            project_count=len(result["projects"]),
            total=result["total"],
            truncated=result["truncated"],
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return Response(result)
