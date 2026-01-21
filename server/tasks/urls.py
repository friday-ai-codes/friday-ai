"""Tasks URL configuration."""
from django.urls import include, path, re_path
from common.routers import FlexibleSlashRouter
from .views import TaskStatusCallbackView, TaskViewSet
router = FlexibleSlashRouter
router.register("", TaskViewSet, basename="task")
urlpatterns = [
 path("", include(router.urls)),
 re_path(
 r"^(?P<task_id>[0-9a-f-]+)/status/?$",
 TaskStatusCallbackView.as_view,
 name="task-status-callback",
 ),
]
