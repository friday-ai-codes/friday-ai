"""URL configuration for SubAgent API endpoints."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from subagent.views import ExecutionContextViewSet
router = DefaultRouter
router.register("execution-contexts", ExecutionContextViewSet, basename="execution-context")
urlpatterns = [
 path("", include(router.urls)),
]
