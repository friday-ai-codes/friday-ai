"""Webhooks URL configuration."""
from django.urls import path
from .views import FeishuWebhookView, GitHubWebhookView
urlpatterns = [
 path("feishu", FeishuWebhookView.as_view, name="feishu-webhook"),
 path("github", GitHubWebhookView.as_view, name="github-webhook"),
]
