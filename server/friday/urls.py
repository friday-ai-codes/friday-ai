"""
URL configuration for friday project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

# API routes (under /api prefix)
api_patterns = [
    # Authentication (accounts app)
    path("auth/", include("accounts.urls")),
    # Spaces
    path("spaces/", include("projects.urls")),
    # Projects（v0.15.0 项目聚合根：CRUD/状态/成员/主R 转移/工件/知识关联）
    path("projects/", include("initiatives.urls")),
    # 工件类型管理（v0.15.0 Phase 79，超管 CRUD）
    path("artifact-types/", include("initiatives.artifact_type_urls")),
    # Repositories
    path("repositories/", include("repositories.urls")),
    # Feishu integration (webhook + logs)
    path("feishu/", include("feishu.urls")),
    # System settings
    path("settings/", include("system.urls")),
    # System-level health and status
    path("system/", include("system.urls_system")),
    # implementation contract：Provider 凭证（仅 test-connection；CRUD 归 implementation）
    path("providers/", include("system.urls_providers")),
    # OIDC authentication
    path("oidc/", include("identity.urls")),
    # Chat (LLM conversation)
    path("chat/", include("chat.urls")),
    # 管理员只读会话后台（Phase 9 ADMVW）：与 chat/ 物理分离，IsSuperUser 守卫
    path("admin/", include("chat.admin_urls")),
    # Prompts (implementation 统一提示词管理)
    path("prompts/", include("prompts.urls")),
    # Workflows
    path("", include("workflows.urls")),
    # SubAgent integration
    path("subagent/", include("subagent.urls")),
    # Container callbacks (ContainerCallbackView)
    path("containers/", include("subagent.api.urls")),
    # Runners
    path("runners/", include("runners.urls")),
    # Access Tokens（外部 MCP/Skill 统一鉴权凭证）
    path("access-tokens/", include("access_tokens.urls")),
    # 操作审计查询/导出（v0.10.0 AUDITUI；只读，IsSuperUser fail-closed）
    path("audit/", include("audit.urls")),
    # 站内信通知（owner-scoped；列表/未读数/已读）
    path("notifications/", include("notifications.urls")),
    # 系统公告（用户端，owner-scoped 可见性；列表/未读数/弹窗/已读）
    path("announcements/", include("notifications.announcement_urls")),
    # 系统公告管理端（IsSuperUser；CRUD + 已读状态）
    path("admin/announcements/", include("notifications.admin_urls")),
    # 用户反馈（提交/列表/详情/附件上传）
    path("feedback/", include("feedback.urls")),
    # 用户反馈管理端（IsSuperUser；列表/详情/回复/改状态）
    path("admin/feedback/", include("feedback.admin_urls")),
    # MCP read tools（外部仓库智能只读工具）
    path("mcp/", include("mcp_tools.urls")),
    # Tool bindings + RemoteTool execute（Phase 10：令牌绑定 CRUD + PAT 执行端点）
    path("tools/", include("tools.urls")),
    # Agent tools API
    path("agents/", include("agents.urls")),
    # Knowledge retrieval（Phase 15 内部测试 REST）
    path("knowledge/", include("knowledge.api.urls")),
    # Delivery 交付脊柱（Phase 28：手动 upsert + 读取 WorkItem）
    path("delivery/", include("delivery.urls")),
    # SDD spec 治理（Phase 50：状态机流转 + 评审；list/detail/transition）
    path("specs/", include("delivery.spec_urls")),
    # API Documentation
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    # All API endpoints under /api
    path("api/", include(api_patterns)),
    # Galaxy API（implementation/04/05）：与 playground 并列
    path("api/codegraph/galaxy/", include("codegraph.galaxy.urls")),
    # codegraph Playground（implementation contract）：与 /api/ 并列，裸前缀让 admin 直接访问
    path("api/codegraph/", include("codegraph.playground_urls")),
    # OpenAI 协议兼容层（contract）：与 /api/ 并列，裸前缀让 OpenAI SDK 直接接入
    path("v1/", include("compat.urls")),
    # Health check (outside /api prefix)
    path("health", include("accounts.urls_health")),
]
