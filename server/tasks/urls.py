"""Tasks URL configuration.
⚠️ DEPRECATED: The Task API is deprecated and will be removed.
Use /api/workflows/ and /api/workflow-executions/ instead.
Migration guide: docs/migration/task-to-workflow.md
Sunset date: 2025-06-01
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from core.feature_flags import feature_flags
# Import based on feature flag - use compat views when enabled
if feature_flags.enable_task_compat_api:
 from .compat_views import TaskCompatViewSet
 router = DefaultRouter(trailing_slash=False)
 router.register("", TaskCompatViewSet, basename="task")
else:
 from .views import TaskViewSet
 router = DefaultRouter(trailing_slash=False)
 router.register("", TaskViewSet, basename="task")
# Legacy callback endpoint
from .views import TaskStatusCallbackView
urlpatterns = [
 path("", include(router.urls)),
 path("<uuid:task_id>/status", TaskStatusCallbackView.as_view, name="task-status-callback"),
]
