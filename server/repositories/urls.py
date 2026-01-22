"""Repositories URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import RepositoryViewSet, SetAccessTokenView
router = DefaultRouter(trailing_slash=False)
router.register("", RepositoryViewSet, basename="repository")
urlpatterns = [
 path("", include(router.urls)),
 path("<uuid:repository_id>/credential/access-token", SetAccessTokenView.as_view, name="set-access-token"),
]
