"""System-level URL configuration (挂载于 /api/system/)。"""

from django.urls import path

from .health_views import SystemHealthView
from .setup_views import (
    SetupFeishuWizardView,
    SetupRagWizardView,
    SetupSecurityCheckView,
)

urlpatterns = [
    path("health/", SystemHealthView.as_view(), name="system-health"),
    # 首启向导 Phase 4：安全校验（只读，非阻塞）+ 飞书 / 向量检索可选配置编排
    path("security-check/", SetupSecurityCheckView.as_view(), name="setup-security-check"),
    path("setup-feishu/", SetupFeishuWizardView.as_view(), name="setup-feishu"),
    path("setup-rag/", SetupRagWizardView.as_view(), name="setup-rag"),
]
