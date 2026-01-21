"""Feishu URL configuration."""
from django.urls import path, re_path
from .views import (
 FeishuConfigTestView,
 FeishuConfigView,
 FeishuWebhookView,
 RefreshWebhookTokenView,
 TriggerLogDetailView,
 TriggerLogListView,
 TriggerLogRawView,
 UpdateWebhookTokenView,
)
urlpatterns = [
 # Webhook endpoint
 path("webhook", FeishuWebhookView.as_view, name="feishu-webhook"),
 # Config management (per project)
 re_path(
 r"^projects/(?P<project_id>[0-9a-f-]+)/config/?$",
 FeishuConfigView.as_view,
 name="feishu-config",
 ),
 re_path(
 r"^projects/(?P<project_id>[0-9a-f-]+)/config/test/?$",
 FeishuConfigTestView.as_view,
 name="feishu-config-test",
 ),
 re_path(
 r"^projects/(?P<project_id>[0-9a-f-]+)/refresh-token/?$",
 RefreshWebhookTokenView.as_view,
 name="feishu-refresh-token",
 ),
 re_path(
 r"^projects/(?P<project_id>[0-9a-f-]+)/token/?$",
 UpdateWebhookTokenView.as_view,
 name="feishu-update-token",
 ),
 # Logs
 path("logs", TriggerLogListView.as_view, name="feishu-logs"),
 re_path(
 r"^logs/(?P<log_id>[0-9a-f-]+)/?$",
 TriggerLogDetailView.as_view,
 name="feishu-log-detail",
 ),
 re_path(
 r"^logs/(?P<log_id>[0-9a-f-]+)/raw/?$",
 TriggerLogRawView.as_view,
 name="feishu-log-raw",
 ),
]
