"""OIDC Identity URL configuration."""
from django.urls import path
from .views import (
 OIDCAuthorizeView,
 OIDCCallbackView,
 OIDCDiscoveryView,
 OIDCProviderDetailView,
 OIDCProviderListView,
 OIDCProviderPublicListView,
)
urlpatterns = [
 # Provider 管理（超级管理员）
 path("providers/", OIDCProviderListView.as_view, name="oidc-provider-list"),
 path("providers/discovery/", OIDCDiscoveryView.as_view, name="oidc-discovery"),
 path("providers/public/", OIDCProviderPublicListView.as_view, name="oidc-provider-public"),
 path("providers/<uuid:pk>/", OIDCProviderDetailView.as_view, name="oidc-provider-detail"),
 # 授权流程
 path("authorize/<uuid:provider_id>/", OIDCAuthorizeView.as_view, name="oidc-authorize"),
 path("callback/", OIDCCallbackView.as_view, name="oidc-callback"),
]
