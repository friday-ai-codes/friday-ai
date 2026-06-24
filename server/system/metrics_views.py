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
from asgiref.sync import sync_to_async
from rest_framework.request import Request
from rest_framework.response import Response

from permissions.api_permissions import IsSuperUser
from system import metrics_query, snapshot_service

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


class MetricsQueryView(APIView):
    """GET /api/system/metrics/query/ — 时序查询（QUERY-01 / SLA-01 / RATE-03，IsSuperUser）。

    参数 ``metric``(qps/tps/sla/error/duration/ttft + gauge:<name>) × ``start``/``end``/
    ``step`` × ``dimension``(source/route/error_class/provider/call_source/model) ×
    ``agg``(p95/p90/p50/avg/max)。聚合走 ``metrics_query.query_timeseries``（Postgres
    ``percentile_cont`` 精确 / SQLite 降级兜底）。``ValueError`` → 400 中文 detail。

    ``get`` 为 ``async``（沿用 73-01 MetricsSnapshotView 范式）：raw cursor 聚合经
    ``sync_to_async`` 桥接，不在事件循环线程内做同步 ORM 访问。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        started = time.perf_counter()
        params = request.query_params
        try:
            data: dict[str, Any] = await sync_to_async(
                metrics_query.query_timeseries, thread_sensitive=True
            )(
                metric=params.get("metric", ""),
                start=params.get("start"),
                end=params.get("end"),
                step=params.get("step"),
                dimension=params.get("dimension", ""),
                agg=params.get("agg", "p95"),
            )
        except ValueError as exc:
            # 非法 metric/dimension → 400（中文 detail），不泄漏内部细节。
            return Response({"detail": str(exc)}, status=400)

        logger.info(
            "metrics_query_served",
            metric=data.get("metric"),
            step_seconds=data.get("step_seconds"),
            series_len=len(data.get("series", [])),
            degraded=data.get("degraded"),
            duration_ms=int((time.perf_counter() - started) * 1000),
            category="caller",
            component="metrics",
        )
        return Response(data)
