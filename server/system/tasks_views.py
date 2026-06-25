"""任务中心聚合 API：让普通用户看到"排队中 / 进行中"的后台任务。

此前前端只能在单仓详情看自己那条进度，没有全局视图；首页"进行中"也只含编码。
本端点一次性返回三类活跃后台任务的**具体列表**（非仅计数），供前端"任务中心"页展示：

- ``indexing``：正在索引的仓库（``index_status=INDEXING``）+ 阶段/文件进度；
- ``summary``：AI 描述 pending/running 的仓库；
- ``queue``：durable 队列深度（``procrastinate_jobs`` 按 queue×status，含 repo_summary）。

``GET /api/system/tasks/``（``IsAuthenticated``，只读）。
"""

from __future__ import annotations

from typing import Any

import structlog
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from repositories.models import IndexStatus, Repository
from repositories.summary_service import derive_summary_status
from subagent.models import SubAgentSession
from system.observability_views import _durable_queue_stats

logger = structlog.get_logger(__name__)

# 单类列表返回上限（count 仍为真实总数，items 截断防止超大返回）。
_LIMIT = 100


def _active_summary_tasks() -> tuple[int, list[dict[str, Any]]]:
    """「AI 描述进行中/排队中」列表——直接读存活 REPO_SUMMARY session（唯一真相）。

    历史实现读 ``Repository.ai_summary_status`` 缓存列，但该列由多个写入方维护、且容器
    回调有终态门禁，store-and-trust 会漂移出「幻影 running」（仓库显示生成中，实际并无
    session 在跑、零 token 消耗）。改为枚举当前处于 pending/running 的 REPO_SUMMARY
    session 并按仓库去重——结构上保证：列表里的每一条都对应一个真实在途的 session。

    Returns:
        ``(count, items)``；``items`` 已按 ``_LIMIT`` 截断，``count`` 为去重后真实总数。
    """
    rows = (
        SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            status__in=[SubAgentSession.Status.PENDING, SubAgentSession.Status.RUNNING],
        )
        .order_by("-created_at")
        .values_list("status", "last_output")
    )
    # 同仓可能有多条在途 session（重派竞态）；按 created_at 倒序去重，保留最新一条。
    latest_by_repo: dict[str, str] = {}
    for session_status, last_output in rows.iterator():
        raw = last_output if isinstance(last_output, dict) else {}
        repo_id = raw.get("repository_id")
        if repo_id and repo_id not in latest_by_repo:
            latest_by_repo[repo_id] = session_status

    if not latest_by_repo:
        return 0, []

    # 关联仓库名；已删除 / 不存在的仓库不计入（避免僵尸 session 撑出幻影条目）。
    names = {
        str(rid): name
        for rid, name in Repository.objects.filter(
            id__in=list(latest_by_repo.keys()), is_deleted=False
        ).values_list("id", "name")
    }
    items = [
        {
            "repository_id": repo_id,
            "name": names[repo_id],
            "status": derive_summary_status(session_status) or session_status,
        }
        for repo_id, session_status in latest_by_repo.items()
        if repo_id in names
    ]
    return len(items), items[:_LIMIT]


class ActiveTasksView(APIView):
    """任务中心：列出正在排队/进行中的后台任务（索引 / AI 描述 / durable 队列）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        indexing_qs = Repository.objects.filter(
            is_deleted=False, index_status=IndexStatus.INDEXING
        ).order_by("-updated_at")

        indexing_items: list[dict[str, Any]] = [
            {
                "repository_id": str(r.id),
                "name": r.name,
                "stage": r.index_stage or "",
                "current_file": r.current_indexing_file or "",
                "files_processed": r.indexed_files_processed or 0,
                "files_total": r.indexed_files_total or 0,
            }
            for r in indexing_qs[:_LIMIT]
        ]

        summary_count, summary_items = _active_summary_tasks()

        payload = {
            "indexing": {"count": indexing_qs.count(), "items": indexing_items},
            "summary": {"count": summary_count, "items": summary_items},
            "queue": _durable_queue_stats(),
        }
        return Response(payload)
