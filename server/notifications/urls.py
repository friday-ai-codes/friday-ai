"""notifications app URL 配置（站内信，owner-scoped）。

挂载点见 ``friday/urls.py``：``path("notifications/", include("notifications.urls"))``
→ ``/api/notifications/...``。
"""

from __future__ import annotations

from django.urls import path

from notifications.api.views import (
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
    NotificationUnreadCountView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path("read-all/", NotificationReadAllView.as_view(), name="notification-read-all"),
    path("<uuid:notification_id>/read/", NotificationReadView.as_view(), name="notification-read"),
]
