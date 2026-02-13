"""URL configuration for SubAgent API endpoints."""
from django.urls import path
from .views import SubAgentCallbackView
urlpatterns = [
 path("callback/", SubAgentCallbackView.as_view, name="subagent-callback"),
]
