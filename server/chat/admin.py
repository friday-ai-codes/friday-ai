"""Django admin 注册：chat 应用下需要管理后台可见的模型。
当前仅注册 ``RepositoryRoutingTrace``（Phase）—— 跨仓路由决策的
可审计落地表，只读，不允许通过 admin 编辑。
"""
from __future__ import annotations
from typing import Any
from django.contrib import admin
from chat.models import ConversationIntentTrace, RepositoryRoutingTrace
@admin.register(RepositoryRoutingTrace)
class RepositoryRoutingTraceAdmin(admin.ModelAdmin):
 """``RepositoryRoutingTrace`` 只读 admin（Phase）。
 trace 是审计记录，不允许编辑；list_filter 提供 evaluation SQL 友好的
 triggered_by / created_at 维度过滤。
 """
 list_display = (
 "id",
 "conversation",
 "triggered_by",
 "threshold",
 "candidate_count",
 "created_at",
 )
 list_filter = ("triggered_by", "created_at")
 search_fields = ("query", "conversation__id")
 readonly_fields = (
 "id",
 "agent_session",
 "conversation",
 "query",
 "candidates",
 "threshold",
 "triggered_by",
 "created_at",
 )
 ordering = ("-created_at",)
 @admin.display(description="候选数")
 def candidate_count(self, obj: RepositoryRoutingTrace) -> int:
 return len(obj.candidates) if isinstance(obj.candidates, list) else 0
 def has_add_permission(self, request: Any) -> bool: # type: ignore[override]
 return False
 def has_change_permission(
 self, request: Any, obj: Any = None
 ) -> bool: # type: ignore[override]
 return False
@admin.register(ConversationIntentTrace)
class ConversationIntentTraceAdmin(admin.ModelAdmin):
 """``ConversationIntentTrace`` 只读 admin（Phase）。
 协商时间线属于审计记录，全字段 readonly；list_filter 提供 evaluation
 维度过滤（按时间窗 + 是否落到 plan）。
 """
 list_display = (
 "clarification_id_short",
 "conversation",
 "selected_option_id",
 "resolved_to_plan",
 "answered_at",
 "created_at",
 )
 list_filter = ("created_at", "answered_at")
 search_fields = ("clarification_id", "conversation__id", "question")
 readonly_fields = (
 "id",
 "conversation",
 "triggering_message_id",
 "clarification_id",
 "question",
 "options",
 "selected_option_id",
 "freeform_answer",
 "inferred_state",
 "resolved_to_plan",
 "created_at",
 "answered_at",
 )
 ordering = ("-created_at",)
 @admin.display(description="clarification_id")
 def clarification_id_short(self, obj: ConversationIntentTrace) -> str:
 return obj.clarification_id[:8] if obj.clarification_id else ""
 def has_add_permission(self, request: Any) -> bool: # type: ignore[override]
 return False
 def has_change_permission(
 self, request: Any, obj: Any = None
 ) -> bool: # type: ignore[override]
 return False
