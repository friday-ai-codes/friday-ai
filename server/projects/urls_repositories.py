"""Repositories URL configuration."""
from django.urls import include, path, re_path
from utils.routers import FlexibleSlashRouter
from .views import RepositoryViewSet, SetAccessTokenView
router = FlexibleSlashRouter
router.register("", RepositoryViewSet, basename="repository")
urlpatterns = [
 path("", include(router.urls)),
 re_path(
 r"^(?P<repository_id>[0-9a-f-]+)/credential/access-token/?$",
 SetAccessTokenView.as_view,
 name="set-access-token",
 ),
]
