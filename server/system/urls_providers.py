"""Phase / 229: Provider 凭证相关 URL。
挂载于 friday/urls.py 的 /api/providers/ 前缀下。
路由结构：
- credentials/ → ProviderCredentialViewSet（Phase CRUD）
- credentials/<uuid>/ → retrieve / update / partial_update / destroy
- credentials/<uuid>/test-connection/ → ProviderCredentialTestConnectionView（Phase 就位）
说明：router 生成的 credentials/<uuid:pk>/ 与 test-connection/ 的 URL 后缀不冲突，
两者共存放置于同一 urlpatterns 下；test-connection 路径段落独立，router 的
TrailingSlashRouter 不会将其误匹配到 retrieve 视图。
"""
from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import ProviderCredentialTestConnectionView, ProviderCredentialViewSet
router = DefaultRouter
router.register(
 r"credentials",
 ProviderCredentialViewSet,
 basename="provider-credential",
)
urlpatterns = [
 # Phase：健康检查端点（保留既有实现，route 独立于 ViewSet）
 path(
 "credentials/<uuid:credential_id>/test-connection/",
 ProviderCredentialTestConnectionView.as_view,
 name="provider-credential-test-connection",
 ),
 # Phase / /：ViewSet CRUD
 *router.urls,
]
