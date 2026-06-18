"""feedback app 管理端 URL 配置（IsSuperUser）。

挂载点见 ``friday/urls.py``：``path("admin/feedback/", include("feedback.admin_urls"))``
→ ``/api/admin/feedback/...``。
"""

from __future__ import annotations

from django.urls import path

from feedback.api.admin_views import (
    AdminFeedbackDetailView,
    AdminFeedbackListView,
    AdminFeedbackReplyView,
)

app_name = "feedback_admin"

urlpatterns = [
    path("", AdminFeedbackListView.as_view(), name="admin-feedback-list"),
    path("<uuid:feedback_id>/", AdminFeedbackDetailView.as_view(), name="admin-feedback-detail"),
    path(
        "<uuid:feedback_id>/reply/",
        AdminFeedbackReplyView.as_view(),
        name="admin-feedback-reply",
    ),
]
