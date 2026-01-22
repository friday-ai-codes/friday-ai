"""Projects URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ProjectViewSet
router = DefaultRouter # trailing_slash=True by default
router.register("", ProjectViewSet, basename="project")
urlpatterns = [
 path("", include(router.urls)),
]
