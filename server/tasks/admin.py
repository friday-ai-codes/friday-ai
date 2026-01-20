"""Tasks admin configuration."""
from django.contrib import admin
from .models import Task
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
 """Admin for Task model."""
 list_display = ["title", "project", "status", "work_item_id", "created_at"]
 list_filter = ["status", "project", "created_at"]
 search_fields = ["title", "work_item_id", "description"]
 ordering = ["-created_at"]
 readonly_fields = ["created_at", "updated_at"]
 fieldsets = [
 ("基本信息", {
 "fields": ["title", "description", "project", "repository"],
 }),
 ("飞书集成", {
 "fields": ["work_item_id", "feature_id"],
 }),
 ("Git 信息", {
 "fields": ["branch_name", "commit_sha", "pr_url"],
 }),
 ("执行状态", {
 "fields": ["status", "error_message", "retry_count", "human_feedback"],
 }),
 ("Claude Code", {
 "fields": ["session_id", "plan_output"],
 "classes": ["collapse"],
 }),
 ("时间戳", {
 "fields": [
 "created_at", "updated_at",
 "plan_started_at", "plan_completed_at",
 "execute_started_at", "execute_completed_at",
 ],
 "classes": ["collapse"],
 }),
 ]
