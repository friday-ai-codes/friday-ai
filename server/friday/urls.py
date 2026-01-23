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
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
# API routes (under /api prefix)
api_patterns = [
 # Authentication (accounts app)
 path("auth/", include("accounts.urls")),
 # Projects
 path("projects/", include("projects.urls")),
 # Repositories
 path("repositories/", include("repositories.urls")),
 # Tasks
 path("tasks/", include("tasks.urls")),
 # Feishu integration (webhook + logs)
 path("feishu/", include("feishu.urls")),
 # System settings
 path("settings/", include("system.urls")),
 # Chat (LLM conversation)
 path("chat/", include("chat.urls")),
 # Workflows
 path("", include("workflows.urls")),
 # API Documentation
 path("schema", SpectacularAPIView.as_view, name="schema"),
 path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
 path("redoc", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
urlpatterns = [
 # All API endpoints under /api
 path("api/", include(api_patterns)),
 # Health check (outside /api prefix)
 path("health", include("accounts.urls_health")),
]
