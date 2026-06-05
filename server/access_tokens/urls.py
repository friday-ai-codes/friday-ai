"""access_tokens URL configuration。"""

from adrf.routers import DefaultRouter
from django.urls import include, path

from .views import AccessTokenViewSet

router = DefaultRouter()
router.register("", AccessTokenViewSet, basename="access-token")

urlpatterns = [
    path("", include(router.urls)),
]
