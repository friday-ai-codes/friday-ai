"""系统公告用户端 URL 配置（owner-scoped 可见性）。

挂载点见 ``friday/urls.py``：``path("announcements/", include("notifications.announcement_urls"))``
→ ``/api/announcements/...``。
"""

from __future__ import annotations

from django.urls import path

from notifications.api.announcement_views import (
    AnnouncementListView,
    AnnouncementPopupView,
    AnnouncementReadView,
    AnnouncementUnreadCountView,
)

app_name = "announcements"

urlpatterns = [
    path("", AnnouncementListView.as_view(), name="announcement-list"),
    path(
        "unread-count/",
        AnnouncementUnreadCountView.as_view(),
        name="announcement-unread-count",
    ),
    path("popup/", AnnouncementPopupView.as_view(), name="announcement-popup"),
    path(
        "<uuid:announcement_id>/read/",
        AnnouncementReadView.as_view(),
        name="announcement-read",
    ),
]
