"""Logs URL configuration."""
from django.urls import path
from .views_logs import (
 WebhookLogDetailView,
 WebhookLogListView,
 WorkItemLogDetailView,
 WorkItemLogListView,
)
urlpatterns = [
 path("webhooks", WebhookLogListView.as_view, name="webhook-log-list"),
 path("webhooks/<uuid:log_id>", WebhookLogDetailView.as_view, name="webhook-log-detail"),
 path("work-items", WorkItemLogListView.as_view, name="work-item-log-list"),
 path("work-items/<uuid:log_id>", WorkItemLogDetailView.as_view, name="work-item-log-detail"),
]
