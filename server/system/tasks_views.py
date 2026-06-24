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

from repositories.models import AISummaryStatus, IndexStatus, Repository
from system.observability_views import _durable_queue_stats

logger = structlog.get_logger(__name__)

# 单类列表返回上限（count 仍为真实总数，items 截断防止超大返回）。
_LIMIT = 100


class ActiveTasksView(APIView):
    """任务中心：列出正在排队/进行中的后台任务（索引 / AI 描述 / durable 队列）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        indexing_qs = Repository.objects.filter(
            is_deleted=False, index_status=IndexStatus.INDEXING
        ).order_by("-updated_at")
        summary_qs = Repository.objects.filter(
            is_deleted=False,
            ai_summary_status__in=[AISummaryStatus.PENDING, AISummaryStatus.RUNNING],
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
        summary_items: list[dict[str, Any]] = [
            {
                "repository_id": str(r.id),
                "name": r.name,
                "status": r.ai_summary_status,
            }
            for r in summary_qs[:_LIMIT]
        ]

        payload = {
            "indexing": {"count": indexing_qs.count(), "items": indexing_items},
            "summary": {"count": summary_qs.count(), "items": summary_items},
            "queue": _durable_queue_stats(),
        }
        return Response(payload)
