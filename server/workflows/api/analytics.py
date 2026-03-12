"""执行分析 API 视图。
提供 5 个聚合查询端点，为前端仪表盘提供预聚合数据。
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
import structlog
from django.db.models import Avg, Case, Count, F, Q, Sum, When
from django.db.models.functions import TruncDate
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from subagent.models import TokenUsage
from workflows.api.analytics_serializers import (
 AnalyticsOverviewSerializer,
 DurationBucketSerializer,
 NodePerformanceSerializer,
 TokenCostDataPointSerializer,
 TrendDataPointSerializer,
)
from workflows.models import (
 ExecutionStatus,
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
)
logger = structlog.get_logger(__name__)
def _parse_date_range(request: Request) -> tuple[date, date]:
 """解析 date_from / date_to 查询参数，默认近 7 天。"""
 today = date.today
 default_from = today - timedelta(days=7)
 date_from_str = request.query_params.get("date_from")
 date_to_str = request.query_params.get("date_to")
 try:
 date_from = date.fromisoformat(date_from_str) if date_from_str else default_from
 except ValueError:
 date_from = default_from
 try:
 date_to = date.fromisoformat(date_to_str) if date_to_str else today
 except ValueError:
 date_to = today
 return date_from, date_to
class AnalyticsOverviewView(APIView):
 """KPI 概览：执行总数、成功率、平均时长、总成本。"""
 permission_classes = [IsAuthenticated]
 def get(self, request: Request) -> Response:
 date_from, date_to = _parse_date_range(request)
 logger.info("analytics.overview", date_from=str(date_from), date_to=str(date_to))
 # 查询时间范围内的执行记录
 executions = WorkflowExecution.objects.filter(
 created_at__date__gte=date_from,
 created_at__date__lte=date_to,
 )
 total = executions.count
 completed = executions.filter(status=ExecutionStatus.COMPLETED).count
 failed = executions.filter(status=ExecutionStatus.FAILED).count
 # 成功率 = completed / (completed + failed)，排除 running/pending 等中间状态
 finished = completed + failed
 success_rate = (completed / finished * 100) if finished > 0 else 0.0
 # 平均时长（秒）— 使用数据库计算 completed_at - started_at
 duration_agg = executions.filter(
 status=ExecutionStatus.COMPLETED,
 started_at__isnull=False,
 completed_at__isnull=False,
 ).aggregate(avg_duration=Avg(F("completed_at") - F("started_at")))
 avg_duration_td = duration_agg["avg_duration"]
 avg_duration_seconds = avg_duration_td.total_seconds if avg_duration_td else None
 # 总成本 — 通过关联链查询 TokenUsage
 cost_agg = TokenUsage.objects.filter(
 session__node_execution__workflow_execution__created_at__date__gte=date_from,
 session__node_execution__workflow_execution__created_at__date__lte=date_to,
 ).aggregate(total_cost=Sum("total_cost_usd"))
 total_cost: Decimal | None = cost_agg["total_cost"]
 data = {
 "total_executions": total,
 "success_rate": round(success_rate, 2),
 "avg_duration_seconds": round(avg_duration_seconds, 2) if avg_duration_seconds is not None else None,
 "total_cost_usd": float(total_cost) if total_cost else 0.0,
 }
 serializer = AnalyticsOverviewSerializer(data)
 return Response(serializer.data)
class TrendView(APIView):
 """成功/失败趋势：按日聚合。"""
 permission_classes = [IsAuthenticated]
 def get(self, request: Request) -> Response:
 date_from, date_to = _parse_date_range(request)
 logger.info("analytics.trends", date_from=str(date_from), date_to=str(date_to))
 daily_stats: Any = (
 WorkflowExecution.objects.filter(
 created_at__date__gte=date_from,
 created_at__date__lte=date_to,
 )
 .annotate(exec_date=TruncDate("created_at"))
 .values("exec_date")
 .annotate(
 completed=Count(
 Case(When(status=ExecutionStatus.COMPLETED, then=1))
 ),
 failed=Count(
 Case(When(status=ExecutionStatus.FAILED, then=1))
 ),
 total=Count("id"),
 )
 .order_by("exec_date")
 )
 data = [
 {
 "date": str(row["exec_date"]),
 "completed": row["completed"],
 "failed": row["failed"],
 "total": row["total"],
 }
 for row in daily_stats
 ]
 serializer = TrendDataPointSerializer(data, many=True)
 return Response(serializer.data)
# 时长分布的分桶定义（秒）
DURATION_BUCKETS: list[tuple[str, float, float]] = [
 ("<10s", 0, 10),
 ("10-30s", 10, 30),
 ("30-60s", 30, 60),
 ("1-5min", 60, 300),
 ("5-15min", 300, 900),
 ("15-30min", 900, 1800),
 ("30min+", 1800, float("inf")),
]
class DurationDistributionView(APIView):
 """执行时长分布：按区间分桶统计。"""
 permission_classes = [IsAuthenticated]
 def get(self, request: Request) -> Response:
 date_from, date_to = _parse_date_range(request)
 logger.info("analytics.duration_distribution", date_from=str(date_from), date_to=str(date_to))
 # 查询已完成执行的时长
 completed_executions = WorkflowExecution.objects.filter(
 created_at__date__gte=date_from,
 created_at__date__lte=date_to,
 status=ExecutionStatus.COMPLETED,
 started_at__isnull=False,
 completed_at__isnull=False,
 ).values_list("started_at", "completed_at")
 # Python 端分桶
 bucket_counts: dict[str, int] = {label: 0 for label, _, _ in DURATION_BUCKETS}
 for started_at, completed_at in completed_executions:
 duration_secs = (completed_at - started_at).total_seconds
 for label, low, high in DURATION_BUCKETS:
 if low <= duration_secs < high:
 bucket_counts[label] += 1
 break
 data = [
 {"bucket_label": label, "count": bucket_counts[label]}
 for label, _, _ in DURATION_BUCKETS
 ]
 serializer = DurationBucketSerializer(data, many=True)
 return Response(serializer.data)
class TokenCostView(APIView):
 """Token 消耗和 USD 成本：按日聚合。"""
 permission_classes = [IsAuthenticated]
 def get(self, request: Request) -> Response:
 date_from, date_to = _parse_date_range(request)
 logger.info("analytics.token_cost", date_from=str(date_from), date_to=str(date_to))
 daily_tokens: Any = (
 TokenUsage.objects.filter(
 recorded_at__date__gte=date_from,
 recorded_at__date__lte=date_to,
 )
 .annotate(usage_date=TruncDate("recorded_at"))
 .values("usage_date")
 .annotate(
 input_tokens=Sum("input_tokens"),
 output_tokens=Sum("output_tokens"),
 total_cost_usd=Sum("total_cost_usd"),
 )
 .order_by("usage_date")
 )
 data = [
 {
 "date": str(row["usage_date"]),
 "input_tokens": row["input_tokens"] or 0,
 "output_tokens": row["output_tokens"] or 0,
 "total_cost_usd": float(row["total_cost_usd"] or 0),
 }
 for row in daily_tokens
 ]
 serializer = TokenCostDataPointSerializer(data, many=True)
 return Response(serializer.data)
class NodePerformanceView(APIView):
 """节点类型性能排行：按 node_type 聚合。"""
 permission_classes = [IsAuthenticated]
 def get(self, request: Request) -> Response:
 date_from, date_to = _parse_date_range(request)
 logger.info("analytics.node_performance", date_from=str(date_from), date_to=str(date_to))
 # 按 node_type 聚合 NodeExecution
 node_stats: Any = (
 NodeExecution.objects.filter(
 workflow_execution__created_at__date__gte=date_from,
 workflow_execution__created_at__date__lte=date_to,
 )
 .values("node__node_type")
 .annotate(
 execution_count=Count("id"),
 avg_duration=Avg(
 F("completed_at") - F("started_at"),
 filter=Q(
 started_at__isnull=False,
 completed_at__isnull=False,
 ),
 ),
 completed_count=Count(
 Case(When(status=NodeExecutionStatus.COMPLETED, then=1))
 ),
 failed_count=Count(
 Case(When(status=NodeExecutionStatus.FAILED, then=1))
 ),
 )
 .order_by("-execution_count")
 )
 data =
 for row in node_stats:
 finished = row["completed_count"] + row["failed_count"]
 success_rate = (row["completed_count"] / finished * 100) if finished > 0 else 0.0
 avg_td = row["avg_duration"]
 avg_secs = avg_td.total_seconds if avg_td else None
 # 关联 token 统计
 total_tokens_agg = TokenUsage.objects.filter(
 session__node_execution__node__node_type=row["node__node_type"],
 session__node_execution__workflow_execution__created_at__date__gte=date_from,
 session__node_execution__workflow_execution__created_at__date__lte=date_to,
 ).aggregate(
 tokens=Sum(F("input_tokens") + F("output_tokens"))
 )
 data.append({
 "node_type": row["node__node_type"],
 "execution_count": row["execution_count"],
 "avg_duration_seconds": round(avg_secs, 2) if avg_secs is not None else None,
 "success_rate": round(success_rate, 2),
 "total_tokens": total_tokens_agg["tokens"] or 0,
 })
 serializer = NodePerformanceSerializer(data, many=True)
 return Response(serializer.data)
