"""Django URL patterns fixture.

Covers: path(), re_path(), url(), DefaultRouter with register().
"""
from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from . import views
from .viewsets import UserViewSet

# Router setup (Layer 3)
router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    # Layer 2: path() patterns
    path("api/users/", views.user_list, name="user-list"),
    path("api/users/<int:id>/", views.user_detail, name="user-detail"),
    path("api/users/<int:id>/delete/", views.user_delete, name="user-delete"),

    # re_path() with regex
    re_path(r"^api/legacy/users/(?P<id>[0-9]+)/$", views.user_detail),

    # include() with router URLs
    path("api/", include(router.urls)),
]
