"""System-level URL configuration (挂载于 /api/system/)。"""

from django.urls import path

from .dashboard_views import DashboardStatsView
from .health_views import SystemHealthView
from .log_views import SystemLogClearView, SystemLogQueryView
from .observability_views import ObservabilityView
from .setup_views import (
    SetupFeishuWizardView,
    SetupRagWizardView,
    SetupSecurityCheckView,
)
from .tasks_views import ActiveTasksView

urlpatterns = [
    path("health/", SystemHealthView.as_view(), name="system-health"),
    # 首页 Dashboard 聚合统计（累计 + 今日新增 + 进行中）
    path("dashboard/stats/", DashboardStatsView.as_view(), name="system-dashboard-stats"),
    # 任务中心：排队中/进行中的后台任务列表（索引 / AI 描述 / durable 队列）
    path("tasks/", ActiveTasksView.as_view(), name="system-active-tasks"),
    # 超管可观测总览（OBS-01）：任务队列全景 + 系统/Runner 负载（IsSuperUser）
    path("observability/", ObservabilityView.as_view(), name="system-observability"),
    # 运维监控「系统日志」：按条件批量清理（LOG-08，IsSuperUser）。
    # 必须排在 logs/ 之前，保持显式路由顺序惯例（避免被通配/前缀语义影响）。
    path("logs/clear/", SystemLogClearView.as_view(), name="system-logs-clear"),
    # 运维监控「系统日志」：基于 SystemLogEntry 的查询/筛选/全文 + 四计数（LOG-01/03）。
    path("logs/", SystemLogQueryView.as_view(), name="system-logs"),
    # 首启向导 Phase 4：安全校验（只读，非阻塞）+ 飞书 / 向量检索可选配置编排
    path("security-check/", SetupSecurityCheckView.as_view(), name="setup-security-check"),
    path("setup-feishu/", SetupFeishuWizardView.as_view(), name="setup-feishu"),
    path("setup-rag/", SetupRagWizardView.as_view(), name="setup-rag"),
]
