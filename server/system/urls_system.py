"""System-level URL configuration (挂载于 /api/system/)。"""

from django.urls import path

from .dashboard_views import DashboardStatsView
from .drilldown_views import CallDrilldownView, ConversationDrilldownView
from .health_views import SystemHealthView
from .log_views import SystemLogClearView, SystemLogQueryView
from .metrics_views import MetricsQueryView, MetricsSnapshotView
from .observability_views import ObservabilityView
from .setup_views import (
    SetupFeishuWizardView,
    SetupRagWizardView,
    SetupSecurityCheckView,
)
from .tasks_views import ActiveTasksView
from .webhook_views import WebhookEventDetailView, WebhookEventListView

urlpatterns = [
    path("health/", SystemHealthView.as_view(), name="system-health"),
    # 首页 Dashboard 聚合统计（累计 + 今日新增 + 进行中）
    path("dashboard/stats/", DashboardStatsView.as_view(), name="system-dashboard-stats"),
    # 任务中心：排队中/进行中的后台任务列表（索引 / AI 描述 / durable 队列）
    path("tasks/", ActiveTasksView.as_view(), name="system-active-tasks"),
    # 超管可观测总览（OBS-01）：任务队列全景 + 系统/Runner 负载（IsSuperUser）
    path("observability/", ObservabilityView.as_view(), name="system-observability"),
    # 指标快照（QUERY-02）：一次性聚合 SNAP-01~05 当前值（IsSuperUser）。
    path("metrics/snapshot/", MetricsSnapshotView.as_view(), name="system-metrics-snapshot"),
    # 时序查询（QUERY-01 / SLA-01 / RATE-03）：metric × start/end/step × dimension × agg。
    path("metrics/query/", MetricsQueryView.as_view(), name="system-metrics-query"),
    # 运维监控「系统日志」：按条件批量清理（LOG-08，IsSuperUser）。
    # 必须排在 logs/ 之前，保持显式路由顺序惯例（避免被通配/前缀语义影响）。
    path("logs/clear/", SystemLogClearView.as_view(), name="system-logs-clear"),
    # 运维监控「系统日志」：基于 SystemLogEntry 的查询/筛选/全文 + 四计数（LOG-01/03）。
    path("logs/", SystemLogQueryView.as_view(), name="system-logs"),
    # 入站 webhook 原始留痕（LOG-07）：列表 + 单条原始详情（已脱敏，IsSuperUser）。
    path("webhooks/", WebhookEventListView.as_view(), name="system-webhooks"),
    path(
        "webhooks/<int:event_id>/",
        WebhookEventDetailView.as_view(),
        name="system-webhook-detail",
    ),
    # 调用下钻（LOG-04）：MCP 调用归因（request_id/run_id）+ AI 对话会话原始（conversation_id）。
    path("calls/drilldown/", CallDrilldownView.as_view(), name="system-call-drilldown"),
    path(
        "conversations/<uuid:conversation_id>/drilldown/",
        ConversationDrilldownView.as_view(),
        name="system-conversation-drilldown",
    ),
    # 首启向导 Phase 4：安全校验（只读，非阻塞）+ 飞书 / 向量检索可选配置编排
    path("security-check/", SetupSecurityCheckView.as_view(), name="setup-security-check"),
    path("setup-feishu/", SetupFeishuWizardView.as_view(), name="setup-feishu"),
    path("setup-rag/", SetupRagWizardView.as_view(), name="setup-rag"),
]
