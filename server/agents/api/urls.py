"""Agent API URL configuration."""

from django.urls import path

from agents.api.views import ToolListView

urlpatterns = [
    path("tools/", ToolListView.as_view(), name="tool-list"),
]
