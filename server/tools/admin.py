"""Django Admin configuration for RemoteTool."""

from django.contrib import admin

from tools.models import RemoteTool


@admin.register(RemoteTool)
class RemoteToolAdmin(admin.ModelAdmin[RemoteTool]):
    list_display = ("name", "source", "is_active", "timeout", "updated_at")
    list_filter = ("source", "is_active")
    search_fields = ("name", "description")
