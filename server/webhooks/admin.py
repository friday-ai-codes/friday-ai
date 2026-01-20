"""Webhooks admin configuration."""
from django.contrib import admin
from .models import WebhookLog, WorkItemLog
@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
 """Admin for WebhookLog model."""
 list_display = ["event_type", "project_key", "status", "created_at"]
 list_filter = ["status", "event_type", "created_at"]
 search_fields = ["event_uuid", "project_key"]
 ordering = ["-created_at"]
 readonly_fields = ["created_at"]
@admin.register(WorkItemLog)
class WorkItemLogAdmin(admin.ModelAdmin):
 """Admin for WorkItemLog model."""
 list_display = ["work_item_id", "work_item_type", "project_key", "created_at"]
 list_filter = ["work_item_type", "created_at"]
 search_fields = ["work_item_id", "project_key"]
 ordering = ["-created_at"]
 readonly_fields = ["created_at"]
