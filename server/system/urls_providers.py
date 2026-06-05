"""initial implementation / 229: Provider 凭证相关 URL。

挂载于 friday/urls.py 的 /api/providers/ 前缀下。

路由结构：
- types/                                → ProviderTypesView（initial implementation schema-driven 数据源）
- credentials/                          → ProviderCredentialViewSet（initial implementation CRUD）
- credentials/<uuid>/                   → retrieve / update / partial_update / destroy
- credentials/<uuid>/toggle-active/     → @action toggle_active（initial implementation contract）
- credentials/<uuid>/refresh-models/    → @action refresh_models（initial implementation contract）
- credentials/<uuid>/test-connection/   → ProviderCredentialTestConnectionView（initial implementation 就位）

说明：router 生成的 credentials/<uuid:pk>/ 与 test-connection/ 的 URL 后缀不冲突，
两者共存放置于同一 urlpatterns 下；test-connection 路径段落独立，router 的
TrailingSlashRouter 不会将其误匹配到 retrieve 视图。types/ 是静态路径，显式注册
在 router.urls 之前，避免被 ViewSet 的 list action 误吞。
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ClaudeCodeConfigView,
    ProviderCredentialTestConnectionView,
    ProviderCredentialViewSet,
    ProviderFetchModelsView,
    ProviderTypesView,
)

router = DefaultRouter()
router.register(
    r"credentials",
    ProviderCredentialViewSet,
    basename="provider-credential",
)

urlpatterns = [
    # initial implementation：Provider 类型元信息 + 动态 JSON Schema
    path(
        "types/",
        ProviderTypesView.as_view(),
        name="provider-types",
    ),
    # 无状态模型探测：无状态「试拉模型」（新建凭证表单，config 不落库）
    path(
        "fetch-models/",
        ProviderFetchModelsView.as_view(),
        name="provider-fetch-models",
    ),
    # Claude Code 编码容器配置：Claude Code 编码容器配置（选凭证 + 三档模型映射）
    path(
        "claude-code-config/",
        ClaudeCodeConfigView.as_view(),
        name="claude-code-config",
    ),
    # initial implementation contract：健康检查端点（保留既有实现，route 独立于 ViewSet）
    path(
        "credentials/<uuid:credential_id>/test-connection/",
        ProviderCredentialTestConnectionView.as_view(),
        name="provider-credential-test-connection",
    ),
    # initial implementation contract / contract / contract：ViewSet CRUD + @action toggle-active / refresh-models
    *router.urls,
]
