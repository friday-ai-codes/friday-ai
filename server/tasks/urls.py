"""Tasks URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import TaskStatusCallbackView, TaskViewSet
router = DefaultRouter(trailing_slash=False)
router.register("", TaskViewSet, basename="task")
urlpatterns = [
 path("", include(router.urls)),
 path("<uuid:task_id>/status", TaskStatusCallbackView.as_view, name="task-status-callback"),
]
