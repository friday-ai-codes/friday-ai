"""Audit REST API URL 配置。"""

from django.urls import path

from .views import AuditEventDetailView, AuditEventListView

urlpatterns = [
    path("audit-events/", AuditEventListView.as_view(), name="audit-event-list"),
    path(
        "audit-events/<uuid:pk>/",
        AuditEventDetailView.as_view(),
        name="audit-event-detail",
    ),
]
