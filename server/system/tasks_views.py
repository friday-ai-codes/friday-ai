"""任务中心聚合 API：系统管理员查看/管理"排队中 / 进行中"的后台任务。

一次性返回三类活跃后台任务的**具体列表**（非仅计数），供"任务中心"页展示：

- ``indexing``：正在索引的仓库（``index_status=INDEXING``）+ 阶段/文件进度；
- ``summary``：建立知识（AI 描述）pending/running 的仓库；
- ``queue``：durable 队列深度（``procrastinate_jobs`` 按 queue×status）。

支持筛选与分页（``type`` / ``status`` / ``space_id`` / ``limit`` / ``offset``），
以及终止任务（索引走 index/cancel，建立知识走 generate-summary/cancel）。

``GET /api/system/tasks/``（``IsSuperUser``，仅系统管理员，只读）。
"""

from __future__ import annotations

from typing import Any

import structlog
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from permissions.api_permissions import IsSuperUser
from projects.models import SpaceRepository
from repositories.models import IndexStatus, Repository
from repositories.summary_service import derive_summary_status
from subagent.models import SubAgentSession
from system.observability_views import _durable_queue_stats

logger = structlog.get_logger(__name__)

# 单类列表返回默认上限（count 仍为真实总数）。
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _spaces_for_repos(repo_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    """批量查询一组仓库各自所属的空间（id+name），避免 N+1。"""
    if not repo_ids:
        return {}
    rows = SpaceRepository.objects.filter(
        repository_id__in=repo_ids
    ).values_list("repository_id", "space__id", "space__name")
    mapping: dict[str, list[dict[str, str]]] = {}
    for repo_id, project_id, project_name in rows:
        mapping.setdefault(str(repo_id), []).append(
            {"id": str(project_id), "name": project_name}
        )
    return mapping


def _parse_pagination(request: Request) -> tuple[int, int]:
    """解析 limit/offset，做边界保护。"""
    try:
        limit = int(request.query_params.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    try:
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)
    return limit, offset


def _active_summary_rows(space_id: str | None) -> dict[str, str]:
    """枚举在途 REPO_SUMMARY session，按仓库去重，返回 ``{repo_id: status}``。

    可选 ``space_id`` 过滤仅返回归属该空间的仓库。
    """
    rows = (
        SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            status__in=[SubAgentSession.Status.PENDING, SubAgentSession.Status.RUNNING],
        )
        .order_by("-created_at")
        .values_list("status", "last_output")
    )
    latest_by_repo: dict[str, str] = {}
    for session_status, last_output in rows.iterator():
        raw = last_output if isinstance(last_output, dict) else {}
        repo_id = raw.get("repository_id")
        if repo_id and repo_id not in latest_by_repo:
            latest_by_repo[repo_id] = session_status
    if not latest_by_repo:
        return {}

    repo_filter = Repository.objects.filter(
        id__in=list(latest_by_repo.keys()), is_deleted=False
    )
    if space_id:
        repo_filter = repo_filter.filter(spaces__id=space_id)
    alive = set(str(rid) for rid in repo_filter.values_list("id", flat=True))
    return {rid: st for rid, st in latest_by_repo.items() if rid in alive}


class ActiveTasksView(APIView):
    """任务中心：列出正在排队/进行中的后台任务（索引 / 建立知识 / durable 队列）。

    仅系统管理员可访问。支持筛选与分页。
    """

    permission_classes = [IsSuperUser]

    def get(self, request: Request) -> Response:
        task_type = (request.query_params.get("type") or "all").lower()
        status_filter = (request.query_params.get("status") or "all").lower()
        space_id = request.query_params.get("space_id") or None
        limit, offset = _parse_pagination(request)

        want_indexing = task_type in ("all", "indexing")
        want_summary = task_type in ("all", "summary")
        want_queue = task_type in ("all", "queue")

        # 索引任务视作 running 态；当筛选 status=pending 时不返回索引项。
        indexing_block = {"count": 0, "items": []}
        if want_indexing and status_filter in ("all", "running"):
            indexing_qs = Repository.objects.filter(
                is_deleted=False, index_status=IndexStatus.INDEXING
            )
            if space_id:
                indexing_qs = indexing_qs.filter(spaces__id=space_id)
            indexing_qs = indexing_qs.order_by("-updated_at").distinct()
            total_indexing = indexing_qs.count()
            page = list(indexing_qs[offset:offset + limit])
            spaces_map = _spaces_for_repos([str(r.id) for r in page])
            indexing_block = {
                "count": total_indexing,
                "items": [
                    {
                        "repository_id": str(r.id),
                        "name": r.name,
                        "status": "running",
                        "stage": r.index_stage or "",
                        "current_file": r.current_indexing_file or "",
                        "files_processed": r.indexed_files_processed or 0,
                        "files_total": r.indexed_files_total or 0,
                        "spaces": spaces_map.get(str(r.id), []),
                    }
                    for r in page
                ],
            }

        # 建立知识任务（pending/running）。
        summary_block = {"count": 0, "items": []}
        if want_summary:
            rows = _active_summary_rows(space_id)
            if status_filter in ("pending", "running"):
                rows = {
                    rid: st
                    for rid, st in rows.items()
                    if (derive_summary_status(st) or st) == status_filter
                }
            all_ids = list(rows.keys())
            names = dict(
                Repository.objects.filter(id__in=all_ids, is_deleted=False).values_list(
                    "id", "name"
                )
            )
            names = {str(k): v for k, v in names.items()}
            ordered = [rid for rid in all_ids if rid in names]
            page_ids = ordered[offset:offset + limit]
            spaces_map = _spaces_for_repos(page_ids)
            summary_block = {
                "count": len(ordered),
                "items": [
                    {
                        "repository_id": rid,
                        "name": names[rid],
                        "status": derive_summary_status(rows[rid]) or rows[rid],
                        "spaces": spaces_map.get(rid, []),
                    }
                    for rid in page_ids
                ],
            }

        payload: dict[str, Any] = {
            "indexing": indexing_block,
            "summary": summary_block,
            "queue": _durable_queue_stats() if want_queue else {"by_queue_status": [], "totals": {}},
        }

        logger.info(
            "active_tasks_listed",
            category="caller",
            component="task_center",
            initiated_by_user_id=str(getattr(request.user, "id", "")) or "system",
            type=task_type,
            status=status_filter,
            space_id=space_id or "",
            indexing_count=indexing_block["count"],
            summary_count=summary_block["count"],
        )
        return Response(payload)
