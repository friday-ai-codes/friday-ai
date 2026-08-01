"""Settings URL configuration."""

from django.urls import path

from .views import (
    FeishuIMTestView,
    RepoRouterWeightConfigView,
    SettingsDetailView,
    SettingsListCreateView,
    SystemBackupView,
    SystemInfoView,
)

urlpatterns = [
    path("", SettingsListCreateView.as_view(), name="settings-list"),
    # implementation 通用设置扩展（必须排在 <str:key>/ 之前，否则会被通配路由拦截）
    path("info/", SystemInfoView.as_view(), name="system-info"),
    path("backup/", SystemBackupView.as_view(), name="system-backup"),
    path("feishu-im/test/", FeishuIMTestView.as_view(), name="feishu-im-test"),
    # 仓库路由权重配置专用端点（Phase 106-02，ROUTE-06）——同样必须排在 <str:key>/ 之前
    path(
        "repo-router/weight-config/",
        RepoRouterWeightConfigView.as_view(),
        name="repo-router-weight-config",
    ),
    path("<str:key>/", SettingsDetailView.as_view(), name="settings-detail"),
]
