"""入站 Git 平台 MR webhook URL（/api/git-webhooks/，MR-02）。"""

from django.urls import path

from initiatives.webhook_views import GitMergeRequestWebhookView

urlpatterns = [
    path(
        "<str:platform>/",
        GitMergeRequestWebhookView.as_view(),
        name="git-mr-webhook",
    ),
]
