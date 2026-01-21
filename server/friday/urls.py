"""
URL configuration for friday project.
The `urlpatterns` list routes URLs to views. For more information please see:
 https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
 1. Add an import: from my_app import views
 2. Add a URL to urlpatterns: path('', views.home, name='home')
Class-based views
 1. Add an import: from other_app.views import Home
 2. Add a URL to urlpatterns: path('', Home.as_view, name='home')
Including another URLconf
 1. Import the include function: from django.urls import include, path
 2. Add a URL to urlpatterns: path('blog/', include('blog.urls'))
"""
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
# API routes (under /api prefix)
api_patterns = [
 # Authentication (accounts app)
 re_path(r"^auth/?", include("accounts.urls")),
 # Projects
 re_path(r"^projects/?", include("projects.urls")),
 # Repositories
 re_path(r"^repositories/?", include("repositories.urls")),
 # Tasks
 re_path(r"^tasks/?", include("tasks.urls")),
 # Feishu integration (webhook + logs)
 re_path(r"^feishu/?", include("feishu.urls")),
 # System settings
 re_path(r"^settings/?", include("system.urls")),
 # API Documentation
 re_path(r"^schema/?$", SpectacularAPIView.as_view, name="schema"),
 re_path(r"^docs/?$", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
 re_path(r"^redoc/?$", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
urlpatterns = [
 # All API endpoints under /api (with or without trailing slash)
 re_path(r"^api/?", include(api_patterns)),
 # Health check (outside /api prefix)
 path("health", include("accounts.urls_health")),
]
