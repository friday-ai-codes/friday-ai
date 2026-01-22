"""Feishu URL configuration."""
from django.urls import path
from .views import (
 FeishuConfigTestView,
 FeishuConfigView,
 FeishuWebhookView,
 RefreshWebhookTokenView,
 TriggerLogDeleteView,
 TriggerLogDetailView,
 TriggerLogListView,
 TriggerLogRawView,
 TriggerLogRetryView,
 UpdateWebhookTokenView,
)
urlpatterns = [
 # Webhook endpoint
 path("webhook", FeishuWebhookView.as_view, name="feishu-webhook"),
 # Config management (per project)
 path("projects/<uuid:project_id>/config", FeishuConfigView.as_view, name="feishu-config"),
 path(
 "projects/<uuid:project_id>/config/test",
 FeishuConfigTestView.as_view,
 name="feishu-config-test",
 ),
 path(
 "projects/<uuid:project_id>/refresh-token",
 RefreshWebhookTokenView.as_view,
 name="feishu-refresh-token",
 ),
 path(
 "projects/<uuid:project_id>/token",
 UpdateWebhookTokenView.as_view,
 name="feishu-update-token",
 ),
 # Logs
 path("logs", TriggerLogListView.as_view, name="feishu-logs"),
 path("logs/<uuid:log_id>", TriggerLogDetailView.as_view, name="feishu-log-detail"),
 path("logs/<uuid:log_id>/raw", TriggerLogRawView.as_view, name="feishu-log-raw"),
 path("logs/<uuid:log_id>/delete", TriggerLogDeleteView.as_view, name="feishu-log-delete"),
 path("logs/<uuid:log_id>/retry", TriggerLogRetryView.as_view, name="feishu-log-retry"),
]
