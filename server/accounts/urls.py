"""Accounts URL configuration."""
from django.urls import path
from .views import (
 AdminChangePasswordView,
 AdminProfileView,
 ChangePasswordView,
 ForceChangePasswordView,
 LoginView,
 LogoutView,
 MeView,
 RefreshTokenView,
)
urlpatterns = [
 path("login", LoginView.as_view, name="login"),
 path("logout", LogoutView.as_view, name="logout"),
 path("refresh", RefreshTokenView.as_view, name="refresh"),
 path("me", MeView.as_view, name="me"),
 path("change-password", ChangePasswordView.as_view, name="change-password"),
 path("force-change-password", ForceChangePasswordView.as_view, name="force-change-password"),
 # Admin management endpoints
 path("admin/profile", AdminProfileView.as_view, name="admin-profile"),
 path("admin/password", AdminChangePasswordView.as_view, name="admin-password"),
]
