"""Projects URL configuration."""
from django.urls import include, path
from utils.routers import FlexibleSlashRouter
from .views import ProjectViewSet
router = FlexibleSlashRouter
router.register("", ProjectViewSet, basename="project")
urlpatterns = [
 path("", include(router.urls)),
]
