"""URL configuration for SubAgent API endpoints."""
from django.urls import include, path
from adrf.routers import DefaultRouter
from subagent.views import ExecutionContextViewSet
router = DefaultRouter
router.register("execution-contexts", ExecutionContextViewSet, basename="execution-context")
urlpatterns = [
 path("", include(router.urls)),
]
