"""交付知识图谱 admin 注册（开发调试用，最小化）。"""

from __future__ import annotations

from django.contrib import admin

from knowledge.models import KnowledgeEdge, KnowledgeEntity, KnowledgeEntityVersion


@admin.register(KnowledgeEntity)
class KnowledgeEntityAdmin(admin.ModelAdmin):
    """KnowledgeEntity 最小 admin。"""

    list_display = ("id", "kind", "origin", "source_kind", "source_id", "title", "event_time")
    list_filter = ("kind", "origin")
    search_fields = ("source_id", "title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(KnowledgeEntityVersion)
class KnowledgeEntityVersionAdmin(admin.ModelAdmin):
    """KnowledgeEntityVersion 最小 admin。"""

    list_display = ("id", "entity", "version", "is_latest", "valid_at", "invalid_at")
    list_filter = ("is_latest",)
    readonly_fields = ("created_at",)


@admin.register(KnowledgeEdge)
class KnowledgeEdgeAdmin(admin.ModelAdmin):
    """KnowledgeEdge 最小 admin。"""

    list_display = ("id", "source_entity", "target_entity", "relation", "valid_at", "invalid_at")
    list_filter = ("relation",)
    readonly_fields = ("created_at",)
