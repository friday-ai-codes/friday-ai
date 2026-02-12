"""Django Admin 配置 for subagent models."""
from django.contrib import admin
from subagent.models import InteractionLog, SubAgentOutput, SubAgentSession, TaskResult
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
