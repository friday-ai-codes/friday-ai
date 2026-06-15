"""Audit REST API URL 配置。"""

from django.urls import path

from .views import AuditEventDetailView, AuditEventExportView, AuditEventListView

urlpatterns = [
    path("audit-events/", AuditEventListView.as_view(), name="audit-event-list"),
    path(
        "audit-events/<uuid:pk>/",
        AuditEventDetailView.as_view(),
        name="audit-event-detail",
    ),
    path(
        "audit-events/export/",
        AuditEventExportView.as_view(),
        name="audit-event-export",
    ),
]
