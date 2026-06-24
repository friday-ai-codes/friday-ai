"""超管可观测聚合 API（OBS-01）：任务队列全景 + 系统/Runner 负载。

单一只读端点 ``GET /api/system/observability/``（``IsSuperUser`` fail-closed），
一次性返回前端总览面板所需的全部聚合数据：

- ``durable_queues``：durable 队列（``procrastinate_jobs``）按 queue×status 的深度
  （index/graph/page_index/crawl_ingest/maintenance）；
- ``subagent``：SubAgent 会话（repo_summary / coding / explore …）按 task_type×status
  计数 + 最近活跃（pending/running）项；
- ``repositories``：仓库索引 / 图谱 / AI 描述三类状态计数 + 进行中列表；
- ``orchestration``：对话编排（``OrchestrationRun``）活跃计数；
- ``runners``：各 Runner 在线/并发/心跳，附最近一次心跳上报的 CPU/内存/磁盘负载
  （Runner 与全部容器同机，等价主机负载）。

只读、不暴露任何写入入口。procrastinate 表不存在时（SQLite / in-process fallback）
优雅降级为空，不报错。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.db import connection
from django.db.models import Count
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from permissions.api_permissions import IsSuperUser

logger = structlog.get_logger(__name__)

# 单个列表下钻的返回上限（防止超大返回拖慢面板首屏）。
_ACTIVE_LIMIT = 100

# 心跳 detail 里的负载指标键（与 runners.consumers._handle_heartbeat 的 _METRIC_KEYS 对齐）。
_LOAD_KEYS = (
    "cpu_percent",
    "mem_percent",
    "mem_total_mb",
    "mem_used_mb",
    "disk_percent",
    "disk_total_gb",
    "disk_used_gb",
)


def _durable_queue_stats() -> dict[str, Any]:
    """durable 队列深度：按 queue_name×status 分组计数 + 各 status 汇总。

    直接读 procrastinate_jobs 表（durable 适配层之外唯一的只读统计场景，不入队、
    不操作任务）。表不存在（SQLite / 未启用 durable）时优雅降级为空。
    """
    by_queue_status: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT queue_name, status, COUNT(*) "
                "FROM procrastinate_jobs "
                "GROUP BY queue_name, status"
            )
            for queue_name, status, count in cursor.fetchall():
                by_queue_status.append(
                    {"queue": queue_name, "status": status, "count": count}
                )
                totals[status] = totals.get(status, 0) + count
    except Exception:  # noqa: BLE001 — 表不存在/未启用 durable 时降级，不影响面板
        logger.debug("observability_durable_unavailable", exc_info=True)
    return {"by_queue_status": by_queue_status, "totals": totals}


def _count_by(qs, field: str) -> dict[str, int]:
    """``qs.values(field).annotate(Count)`` → ``{field_value: count}``。"""
    return {
        row[field]: row["n"]
        for row in qs.values(field).annotate(n=Count("id")).order_by()
    }


def _subagent_stats() -> dict[str, Any]:
    from subagent.models import SubAgentSession

    base = SubAgentSession.objects.all()
    by_type_status = [
        {"task_type": row["task_type"], "status": row["status"], "count": row["n"]}
        for row in base.values("task_type", "status")
        .annotate(n=Count("id"))
        .order_by()
    ]

    active_statuses = [SubAgentSession.Status.PENDING, SubAgentSession.Status.RUNNING]
    active = []
    for s in (
        base.filter(status__in=active_statuses)
        .order_by("-updated_at")[:_ACTIVE_LIMIT]
    ):
        raw = s.last_output if isinstance(s.last_output, dict) else {}
        active.append(
            {
                "session_id": s.session_id,
                "task_type": s.task_type,
                "status": s.status,
                "repository_id": raw.get("repository_id", ""),
                "runner_id": str(s.runner_id) if s.runner_id else "",
                "updated_at": s.updated_at.isoformat(),
            }
        )
    return {"by_type_status": by_type_status, "active": active}


def _repository_stats() -> dict[str, Any]:
    from repositories.models import Repository

    qs = Repository.objects.filter(is_deleted=False)
    return {
        "total": qs.count(),
        "index_status": _count_by(qs, "index_status"),
        "graph_status": _count_by(qs, "graph_build_status"),
        "ai_summary_status": _count_by(qs, "ai_summary_status"),
    }


def _orchestration_stats() -> dict[str, int]:
    from orchestration.models import OrchestrationRun

    return _count_by(OrchestrationRun.objects.all(), "status")


def _runner_load() -> list[dict[str, Any]]:
    from runners.models import Runner, RunnerEvent

    runners: list[dict[str, Any]] = []
    for r in Runner.objects.filter(is_active=True).order_by("name"):
        latest_hb = (
            RunnerEvent.objects.filter(
                runner_id=r.id, event_type=RunnerEvent.EventType.HEARTBEAT
            )
            .order_by("-created_at")
            .first()
        )
        load = {}
        if latest_hb and isinstance(latest_hb.detail, dict):
            load = {k: latest_hb.detail.get(k) for k in _LOAD_KEYS if k in latest_hb.detail}
        runners.append(
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "current_tasks": r.current_tasks,
                "concurrent": r.concurrent,
                "version": r.version,
                "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
                "load": load,
            }
        )
    return runners


class ObservabilityView(APIView):
    """超管任务与系统总览（OBS-01，IsSuperUser fail-closed，只读）。"""

    permission_classes = [IsSuperUser]

    def get(self, request: Request) -> Response:
        payload = {
            "generated_at": timezone.now().isoformat(),
            "durable_queues": _durable_queue_stats(),
            "subagent": _subagent_stats(),
            "repositories": _repository_stats(),
            "orchestration": _orchestration_stats(),
            "runners": _runner_load(),
        }
        logger.info(
            "observability_served",
            runner_count=len(payload["runners"]),
            subagent_active=len(payload["subagent"]["active"]),
        )
        return Response(payload)
