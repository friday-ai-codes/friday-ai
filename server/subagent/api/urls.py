"""URL configuration for container callback endpoints (Phase)."""
from django.urls import path
from subagent.api.callbacks import ContainerCallbackView
urlpatterns = [
 path("callback/", ContainerCallbackView.as_view, name="container-callback"),
]
