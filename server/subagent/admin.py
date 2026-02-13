"""Django Admin 配置 for subagent models."""
from django.contrib import admin
from subagent.models import ActionLog, InteractionLog, SubAgentOutput, SubAgentSession, TaskResult, TokenUsage
@admin.register(SubAgentSession)
class SubAgentSessionAdmin(admin.ModelAdmin):
 list_display = [
 "id",
 "session_id",
 "task_type",
 "status",
 "health_status",
 "created_at",
 "started_at",
 "completed_at",
 ]
 list_filter = ["status", "task_type", "health_status"]
 search_fields = ["session_id", "repo_url", "container_name"]
 readonly_fields = ["created_at", "updated_at", "started_at", "completed_at"]
 raw_id_fields = ["main_session", "node_execution"]
@admin.register(TaskResult)
class TaskResultAdmin(admin.ModelAdmin):
 list_display = ["id", "session", "result_type", "duration_ms", "created_at"]
 list_filter = ["result_type"]
 search_fields = ["session__session_id"]
 raw_id_fields = ["session"]
@admin.register(InteractionLog)
class InteractionLogAdmin(admin.ModelAdmin):
 list_display = [
 "id",
 "session",
 "question_text_preview",
 "is_answered",
 "asked_at",
 "answered_at",
 "reminder_count",
 ]
 list_filter = ["answered_at", "answer_source", "asked_at"]
 search_fields = ["question_text", "answer_text", "session__session_id"]
 readonly_fields = ["asked_at"]
 raw_id_fields = ["session"]
 @admin.display(description="问题预览")
 def question_text_preview(self, obj: InteractionLog) -> str:
 return obj.question_text[:50] + "..." if len(obj.question_text) > 50 else obj.question_text
 @admin.display(boolean=True, description="已回复")
 def is_answered(self, obj: InteractionLog) -> bool:
 return obj.is_answered
@admin.register(SubAgentOutput)
class SubAgentOutputAdmin(admin.ModelAdmin):
 list_display = ["id", "task_id", "session", "created_at"]
 search_fields = ["task_id"]
 raw_id_fields = ["session"]
@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
 """ActionLog Django Admin 配置。"""
 list_display = [
 "id",
 "session_link",
 "action_type",
 "sequence",
 "timestamp",
 "duration_ms",
 "payload_preview",
 ]
 list_filter = ["action_type", "timestamp"]
 search_fields = ["session__session_id", "payload"]
 readonly_fields = ["session", "action_type", "timestamp", "sequence", "payload", "duration_ms", "created_at"]
 ordering = ["-timestamp"]
 @admin.display(description="会话")
 def session_link(self, obj: ActionLog) -> str:
 from django.urls import reverse
 from django.utils.html import format_html
 url = reverse("admin:subagent_subagentsession_change", args=[obj.session.pk])
 return format_html('<a href="{}">{}</a>', url, obj.session.session_id[:16])
 @admin.display(description="载荷预览")
 def payload_preview(self, obj: ActionLog) -> str:
 import json
 preview = json.dumps(obj.payload, ensure_ascii=False)[:100]
 return preview + "..." if len(json.dumps(obj.payload)) > 100 else preview
@admin.register(TokenUsage)
class TokenUsageAdmin(admin.ModelAdmin):
 """TokenUsage Django Admin 配置。"""
 list_display = [
 "id",
 "session_link",
 "model",
 "input_tokens",
 "output_tokens",
 "total_tokens_display",
 "total_cost_usd",
 "source",
 "recorded_at",
 ]
 list_filter = ["model", "source", "recorded_at"]
 search_fields = ["session__session_id", "model"]
 readonly_fields = [
 "session",
 "input_tokens",
 "output_tokens",
 "cache_read_tokens",
 "cache_write_tokens",
 "total_cost_usd",
 "model",
 "source",
 "recorded_at",
 ]
 ordering = ["-recorded_at"]
 @admin.display(description="会话")
 def session_link(self, obj: TokenUsage) -> str:
 from django.urls import reverse
 from django.utils.html import format_html
 url = reverse("admin:subagent_subagentsession_change", args=[obj.session.pk])
 return format_html('<a href="{}">{}</a>', url, obj.session.session_id[:16])
 @admin.display(description="总 Token")
 def total_tokens_display(self, obj: TokenUsage) -> int:
 return obj.total_tokens
