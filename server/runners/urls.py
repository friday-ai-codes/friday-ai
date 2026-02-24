"""Runners URL configuration."""
from django.urls import include, path
from adrf.routers import DefaultRouter
from .views import (
 RegistrationTokenViewSet,
 RunnerRegisterView,
 RunnerUnregisterView,
 RunnerVerifyView,
 RunnerViewSet,
)
token_router = DefaultRouter
token_router.register("", RegistrationTokenViewSet, basename="registration-token")
runner_router = DefaultRouter
runner_router.register("", RunnerViewSet, basename="runner")
urlpatterns = [
 path("tokens/", include(token_router.urls)),
 path("register/", RunnerRegisterView.as_view, name="runner-register"),
 path("unregister/", RunnerUnregisterView.as_view, name="runner-unregister"),
 path("verify/", RunnerVerifyView.as_view, name="runner-verify"),
 path("", include(runner_router.urls)),
]
