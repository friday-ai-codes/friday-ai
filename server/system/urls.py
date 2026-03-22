"""Settings URL configuration."""
from django.urls import path
from .views import FeishuIMTestView, SettingsDetailView, SettingsListCreateView
urlpatterns = [
 path("", SettingsListCreateView.as_view, name="settings-list"),
 path("feishu-im/test/", FeishuIMTestView.as_view, name="feishu-im-test"),
 path("<str:key>/", SettingsDetailView.as_view, name="settings-detail"),
]
