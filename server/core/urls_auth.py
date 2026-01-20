"""Authentication URL configuration."""
from django.urls import path
from .views import (
 ChangePasswordView,
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
]
