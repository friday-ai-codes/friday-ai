"""代码关系图谱 admin 注册（开发调试用，最小化）。"""
from __future__ import annotations
from django.contrib import admin
from code_relations.models import ChunkEdge, ChunkRegistry
@admin.register(ChunkRegistry)
class ChunkRegistryAdmin(admin.ModelAdmin):
 """ChunkRegistry 最小 admin。"""
 list_display = ("chunk_id", "repository", "file_path", "chunk_index", "updated_at")
 list_filter = ("repository",)
 search_fields = ("file_path", "content_hash")
 readonly_fields = ("chunk_id", "created_at", "updated_at")
@admin.register(ChunkEdge)
class ChunkEdgeAdmin(admin.ModelAdmin):
 """ChunkEdge 最小 admin。"""
 list_display = (
 "id",
 "edge_type",
 "source_chunk_id",
 "target_chunk_id",
 "weight",
 "repository",
 )
 list_filter = ("edge_type", "repository")
 readonly_fields = ("id", "created_at")
