"""feedback app 用户端 URL 配置。

挂载点见 ``friday/urls.py``：``path("feedback/", include("feedback.urls"))``
→ ``/api/feedback/...``。
"""

from __future__ import annotations

from django.urls import path

from feedback.api.views import (
    FeedbackAttachmentUploadView,
    FeedbackAttachmentView,
    FeedbackDetailView,
    FeedbackListCreateView,
)

app_name = "feedback"

urlpatterns = [
    path("", FeedbackListCreateView.as_view(), name="feedback-list-create"),
    path("attachments/", FeedbackAttachmentUploadView.as_view(), name="feedback-attachment-upload"),
    path(
        "attachments/<str:file_name>/",
        FeedbackAttachmentView.as_view(),
        name="feedback-attachment",
    ),
    path("<uuid:feedback_id>/", FeedbackDetailView.as_view(), name="feedback-detail"),
]
