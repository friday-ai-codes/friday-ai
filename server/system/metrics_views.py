"""超管指标快照 API（QUERY-02）：一次性聚合 SNAP-01~05 当前值。

单一只读端点 ``GET /api/system/metrics/snapshot/``（``IsSuperUser`` fail-closed，
沿用 observability_views 惯例），调 ``snapshot_service.collect_snapshot`` 取主机/DB/
Redis/Qdrant/并发排队五源当前值 + 队列计数。各源已逐源 best-effort 兜底，视图层
不再吞业务异常（鉴权/序列化错误正常 500）。

``/api/system/metrics/*`` 前缀在中间件打 ``synthetic`` 隔离——快照/查询入口自身的
QPS 不污染业务 SLA/QPS 统计（per 73-CONTEXT specifics）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from adrf.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response

from permissions.api_permissions import IsSuperUser
from system import snapshot_service

logger = structlog.get_logger(__name__)


class MetricsSnapshotView(APIView):
    """GET /api/system/metrics/snapshot/ — 聚合返回 SNAP-01~05 当前值（IsSuperUser）。

    ``get`` 为 ``async``：``collect_snapshot`` 内 ``asyncio.all_tasks()`` 需在事件循环线程内取。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        started = time.perf_counter()
        data: dict[str, Any] = await snapshot_service.collect_snapshot()

        # 附队列四计数（指标/日志落库 sink），best-effort——import/调用失败忽略。
        counters: dict[str, Any] = {}
        try:
            from system import metric_sink

            counters["request_metric"] = metric_sink.snapshot_counters()
        except Exception:  # noqa: BLE001 — 计数采集失败不影响快照
            pass
        try:
            from system import log_sink

            counters["system_log"] = log_sink.snapshot_counters()
        except Exception:  # noqa: BLE001
            pass
        data["counters"] = counters

        logger.info(
            "metrics_snapshot_served",
            duration_ms=int((time.perf_counter() - started) * 1000),
            host_available=bool(data.get("host", {}).get("available")),
            db_available=bool(data.get("db", {}).get("available")),
            category="caller",
            component="metrics",
        )
        return Response(data)
