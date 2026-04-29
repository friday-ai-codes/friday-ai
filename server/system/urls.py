"""Settings URL configuration."""
from django.urls import path
from .views import (
 FeishuIMTestView,
 SettingsDetailView,
 SettingsListCreateView,
 SystemBackupView,
 SystemInfoView,
)
urlpatterns = [
 path("", SettingsListCreateView.as_view, name="settings-list"),
 # Phase 通用设置扩展（必须排在 <str:key>/ 之前，否则会被通配路由拦截）
 path("info/", SystemInfoView.as_view, name="system-info"),
 path("backup/", SystemBackupView.as_view, name="system-backup"),
 path("feishu-im/test/", FeishuIMTestView.as_view, name="feishu-im-test"),
 path("<str:key>/", SettingsDetailView.as_view, name="settings-detail"),
]
