"""System-level URL configuration (挂载于 /api/system/)。"""

from django.urls import path

from .health_views import SystemHealthView

urlpatterns = [
    path("health/", SystemHealthView.as_view(), name="system-health"),
]
