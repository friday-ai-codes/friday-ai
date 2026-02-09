"""URL configuration for SubAgent API endpoints."""
from django.urls import path
from .views import MockSubAgentTaskView, SubAgentCallbackView
urlpatterns = [
 path("tasks/", MockSubAgentTaskView.as_view, name="subagent-tasks"),
 path("callback/", SubAgentCallbackView.as_view, name="subagent-callback"),
]
