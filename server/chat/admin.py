"""Django admin 注册：chat 应用下需要管理后台可见的模型。
当前仅注册 ``RepositoryRoutingTrace``（Phase）—— 跨仓路由决策的
可审计落地表，只读，不允许通过 admin 编辑。
"""
from __future__ import annotations
from typing import Any
from django.contrib import admin
from chat.models import RepositoryRoutingTrace
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
