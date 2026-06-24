"""System-level URL configuration (挂载于 /api/system/)。"""

from django.urls import path

from .dashboard_views import DashboardStatsView
from .health_views import SystemHealthView
from .observability_views import ObservabilityView
from .setup_views import (
    SetupFeishuWizardView,
    SetupRagWizardView,
    SetupSecurityCheckView,
)

urlpatterns = [
    path("health/", SystemHealthView.as_view(), name="system-health"),
    # 首页 Dashboard 聚合统计（累计 + 今日新增 + 进行中）
    path("dashboard/stats/", DashboardStatsView.as_view(), name="system-dashboard-stats"),
    # 超管可观测总览（OBS-01）：任务队列全景 + 系统/Runner 负载（IsSuperUser）
    path("observability/", ObservabilityView.as_view(), name="system-observability"),
    # 首启向导 Phase 4：安全校验（只读，非阻塞）+ 飞书 / 向量检索可选配置编排
    path("security-check/", SetupSecurityCheckView.as_view(), name="setup-security-check"),
    path("setup-feishu/", SetupFeishuWizardView.as_view(), name="setup-feishu"),
    path("setup-rag/", SetupRagWizardView.as_view(), name="setup-rag"),
]
