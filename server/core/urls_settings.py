"""Settings URL configuration."""
from django.urls import re_path
from .views import SettingsDetailView, SettingsListCreateView
urlpatterns = [
 re_path(r"^$", SettingsListCreateView.as_view, name="settings-list"),
 re_path(r"^(?P<key>[^/]+)/?$", SettingsDetailView.as_view, name="settings-detail"),
]
