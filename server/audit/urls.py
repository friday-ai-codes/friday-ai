"""audit app URL 配置——审计查询/导出（只读，仅 GET）。

仅注册 GET 路由：列表 / 详情 / 导出。绝不暴露写入口（append-only / 只读契约）。
挂载点见 ``friday/urls.py``：``path("audit/", include("audit.urls"))`` → ``/api/audit/...``。
"""

from __future__ import annotations

from django.urls import path

from audit.api.views import (
    AuditEventDetailView,
    AuditEventExportView,
    AuditEventListView,
)

app_name = "audit"

urlpatterns = [
    path("events/", AuditEventListView.as_view(), name="event-list"),
    path("events/export/", AuditEventExportView.as_view(), name="event-export"),
    path("events/<uuid:event_id>/", AuditEventDetailView.as_view(), name="event-detail"),
]
