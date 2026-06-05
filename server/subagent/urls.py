"""URL configuration for SubAgent API endpoints."""

from adrf.routers import DefaultRouter
from django.urls import include, path

from subagent.views import ExecutionContextViewSet

router = DefaultRouter()
router.register("execution-contexts", ExecutionContextViewSet, basename="execution-context")

urlpatterns = [
    path("", include(router.urls)),
]
