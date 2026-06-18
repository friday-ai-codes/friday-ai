"""系统公告管理端 URL 配置（IsSuperUser）。

挂载点见 ``friday/urls.py``：
``path("admin/announcements/", include("notifications.admin_urls"))``
→ ``/api/admin/announcements/...``。
"""

from __future__ import annotations

from django.urls import path

from notifications.api.admin_views import (
    AdminAnnouncementDetailView,
    AdminAnnouncementListCreateView,
    AdminAnnouncementReadStatusView,
)

app_name = "announcements_admin"

urlpatterns = [
    path("", AdminAnnouncementListCreateView.as_view(), name="admin-announcement-list"),
    path(
        "<uuid:announcement_id>/",
        AdminAnnouncementDetailView.as_view(),
        name="admin-announcement-detail",
    ),
    path(
        "<uuid:announcement_id>/read-status/",
        AdminAnnouncementReadStatusView.as_view(),
        name="admin-announcement-read-status",
    ),
]
