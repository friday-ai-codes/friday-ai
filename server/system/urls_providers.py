"""Phase: Provider 凭证相关 URL（仅 test-connection；CRUD 归 Phase）。
挂载于 friday/urls.py 的 /api/providers/ 前缀下。Phase 会在此
urls_providers.py 扩展 CRUD 路由（LIST / CREATE / RETRIEVE / UPDATE / DELETE）。
"""
from django.urls import path
from .views import ProviderCredentialTestConnectionView
urlpatterns = [
 path(
 "credentials/<uuid:credential_id>/test-connection/",
 ProviderCredentialTestConnectionView.as_view,
 name="provider-credential-test-connection",
 ),
]
