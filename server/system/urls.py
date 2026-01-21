"""Settings URL configuration."""
from django.urls import path
from .views import SettingsDetailView, SettingsListCreateView
urlpatterns = [
 path("", SettingsListCreateView.as_view, name="settings-list"),
 path("<str:key>", SettingsDetailView.as_view, name="settings-detail"),
]
