"""审计事件 Django admin —— 只读注册。

AuditEvent 为 append-only 模型，admin 只提供查询/筛选能力，
禁用新增、修改、删除操作。
"""

from django.contrib import admin

from audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "actor_display",
        "action",
        "target_type",
        "target_id",
        "source",
    )
    list_filter = ("action", "source", "target_type")
    search_fields = ("actor_display", "action", "target_id")
    readonly_fields = [f.name for f in AuditEvent._meta.get_fields()]
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
